//! Workbook charts as deterministic SVG (v3 `_xlsx_chart_svg`,
//! `_xlsx_series_values`, `_xlsx_category_values`).

use std::f64::consts::PI;

use super::book::{Chart, ChartKind, Series, Workbook};
use super::formula::{column_letter, range_boundaries, Book, Evaluation};
use super::value::{parse_py_float, py_sum, Value};
use crate::preview::html::escape;

const PALETTE: [&str; 5] = ["#2563eb", "#0f766e", "#f59e0b", "#dc2626", "#7c3aed"];

/// The cells of `formula` (`Sheet!$A$1:$A$9`) read through the evaluation,
/// `fallback` where a formula cannot be evaluated. `None` when the reference
/// does not name a worksheet range.
fn reference_cells(
    book: &Workbook,
    evaluation: &mut Evaluation<Workbook>,
    formula: &str,
    fallback: Value,
) -> Option<Vec<Value>> {
    let (sheet_name, cell_range) = formula.rsplit_once('!')?;
    let sheet_name = sheet_name.trim_matches('\'').replace("''", "'");
    if !book.sheet_exists(&sheet_name) {
        return None;
    }
    let sheet = book.worksheet(&sheet_name)?;
    let (c1, r1, c2, r2) = range_boundaries(cell_range)?;
    let (c1, r1) = (c1.unwrap_or(1), r1.unwrap_or(1));
    let c2 = c2.unwrap_or_else(|| sheet.max_column());
    let r2 = r2.unwrap_or_else(|| sheet.max_row());
    let mut values = Vec::new();
    for row in r1..=r2 {
        for column in c1..=c2 {
            let coordinate = format!("{}{row}", column_letter(column));
            values.push(evaluation.display_value(&sheet_name, &coordinate, fallback.clone()));
        }
    }
    Some(values)
}

fn series_values(
    book: &Workbook,
    evaluation: &mut Evaluation<Workbook>,
    series: &Series,
) -> Vec<f64> {
    if let Some(points) = &series.val_lit {
        return points
            .iter()
            .map(|p| p.as_deref().and_then(parse_py_float).unwrap_or(0.0))
            .collect();
    }
    let Some(formula) = &series.val_ref else {
        return Vec::new();
    };
    reference_cells(book, evaluation, formula, Value::Int(0))
        .unwrap_or_default()
        .iter()
        .map(|v| {
            if v.truthy() {
                v.py_float().unwrap_or(0.0)
            } else {
                0.0
            }
        })
        .collect()
}

fn category_values(
    book: &Workbook,
    evaluation: &mut Evaluation<Workbook>,
    series: &Series,
) -> Vec<String> {
    let Some(formula) = &series.cat_ref else {
        return Vec::new();
    };
    reference_cells(book, evaluation, formula, Value::Str(String::new()))
        .unwrap_or_default()
        .iter()
        .map(|v| {
            if v.truthy() {
                v.py_str()
            } else {
                String::new()
            }
        })
        .collect()
}

/// Render a workbook chart as an SVG preview.
pub fn chart_svg(book: &Workbook, chart: &Chart, evaluation: &mut Evaluation<Workbook>) -> String {
    let series_values: Vec<Vec<f64>> = chart
        .series
        .iter()
        .map(|s| series_values(book, evaluation, s))
        .filter(|v| !v.is_empty())
        .collect();
    if series_values.is_empty() {
        return "<div class=\"chart-empty\">Chart data unavailable</div>".to_string();
    }
    let mut maximum = series_values
        .iter()
        .flatten()
        .map(|v| v.abs())
        .fold(None, |acc: Option<f64>, v| {
            Some(acc.map_or(v, |a| if v > a { v } else { a }))
        })
        .unwrap_or(1.0);
    if maximum == 0.0 {
        maximum = 1.0;
    }
    // Values below zero: v3 scaled by the largest magnitude from a fixed
    // baseline, so negative bars and points fell outside the chart. With
    // negatives the baseline moves up to make room; without, it is v3's.
    let negative = series_values
        .iter()
        .flatten()
        .filter(|v| **v < 0.0)
        .fold(0.0f64, |a, v| a.max(-v));
    let (span, bar_base, line_base) = if negative > 0.0 {
        let positive = series_values
            .iter()
            .flatten()
            .fold(0.0f64, |a, v| a.max(*v));
        let span = positive + negative;
        (
            span,
            42.0 + positive / span * 210.0,
            47.0 + positive / span * 205.0,
        )
    } else {
        (maximum, 252.0, 252.0)
    };
    let axis = |y: f64| {
        if negative > 0.0 {
            format!("{y:.2}")
        } else {
            "252".to_string()
        }
    };
    let count = series_values.iter().map(Vec::len).max().unwrap_or(0);
    let categories = match chart.series.first() {
        Some(first) => category_values(book, evaluation, first),
        None => Vec::new(),
    };

    let category_labels = || -> String {
        if categories.is_empty() {
            return String::new();
        }
        let max_labels = 6;
        let visible: Vec<usize> = if categories.len() <= max_labels {
            (0..categories.len()).collect()
        } else {
            let step = (categories.len() - 1).div_ceil(max_labels - 1);
            let mut v: Vec<usize> = (0..categories.len()).step_by(step).collect();
            if *v.last().expect("non-empty") != categories.len() - 1 {
                v.push(categories.len() - 1);
            }
            v
        };
        let denominator = (categories.len().max(2) - 1) as f64;
        visible
            .iter()
            .map(|&index| {
                let x = 52.0 + (index * 520) as f64 / denominator;
                let label: String = categories[index].chars().take(14).collect();
                format!(
                    "<text x=\"{x:.2}\" y=\"278\" text-anchor=\"end\" font-size=\"10\" fill=\"#6b7280\" transform=\"rotate(-32 {x:.2} 278)\">{}</text>",
                    escape(&label)
                )
            })
            .collect()
    };

    match chart.kind {
        ChartKind::Pie | ChartKind::Doughnut => {
            let values: Vec<f64> = series_values[0].iter().map(|v| v.abs()).collect();
            let total = py_sum(&values).py_float().unwrap_or(0.0);
            let total = if total == 0.0 { 1.0 } else { total };
            let mut start = -PI / 2.0;
            let mut slices = String::new();
            for (index, value) in values.iter().enumerate() {
                let end = start + 2.0 * PI * value / total;
                if *value > 0.0 && *value >= total {
                    // A single full slice: an arc back to its own start point
                    // draws nothing (v3 left the pie empty).
                    slices.push_str(&format!(
                        "<circle cx=\"300\" cy=\"150\" r=\"108\" fill=\"{}\"/>",
                        PALETTE[index % PALETTE.len()]
                    ));
                    start = end;
                    continue;
                }
                let (sx, sy) = (300.0 + 108.0 * start.cos(), 150.0 + 108.0 * start.sin());
                let (ex, ey) = (300.0 + 108.0 * end.cos(), 150.0 + 108.0 * end.sin());
                let large = if end - start > PI { 1 } else { 0 };
                slices.push_str(&format!(
                    "<path d=\"M300 150 L{sx:.2} {sy:.2} A108 108 0 {large} 1 {ex:.2} {ey:.2} Z\" fill=\"{}\"/>",
                    PALETTE[index % PALETTE.len()]
                ));
                start = end;
            }
            let hole = if chart.kind == ChartKind::Doughnut {
                "<circle cx=\"300\" cy=\"150\" r=\"65\" fill=\"white\"/>"
            } else {
                ""
            };
            format!(
                "<svg class=\"workbook-chart-svg\" viewBox=\"0 0 600 300\">{slices}{hole}</svg>"
            )
        }
        ChartKind::Area | ChartKind::Line => {
            let mut paths = String::new();
            for (series_index, values) in series_values.iter().enumerate() {
                let denominator = (values.len().max(2) - 1) as f64;
                let points: Vec<(f64, f64)> = values
                    .iter()
                    .enumerate()
                    .map(|(i, v)| {
                        (
                            52.0 + (i * 520) as f64 / denominator,
                            line_base - (v / span) * 205.0,
                        )
                    })
                    .collect();
                let point_text: Vec<String> = points
                    .iter()
                    .map(|(x, y)| format!("{x:.2},{y:.2}"))
                    .collect();
                let color = PALETTE[series_index % PALETTE.len()];
                let mut area = String::new();
                if chart.kind == ChartKind::Area && !points.is_empty() {
                    let mut polygon = vec![format!("{:.2},{}", points[0].0, axis(line_base))];
                    polygon.extend(point_text.iter().cloned());
                    polygon.push(format!(
                        "{:.2},{}",
                        points[points.len() - 1].0,
                        axis(line_base)
                    ));
                    area = format!(
                        "<polygon class=\"workbook-chart-area\" points=\"{}\" fill=\"{color}\" fill-opacity=\".24\"/>",
                        polygon.join(" ")
                    );
                }
                let markers: String = points
                    .iter()
                    .map(|(x, y)| {
                        format!("<circle cx=\"{x:.2}\" cy=\"{y:.2}\" r=\"4\" fill=\"{color}\"/>")
                    })
                    .collect();
                paths.push_str(&format!(
                    "{area}<polyline points=\"{}\" fill=\"none\" stroke=\"{color}\" stroke-width=\"4\"/>{markers}",
                    point_text.join(" ")
                ));
            }
            format!(
                "<svg class=\"workbook-chart-svg\" viewBox=\"0 0 600 300\" preserveAspectRatio=\"none\"><line x1=\"45\" y1=\"{AXIS}\" x2=\"575\" y2=\"{AXIS}\" stroke=\"#9ca3af\"/>{paths}{}</svg>",
                category_labels(),
                AXIS = axis(line_base),
            )
        }
        ChartKind::Bar => {
            let group_width = 520.0 / count.max(1) as f64;
            let bar_width = (group_width / series_values.len().max(1) as f64 * 0.72).max(2.0);
            let mut bars = String::new();
            for (series_index, values) in series_values.iter().enumerate() {
                for (value_index, value) in values.iter().enumerate() {
                    let height = value.abs() / span * 210.0;
                    let x =
                        52.0 + value_index as f64 * group_width + series_index as f64 * bar_width;
                    let y = if *value >= 0.0 {
                        bar_base - height
                    } else {
                        bar_base
                    };
                    bars.push_str(&format!(
                        "<rect x=\"{x:.2}\" y=\"{y:.2}\" width=\"{bar_width:.2}\" height=\"{height:.2}\" fill=\"{}\"/>",
                        PALETTE[series_index % PALETTE.len()]
                    ));
                }
            }
            format!(
                "<svg class=\"workbook-chart-svg\" viewBox=\"0 0 600 300\" preserveAspectRatio=\"none\"><line x1=\"45\" y1=\"{BAXIS}\" x2=\"575\" y2=\"{BAXIS}\" stroke=\"#9ca3af\"/>{bars}</svg>",
                BAXIS = axis(bar_base),
            )
        }
    }
}
