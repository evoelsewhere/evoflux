//! Charts to inline SVG (v3 `_chart_svg` and helpers), reading the chart part
//! with python-pptx's semantics: chart type from the first plot, series in
//! `c:order` order across plots, cached values, the second value axis of a
//! scatter chart as its value axis.

use std::collections::HashMap;

use super::super::html::escape;
use super::color::{color_format_css, Palette};
use super::util::{
    child, child_ns, elements, f, first_child, g, isclose, local, own_text, pct0, py_float, py_int,
    py_sum, repr, Nd, Skip, C, R,
};

const FALLBACK_PALETTE: [&str; 6] = [
    "#4472c4", "#ed7d31", "#a5a5a5", "#ffc000", "#5b9bd5", "#70ad47",
];

const XCHART_TAGS: [&str; 16] = [
    "area3DChart",
    "areaChart",
    "bar3DChart",
    "barChart",
    "bubbleChart",
    "doughnutChart",
    "line3DChart",
    "lineChart",
    "ofPieChart",
    "pie3DChart",
    "pieChart",
    "radarChart",
    "scatterChart",
    "stockChart",
    "surface3DChart",
    "surfaceChart",
];
/// Plots python-pptx models (`PlotFactory`).
const PLOT_TAGS: [&str; 9] = [
    "areaChart",
    "area3DChart",
    "barChart",
    "bubbleChart",
    "doughnutChart",
    "lineChart",
    "pieChart",
    "radarChart",
    "scatterChart",
];

struct Chart<'a> {
    chart: Nd<'a>,
    plot_area: Nd<'a>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum AxisKind {
    Category,
    Date,
    Value,
}

#[derive(Clone, Copy)]
struct Axis<'a> {
    node: Nd<'a>,
    kind: AxisKind,
}

struct Record<'a> {
    name: String,
    values: Vec<f64>,
    color: String,
    ser: Nd<'a>,
}

fn c_child<'a>(node: Nd<'a>, name: &str) -> Option<Nd<'a>> {
    child_ns(node, C, name)
}

fn c_children<'a>(node: Nd<'a>, name: &'a str) -> impl Iterator<Item = Nd<'a>> + 'a {
    elements(node).filter(move |e| local(*e) == name && e.tag_name().namespace() == Some(C))
}

fn c_descendants<'a>(node: Nd<'a>, name: &'a str) -> impl Iterator<Item = Nd<'a>> + 'a {
    super::util::descendants_ns(node, C, name)
}

impl<'a> Chart<'a> {
    fn xcharts(&self) -> Vec<Nd<'a>> {
        elements(self.plot_area)
            .filter(|e| e.tag_name().namespace() == Some(C) && XCHART_TAGS.contains(&local(*e)))
            .collect()
    }

    fn axes(&self, name: &'a str) -> Vec<Nd<'a>> {
        c_children(self.plot_area, name).collect()
    }

    fn value_axis(&self) -> Option<Axis<'a>> {
        let axes = self.axes("valAx");
        let index = if axes.len() > 1 { 1 } else { 0 };
        axes.get(index).map(|node| Axis {
            node: *node,
            kind: AxisKind::Value,
        })
    }

    fn category_axis(&self) -> Option<Axis<'a>> {
        if let Some(node) = self.axes("catAx").first() {
            return Some(Axis {
                node: *node,
                kind: AxisKind::Category,
            });
        }
        if let Some(node) = self.axes("dateAx").first() {
            return Some(Axis {
                node: *node,
                kind: AxisKind::Date,
            });
        }
        self.axes("valAx").first().map(|node| Axis {
            node: *node,
            kind: AxisKind::Value,
        })
    }

    fn legend(&self) -> Option<Nd<'a>> {
        c_child(self.chart, "legend")
    }

    fn has_legend(&self) -> bool {
        self.legend().is_some()
    }

    /// v3 `_chart_legend_position`.
    fn legend_position(&self) -> &'static str {
        let Some(legend) = self.legend() else {
            return "right";
        };
        let value = c_child(legend, "legendPos")
            .and_then(|p| p.attribute("val"))
            .unwrap_or("r");
        match value {
            "b" => "bottom",
            "tr" => "corner",
            "l" => "left",
            "t" => "top",
            _ => "right",
        }
    }

    /// v3 `_chart_data_labels_enabled`: whether any plot has `c:dLbls`.
    ///
    /// Fix over v3: python-pptx's scatter (and 3-D area) plot has no
    /// `has_data_labels`, so v3 answered False for every scatter chart and for
    /// any chart whose plots reached one before a labelled plot.
    fn data_labels(&self) -> bool {
        self.xcharts()
            .into_iter()
            .any(|plot| c_child(plot, "dLbls").is_some())
    }

    fn major_gridlines(&self) -> bool {
        axis_gridlines(self.value_axis())
    }

    /// `chart.series`: every plot's series, each plot's in `c:order` order.
    fn series(&self) -> R<Vec<Nd<'a>>> {
        let mut result = Vec::new();
        for plot in self.xcharts() {
            let mut sers = Vec::new();
            for ser in c_children(plot, "ser") {
                // `c:order` as Python reads it: any (signed, unbounded) int.
                let order = c_child(ser, "order")
                    .and_then(|o| o.attribute("val"))
                    .and_then(big_int_key)
                    .ok_or(Skip)?;
                sers.push((order, ser));
            }
            sers.sort_by_key(|(order, _)| *order);
            result.extend(sers.into_iter().map(|(_, ser)| ser));
        }
        Ok(result)
    }
}

/// A Python `int(str)` as a sortable key (values beyond i128 saturate).
fn big_int_key(raw: &str) -> Option<i128> {
    let text = raw.trim();
    if let Ok(value) = text.parse::<i128>() {
        return Some(value);
    }
    let (negative, digits) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text.strip_prefix('+').unwrap_or(text)),
    };
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some(if negative { i128::MIN } else { i128::MAX })
}

fn axis_gridlines(axis: Option<Axis<'_>>) -> bool {
    axis.is_some_and(|a| c_child(a.node, "majorGridlines").is_some())
}

fn grouping<'a>(plot: Nd<'a>, default: &'a str) -> Result<&'a str, ()> {
    match c_child(plot, "grouping").and_then(|g| g.attribute("val")) {
        None => Ok(default),
        Some(value @ ("clustered" | "percentStacked" | "stacked" | "standard")) => Ok(value),
        Some(_) => Err(()),
    }
}

/// v3 `_chart_type_name` (python-pptx `PlotTypeInspector`).
///
/// Fix over v3: where python-pptx raised outside its `ValueError` contract
/// (no plot at all; a `c:grouping` the chart kind does not use, such as
/// `standard` on a bar chart; a missing `c:barDir`, `c:radarStyle` or
/// `c:scatterStyle`), v3 lost the chart or failed the whole deck. Here a chart
/// without plots is `UNKNOWN` (the "Unsupported chart type" note), an
/// unexpected grouping reads as the kind's default and missing children take
/// their schema defaults.
fn chart_type_name(chart: &Chart<'_>) -> R<String> {
    let plots = chart.xcharts();
    let Some(plot) = plots.first().copied() else {
        return Ok("UNKNOWN".into());
    };
    let tag = local(plot);
    if !PLOT_TAGS.contains(&tag) {
        return Ok("UNKNOWN".into());
    }
    let unknown = || Ok("UNKNOWN".to_string());
    let by_grouping = |default: &str, names: [(&str, &str); 3]| -> R<String> {
        let Ok(value) = grouping(plot, default) else {
            return unknown();
        };
        let found = names
            .iter()
            .find(|(key, _)| *key == value)
            .unwrap_or(&names[0]);
        Ok(found.1.to_string())
    };
    let ser_has =
        |child_name: &str| c_children(plot, "ser").any(|s| c_child(s, child_name).is_some());
    let symbols = || -> Vec<Option<&str>> {
        c_children(plot, "ser")
            .filter_map(|s| c_child(s, "marker"))
            .filter_map(|m| c_child(m, "symbol"))
            .map(|s| s.attribute("val"))
            .collect()
    };
    match tag {
        "areaChart" => by_grouping(
            "standard",
            [
                ("standard", "AREA"),
                ("stacked", "AREA_STACKED"),
                ("percentStacked", "AREA_STACKED_100"),
            ],
        ),
        "area3DChart" => by_grouping(
            "standard",
            [
                ("standard", "THREE_D_AREA"),
                ("stacked", "THREE_D_AREA_STACKED"),
                ("percentStacked", "THREE_D_AREA_STACKED_100"),
            ],
        ),
        "barChart" => {
            let direction = c_child(plot, "barDir").and_then(|d| d.attribute("val"));
            match direction.unwrap_or("col") {
                "bar" => by_grouping(
                    "clustered",
                    [
                        ("clustered", "BAR_CLUSTERED"),
                        ("stacked", "BAR_STACKED"),
                        ("percentStacked", "BAR_STACKED_100"),
                    ],
                ),
                "col" => by_grouping(
                    "clustered",
                    [
                        ("clustered", "COLUMN_CLUSTERED"),
                        ("stacked", "COLUMN_STACKED"),
                        ("percentStacked", "COLUMN_STACKED_100"),
                    ],
                ),
                _ => unknown(),
            }
        }
        "bubbleChart" => {
            let first = c_children(plot, "ser").find_map(|s| c_child(s, "bubble3D"));
            Ok(match first {
                Some(node) if !matches!(node.attribute("val"), Some("0") | Some("false")) => {
                    "BUBBLE_THREE_D_EFFECT".into()
                }
                _ => "BUBBLE".into(),
            })
        }
        "doughnutChart" => Ok(if ser_has("explosion") {
            "DOUGHNUT_EXPLODED"
        } else {
            "DOUGHNUT"
        }
        .into()),
        "pieChart" => Ok(if ser_has("explosion") {
            "PIE_EXPLODED"
        } else {
            "PIE"
        }
        .into()),
        "lineChart" => {
            let no_markers = symbols().contains(&Some("none"));
            if no_markers {
                by_grouping(
                    "standard",
                    [
                        ("standard", "LINE"),
                        ("stacked", "LINE_STACKED"),
                        ("percentStacked", "LINE_STACKED_100"),
                    ],
                )
            } else {
                by_grouping(
                    "standard",
                    [
                        ("standard", "LINE_MARKERS"),
                        ("stacked", "LINE_MARKERS_STACKED"),
                        ("percentStacked", "LINE_MARKERS_STACKED_100"),
                    ],
                )
            }
        }
        "radarChart" => {
            let style = c_child(plot, "radarStyle").and_then(|s| s.attribute("val"));
            let no_markers = symbols().first().copied().flatten() == Some("none");
            Ok(match style {
                None => "RADAR",
                Some("filled") => "RADAR_FILLED",
                _ if no_markers => "RADAR",
                _ => "RADAR_MARKERS",
            }
            .into())
        }
        "scatterChart" => {
            let style = c_child(plot, "scatterStyle").and_then(|s| s.attribute("val"));
            let no_line = c_children(plot, "ser")
                .filter_map(|s| c_child(s, "spPr"))
                .filter_map(|p| child_ns(p, super::util::A, "ln"))
                .any(|l| child_ns(l, super::util::A, "noFill").is_some());
            let no_markers = symbols().first().copied().flatten() == Some("none");
            Ok(match style {
                Some("lineMarker") if no_line => "XY_SCATTER",
                Some("lineMarker") if no_markers => "XY_SCATTER_LINES_NO_MARKERS",
                Some("lineMarker") => "XY_SCATTER_LINES",
                Some("smoothMarker") if no_markers => "XY_SCATTER_SMOOTH_NO_MARKERS",
                Some("smoothMarker") => "XY_SCATTER_SMOOTH",
                _ => "XY_SCATTER",
            }
            .into())
        }
        _ => unknown(),
    }
}

/// XPath `number(@idx)`.
fn xpath_number(raw: &str) -> Option<f64> {
    let trimmed = raw.trim();
    if trimmed.is_empty()
        || !trimmed
            .chars()
            .all(|c| c.is_ascii_digit() || matches!(c, '.' | '-'))
    {
        return None;
    }
    trimmed.parse().ok()
}

/// python-pptx `CT_NumDataSource` values (`ptCount` slots, `None` for gaps).
///
/// Fix over v3: an unreadable count, a point without `c:v` or a value that is
/// not a number made python-pptx raise and v3 lose the chart; here such a
/// count reads as 0 and such a point as a gap.
fn data_source_values(source: Option<Nd<'_>>) -> R<Vec<Option<f64>>> {
    let Some(source) = source else {
        return Ok(Vec::new());
    };
    let count = match c_descendants(source, "ptCount").find_map(|n| n.attribute("val")) {
        Some(raw) => py_int(raw).unwrap_or(0),
        None => 0,
    };
    let mut by_index: HashMap<i64, Nd<'_>> = HashMap::new();
    for point in c_descendants(source, "pt") {
        if let Some(number) = point.attribute("idx").and_then(xpath_number) {
            if number.fract() == 0.0 {
                by_index.entry(number as i64).or_insert(point);
            }
        }
    }
    let mut values = Vec::new();
    for index in 0..count.clamp(0, super::util::MAX_POINTS) {
        match by_index.get(&index) {
            Some(point) => values.push(c_child(*point, "v").and_then(own_text).and_then(py_float)),
            None => values.push(None),
        }
    }
    Ok(values)
}

/// v3 `_chart_cache_values`: points of a branch sorted by index.
fn cache_values(ser: Nd<'_>, branch: &str) -> Vec<f64> {
    let Some(source) = child(ser, branch) else {
        return Vec::new();
    };
    let mut indexed: Vec<(i64, f64)> = Vec::new();
    for point in source
        .descendants()
        .filter(|d| d.is_element() && local(*d) == "pt")
    {
        let Some(v) = child(point, "v") else {
            continue;
        };
        let index = match point.attribute("idx") {
            Some(raw) => match py_int(raw) {
                Some(i) => i,
                None => continue,
            },
            None => indexed.len() as i64,
        };
        let text = own_text(v).filter(|t| !t.is_empty()).unwrap_or("0");
        let Some(value) = py_float(text) else {
            continue;
        };
        indexed.push((index, if value.is_finite() { value } else { 0.0 }));
    }
    indexed.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then(a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
    });
    indexed.into_iter().map(|(_, v)| v).collect()
}

/// v3 `_chart_series_name`.
fn series_name(ser: Nd<'_>, index: usize) -> String {
    let python_pptx = c_child(ser, "tx").and_then(|tx| {
        c_descendants(tx, "pt")
            .filter_map(|pt| c_child(pt, "v"))
            .flat_map(|v| {
                v.children()
                    .filter(|n| n.is_text())
                    .filter_map(|n| n.text())
                    .collect::<Vec<_>>()
            })
            .next()
    });
    let name = super::util::py_strip(python_pptx.unwrap_or(""));
    if !name.is_empty() {
        return name.to_string();
    }
    if let Some(tx) = child(ser, "tx") {
        for v in tx
            .descendants()
            .filter(|d| d.is_element() && local(*d) == "v")
        {
            let text = super::util::py_strip(own_text(v).unwrap_or(""));
            if !text.is_empty() {
                return text.to_string();
            }
        }
    }
    format!("Series {}", index + 1)
}

/// The fill colour choice python-pptx's `fill.fore_color` reads, if any.
fn fill_fore_color(sp_pr: Nd<'_>) -> Option<Option<Nd<'_>>> {
    let fill = elements(sp_pr).find(|e| {
        matches!(
            local(*e),
            "noFill" | "solidFill" | "gradFill" | "blipFill" | "pattFill" | "grpFill"
        )
    })?;
    match local(fill) {
        "solidFill" => Some(first_child(Some(fill))),
        "pattFill" => Some(first_child(child(fill, "fgClr"))),
        _ => None,
    }
}

/// v3 `_chart_series_color`.
fn series_color(ser: Nd<'_>, index: usize, palette: &Palette) -> String {
    let sp_pr = c_child(ser, "spPr");
    if let Some(color) = sp_pr.and_then(fill_fore_color) {
        if let Some(css) = color_format_css(color, palette) {
            if css != "transparent" {
                return css;
            }
        }
    }
    let line_color = sp_pr
        .and_then(|p| child_ns(p, super::util::A, "ln"))
        .and_then(|ln| {
            elements(ln).find(|e| {
                matches!(
                    local(*e),
                    "noFill" | "solidFill" | "gradFill" | "blipFill" | "pattFill" | "grpFill"
                )
            })
        })
        .filter(|fill| local(*fill) == "solidFill")
        .map(|fill| first_child(Some(fill)));
    let css = match line_color {
        Some(color) => color_format_css(color, palette),
        None => Some("transparent".into()),
    };
    if let Some(css) = css.filter(|c| c != "transparent") {
        return css;
    }
    FALLBACK_PALETTE[index % FALLBACK_PALETTE.len()].to_string()
}

/// v3 `_chart_series_records`.
fn series_records<'a>(chart: &Chart<'a>, palette: &Palette) -> R<Vec<Record<'a>>> {
    let mut records = Vec::new();
    for (index, ser) in chart.series()?.into_iter().enumerate() {
        let parent = ser.parent_element().map(local).unwrap_or("");
        let branch = match parent {
            "areaChart" | "barChart" | "doughnutChart" | "lineChart" | "pieChart"
            | "radarChart" => "val",
            "scatterChart" | "bubbleChart" => "yVal",
            // Fix over v3: a series of a plot python-pptx does not model (a
            // 3-D plot next to a 2-D one) raised and lost the chart; skip it.
            _ => continue,
        };
        let raw = data_source_values(c_child(ser, branch))?;
        // Fix over v3: a non-finite cached value (`inf`, `NaN`) made v3's axis
        // scaling raise (`OverflowError` failed the whole deck); it counts as 0.
        let mut values: Vec<f64> = raw
            .into_iter()
            .map(|v| v.filter(|v| v.is_finite()).unwrap_or(0.0))
            .collect();
        if values.is_empty() {
            values = cache_values(ser, "yVal");
        }
        if values.is_empty() {
            continue;
        }
        records.push(Record {
            name: series_name(ser, index),
            values,
            color: series_color(ser, index, palette),
            ser,
        });
    }
    Ok(records)
}

/// v3 `_chart_categories`.
fn categories(chart: &Chart<'_>) -> R<Vec<String>> {
    let Some(plot) = chart.xcharts().first().copied() else {
        return Ok(Vec::new());
    };
    let count = match c_children(plot, "ser")
        .filter_map(|s| c_child(s, "cat"))
        .find_map(|cat| c_descendants(cat, "ptCount").next())
    {
        Some(node) => match node.attribute("val").map(py_int) {
            Some(Some(v)) => v,
            Some(None) => return Ok(Vec::new()),
            // Fix over v3 (raised): a `c:ptCount` without a value counts 0.
            None => 0,
        },
        None => 0,
    };
    let first_cat = c_children(plot, "ser")
        .next()
        .and_then(|s| c_child(s, "cat"));
    let mut points: Vec<Nd<'_>> = Vec::new();
    if let Some(cat) = first_cat {
        for level in c_descendants(cat, "lvl") {
            let first_level = level
                .parent_element()
                .and_then(|p| c_children(p, "lvl").next())
                .is_some_and(|first| first == level);
            if first_level {
                points.extend(c_children(level, "pt"));
            }
        }
        if points.is_empty() {
            points = c_descendants(cat, "pt").collect();
        }
    }
    let mut by_index: HashMap<i64, Nd<'_>> = HashMap::new();
    for point in points {
        // Fix over v3 (raised): a point without `idx` is ignored.
        let Some(raw) = point.attribute("idx") else {
            continue;
        };
        let Some(index) = py_int(raw).filter(|i| *i >= 0) else {
            return Ok(Vec::new());
        };
        by_index.insert(index, point);
    }
    let mut labels = Vec::new();
    for index in 0..count.clamp(0, super::util::MAX_POINTS) {
        labels.push(match by_index.get(&index) {
            // Fix over v3 (raised): a point without `c:v` is an empty label.
            Some(point) => match c_child(*point, "v") {
                Some(v) => own_text(v).unwrap_or("None").to_string(),
                None => String::new(),
            },
            None => String::new(),
        });
    }
    Ok(labels)
}

/// The minimum/maximum scale of an axis (`Err` where python-pptx raised).
fn axis_limits(axis: Option<Axis<'_>>) -> R<(Option<f64>, Option<f64>)> {
    let Some(axis) = axis else {
        return Ok((None, None));
    };
    // Fix over v3 (raised): an axis without `c:scaling` has no limits.
    let Some(scaling) = c_child(axis.node, "scaling") else {
        return Ok((None, None));
    };
    let read = |name: &str| -> Result<Option<f64>, ()> {
        match c_child(scaling, name) {
            None => Ok(None),
            Some(node) => node.attribute("val").and_then(py_float).map(Some).ok_or(()),
        }
    };
    let Ok(lower) = read("min") else {
        return Ok((None, None));
    };
    let Ok(upper) = read("max") else {
        return Ok((lower, None));
    };
    Ok((lower, upper))
}

/// v3 `_chart_axis_major_unit`.
fn major_unit(axis: Option<Axis<'_>>, lower: f64, upper: f64) -> f64 {
    let explicit = axis
        .filter(|a| a.kind == AxisKind::Value)
        .and_then(|a| c_child(a.node, "majorUnit"))
        .and_then(|u| u.attribute("val"))
        .and_then(py_float)
        .unwrap_or(0.0);
    if explicit > 0.0 {
        return explicit;
    }
    let span = (upper - lower).max(1e-12);
    if span <= 10.0
        && isclose(lower, lower.round_ties_even(), 1e-9)
        && isclose(upper, upper.round_ties_even(), 1e-9)
    {
        return 1.0;
    }
    let rough = span / 7.0;
    let magnitude = 10f64.powf(rough.log10().floor());
    let fraction = rough / magnitude;
    let mut best = 1.0;
    let mut best_score = f64::INFINITY;
    for candidate in [1.0, 2.0, 2.5, 5.0, 10.0] {
        let score = (candidate / fraction).ln().abs();
        if score < best_score {
            best = candidate;
            best_score = score;
        }
    }
    best * magnitude
}

fn py_min(values: &[f64]) -> f64 {
    values
        .iter()
        .copied()
        .fold(0.0, |acc, v| if v < acc { v } else { acc })
}

fn py_max(values: &[f64]) -> f64 {
    values
        .iter()
        .copied()
        .fold(0.0, |acc, v| if v > acc { v } else { acc })
}

/// v3 `_chart_scale`.
fn scale(values: &[f64], axis: Option<Axis<'_>>) -> R<(f64, f64)> {
    let data_lower = py_min(values);
    let data_upper = py_max(values);
    let (explicit_lower, explicit_upper) = axis_limits(axis)?;
    let mut lower = explicit_lower.unwrap_or(data_lower);
    let mut upper = explicit_upper.unwrap_or(data_upper);
    if isclose(lower, upper, 0.0) {
        upper = lower + 1.0;
    }
    let unit = major_unit(axis, lower, upper);
    if explicit_lower.is_none() {
        lower = ((data_lower + unit * 1e-9) / unit).floor() * unit;
        if data_lower < 0.0 && isclose(lower, data_lower, unit * 1e-9) {
            lower -= unit;
        }
    }
    if explicit_upper.is_none() {
        upper = ((data_upper - unit * 1e-9) / unit).ceil() * unit;
        if data_upper > 0.0 && isclose(upper, data_upper, unit * 1e-9) {
            upper += unit;
        }
    }
    if isclose(lower, upper, 0.0) {
        upper = lower + unit;
    }
    Ok((lower, upper))
}

/// v3 `_chart_tick_values`.
fn tick_values(lower: f64, upper: f64, axis: Option<Axis<'_>>) -> Vec<f64> {
    let unit = major_unit(axis, lower, upper);
    let first = ((lower - unit * 1e-9) / unit).ceil() * unit;
    let mut ticks = Vec::new();
    let mut value = first;
    while value <= upper + unit * 1e-9 && ticks.len() < 40 {
        ticks.push(if isclose(value, 0.0, unit * 1e-9) {
            0.0
        } else {
            value
        });
        value += unit;
    }
    if ticks.is_empty() {
        vec![lower, upper]
    } else {
        ticks
    }
}

struct Plot {
    left: f64,
    right: f64,
    top: f64,
    bottom: f64,
}

/// v3 `_chart_axes`.
fn axes_svg(
    lower: f64,
    upper: f64,
    baseline: f64,
    gridlines: bool,
    axis: Option<Axis<'_>>,
    plot: &Plot,
) -> String {
    let mut parts = String::new();
    for tick in tick_values(lower, upper, axis).into_iter().rev() {
        let y = plot.bottom - (tick - lower) / (upper - lower) * (plot.bottom - plot.top);
        if gridlines {
            parts.push_str(&format!(
                "<line class=\"chart-gridline\" x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#d9d9d9\" stroke-width=\"1\"/>",
                f(plot.left, 2),
                f(y, 2),
                f(plot.right, 2),
                f(y, 2)
            ));
        }
        parts.push_str(&format!(
            "<text class=\"chart-axis-label chart-axis-label-y\" x=\"{}\" y=\"{}\" text-anchor=\"end\" font-size=\"11\" fill=\"#666\">{}</text>",
            f(plot.left - 7.0, 2),
            f(y + 4.0, 2),
            g(tick)
        ));
    }
    parts.push_str(&format!(
        "<line class=\"chart-axis chart-axis-y\" x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#7f7f7f\"/>",
        f(plot.left, 2),
        f(plot.top, 2),
        f(plot.left, 2),
        f(plot.bottom, 2)
    ));
    parts.push_str(&format!(
        "<line class=\"chart-axis chart-axis-x\" x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#7f7f7f\"/>",
        f(plot.left, 2),
        f(baseline, 2),
        f(plot.right, 2),
        f(baseline, 2)
    ));
    parts
}

/// v3 `_chart_plot_horizontal_bounds`.
fn horizontal_bounds(chart: &Chart<'_>) -> (f64, f64) {
    if !chart.has_legend() {
        return (62.0, 574.0);
    }
    match chart.legend_position() {
        "right" | "corner" => (62.0, 430.0),
        "left" => (170.0, 574.0),
        _ => (62.0, 574.0),
    }
}

fn marker_capable(ser: Nd<'_>) -> bool {
    matches!(
        ser.parent_element().map(local),
        Some("lineChart" | "scatterChart" | "radarChart" | "bubbleChart")
    )
}

/// v3 `_chart_marker_style`.
fn marker_style(ser: Nd<'_>, default: &str) -> String {
    if !marker_capable(ser) {
        return default.into();
    }
    let symbol = c_child(ser, "marker").and_then(|m| c_child(m, "symbol"));
    let Some(symbol) = symbol else {
        return default.into();
    };
    match symbol.attribute("val") {
        Some("auto") => "AUTOMATIC",
        Some("circle") => "CIRCLE",
        Some("dash") => "DASH",
        Some("diamond") => "DIAMOND",
        Some("dot") => "DOT",
        Some("none") => "NONE",
        Some("picture") => "PICTURE",
        Some("plus") => "PLUS",
        Some("square") => "SQUARE",
        Some("star") => "STAR",
        Some("triangle") => "TRIANGLE",
        Some("x") => "X",
        _ => default,
    }
    .into()
}

/// v3 `_chart_marker_svg`.
fn marker_svg(
    ser: Nd<'_>,
    x: f64,
    y: f64,
    color: &str,
    x_compensation: f64,
    default_style: &str,
) -> String {
    let size = if marker_capable(ser) {
        c_child(ser, "marker")
            .and_then(|m| c_child(m, "size"))
            .and_then(|s| s.attribute("val"))
            .and_then(py_int)
            .map(|v| v as f64)
            .unwrap_or(0.0)
    } else {
        0.0
    };
    let radius = (if size != 0.0 { size / 2.0 } else { 4.5 }).clamp(3.0, 12.0);
    let radius_x = radius * x_compensation.max(0.25);
    let style = marker_style(ser, default_style);
    let common = format!("class=\"chart-marker\" fill=\"{color}\"");
    match style.as_str() {
        // Fix over v3: python-pptx names the automatic marker `AUTOMATIC`, so
        // v3's `"AUTO"` branch never matched and automatic markers drew circles.
        "DIAMOND" | "AUTOMATIC" => format!(
            "<polygon {common} data-marker-style=\"diamond\" points=\"{},{} {},{} {},{} {},{}\"/>",
            f(x, 2),
            f(y - radius, 2),
            f(x + radius_x, 2),
            f(y, 2),
            f(x, 2),
            f(y + radius, 2),
            f(x - radius_x, 2),
            f(y, 2)
        ),
        "SQUARE" | "DASH" => format!(
            "<rect {common} data-marker-style=\"square\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"/>",
            f(x - radius_x, 2),
            f(y - radius, 2),
            f(2.0 * radius_x, 2),
            f(2.0 * radius, 2)
        ),
        "TRIANGLE" => format!(
            "<polygon {common} data-marker-style=\"triangle\" points=\"{},{} {},{} {},{}\"/>",
            f(x, 2),
            f(y - radius, 2),
            f(x + radius_x, 2),
            f(y + radius, 2),
            f(x - radius_x, 2),
            f(y + radius, 2)
        ),
        _ => format!(
            "<ellipse {common} data-marker-style=\"circle\" cx=\"{}\" cy=\"{}\" rx=\"{}\" ry=\"{}\"/>",
            f(x, 2),
            f(y, 2),
            f(radius_x, 2),
            f(radius, 2)
        ),
    }
}

/// v3 `_chart_legend`.
fn legend_svg(
    chart: &Chart<'_>,
    names: &[&str],
    colors: &[&str],
    marker_styles: Option<&[String]>,
) -> String {
    let position = chart.legend_position();
    let mut items = String::new();
    let color = |index: usize| colors[index % colors.len()];
    if matches!(position, "top" | "bottom") {
        let y: i64 = if position == "top" { 5 } else { 283 };
        let widths: Vec<i64> = names
            .iter()
            .map(|n| 27 + n.chars().count().min(28) as i64 * 7)
            .collect();
        let total = widths.iter().sum::<i64>() + (names.len() as i64 - 1).max(0) * 16;
        let mut x = ((600 - total) as f64 / 2.0).max(8.0);
        for (index, (name, width)) in names.iter().zip(&widths).enumerate() {
            items.push_str(&format!(
                "<rect x=\"{}\" y=\"{y}\" width=\"11\" height=\"11\" fill=\"{}\"/><text x=\"{}\" y=\"{}\" font-size=\"11\" fill=\"#595959\">{}</text>",
                f(x, 2),
                color(index),
                f(x + 16.0, 2),
                y + 10,
                escape(name)
            ));
            x += (*width + 16) as f64;
        }
    } else {
        let x: i64 = if position == "left" { 7 } else { 455 };
        // `start_y` is a float in v3 except for the corner position.
        let corner = position == "corner";
        let start_y = 150.0 - names.len().max(1) as f64 * 25.0 / 2.0;
        for (index, name) in names.iter().enumerate() {
            let (y_text, y_plus_10, y) = if corner {
                let y = 35 + index as i64 * 25;
                (y.to_string(), (y + 10).to_string(), y as f64)
            } else {
                let y = start_y + (index * 25) as f64;
                (repr(y), repr(y + 10.0), y)
            };
            let style = marker_styles.map(|m| m[index].as_str()).unwrap_or("SQUARE");
            let symbol = if style == "DIAMOND" {
                let xf = x as f64;
                format!(
                    "<polygon class=\"chart-legend-marker\" data-marker-style=\"diamond\" fill=\"{}\" points=\"{},{} {},{} {},{} {},{}\"/>",
                    color(index),
                    f(xf + 5.5, 2),
                    f(y, 2),
                    f(xf + 11.0, 2),
                    f(y + 5.5, 2),
                    f(xf + 5.5, 2),
                    f(y + 11.0, 2),
                    f(xf, 2),
                    f(y + 5.5, 2)
                )
            } else {
                format!(
                    "<rect class=\"chart-legend-marker\" x=\"{x}\" y=\"{y_text}\" width=\"11\" height=\"11\" fill=\"{}\"/>",
                    color(index)
                )
            };
            items.push_str(&format!(
                "{symbol}<text x=\"{}\" y=\"{y_plus_10}\" font-size=\"11\" fill=\"#595959\">{}</text>",
                x + 16,
                escape(name)
            ));
        }
    }
    format!("<g class=\"chart-legend chart-legend-{position}\" data-legend-position=\"{position}\">{items}</g>")
}

/// v3 `_chart_pie_svg`.
fn pie_svg(
    chart: &Chart<'_>,
    chart_type: &str,
    records: &[Record<'_>],
    categories: &[String],
) -> String {
    let values: Vec<f64> = records[0].values.iter().map(|v| v.abs()).collect();
    let total = py_sum(values.iter().copied());
    let total = if total == 0.0 { 1.0 } else { total };
    let data_labels = chart.data_labels();
    let has_legend = chart.has_legend();
    let legend_position = if has_legend {
        chart.legend_position()
    } else {
        "right"
    };
    let (center_x, center_y, radius): (i64, i64, i64) = match legend_position {
        "left" => (405, 154, 103),
        "top" => (300, 166, 92),
        "bottom" => (300, 132, 92),
        _ => (190, 154, 108),
    };
    let (cx, cy, r) = (center_x as f64, center_y as f64, radius as f64);
    let mut parts = String::new();
    let mut start_angle = -std::f64::consts::PI / 2.0;
    let colors: Vec<&str> = (0..values.len())
        .map(|i| FALLBACK_PALETTE[i % FALLBACK_PALETTE.len()])
        .collect();
    for (index, value) in values.iter().enumerate() {
        let end_angle = start_angle + 2.0 * std::f64::consts::PI * value / total;
        if isclose(*value, total, 0.0) {
            parts.push_str(&format!(
                "<circle class=\"chart-slice\" cx=\"{center_x}\" cy=\"{center_y}\" r=\"{radius}\" fill=\"{}\"/>",
                colors[index]
            ));
        } else {
            let start_x = cx + r * start_angle.cos();
            let start_y = cy + r * start_angle.sin();
            let end_x = cx + r * end_angle.cos();
            let end_y = cy + r * end_angle.sin();
            let large_arc = i32::from(end_angle - start_angle > std::f64::consts::PI);
            parts.push_str(&format!(
                "<path class=\"chart-slice\" d=\"M{center_x} {center_y} L{} {} A{radius} {radius} 0 {large_arc} 1 {} {} Z\" fill=\"{}\"/>",
                f(start_x, 2),
                f(start_y, 2),
                f(end_x, 2),
                f(end_y, 2),
                colors[index]
            ));
        }
        if data_labels && *value != 0.0 {
            let middle = (start_angle + end_angle) / 2.0;
            let label_x = cx + r * 0.68 * middle.cos();
            let label_y = cy + r * 0.68 * middle.sin();
            parts.push_str(&format!(
                "<text class=\"chart-data-label\" x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"12\" fill=\"#fff\">{}</text>",
                f(label_x, 2),
                f(label_y, 2),
                pct0(value / total)
            ));
        }
        start_angle = end_angle;
    }
    let doughnut = chart_type.contains("DOUGHNUT");
    if doughnut {
        parts.push_str(&format!(
            "<circle cx=\"{center_x}\" cy=\"{center_y}\" r=\"{}\" fill=\"#fff\"/>",
            f(r * 0.57, 2)
        ));
    }
    if has_legend {
        let mut legend_items = String::new();
        for (index, value) in values.iter().enumerate() {
            let label = categories.get(index).map(String::as_str).unwrap_or("");
            let suffix = if data_labels {
                format!(" ({})", pct0(value / total))
            } else {
                String::new()
            };
            let (item_x, item_y) = if matches!(legend_position, "top" | "bottom") {
                (
                    45.0 + index as f64 * (510.0 / values.len().max(1) as f64),
                    if legend_position == "top" { 5.0 } else { 283.0 },
                )
            } else {
                (
                    if legend_position == "left" {
                        8.0
                    } else {
                        355.0
                    },
                    (54 + index * 31) as f64,
                )
            };
            legend_items.push_str(&format!(
                "<rect x=\"{}\" y=\"{}\" width=\"12\" height=\"12\" fill=\"{}\"/><text x=\"{}\" y=\"{}\" font-size=\"12\" fill=\"#595959\">{}{suffix}</text>",
                f(item_x, 2),
                f(item_y, 2),
                colors[index],
                f(item_x + 21.0, 2),
                f(item_y + 11.0, 2),
                escape(label)
            ));
        }
        parts.push_str(&format!(
            "<g class=\"chart-legend chart-legend-{legend_position}\" data-legend-position=\"{legend_position}\">{legend_items}</g>"
        ));
    }
    let semantic = if doughnut { "doughnut" } else { "pie" };
    format!("<svg class=\"chart-svg chart-{semantic}\" viewBox=\"0 0 600 300\">{parts}</svg>")
}

/// v3 `_chart_category_labels`.
fn category_labels(categories: &[String], bar: bool, plot: &Plot) -> String {
    let mut out = String::new();
    if bar {
        let slot = (plot.bottom - plot.top) / categories.len().max(1) as f64;
        for (index, label) in categories.iter().enumerate() {
            out.push_str(&format!(
                "<text class=\"chart-category-label\" x=\"{}\" y=\"{}\" text-anchor=\"end\" font-size=\"12\" fill=\"#666\">{}</text>",
                f(plot.left - 11.0, 2),
                f(plot.top + (index as f64 + 0.5) * slot + 4.0, 2),
                escape(label)
            ));
        }
        return out;
    }
    let slot = (plot.right - plot.left) / categories.len().max(1) as f64;
    for (index, label) in categories.iter().enumerate() {
        out.push_str(&format!(
            "<text class=\"chart-category-label\" x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"12\" fill=\"#666\">{}</text>",
            f(plot.left + (index as f64 + 0.5) * slot, 2),
            f(plot.bottom + 24.0, 2),
            escape(label)
        ));
    }
    out
}

/// Per-category sums of absolute values (v3 `totals`).
fn totals(series: &[&[f64]], count: usize) -> Vec<f64> {
    (0..count)
        .map(|index| {
            py_sum(
                series
                    .iter()
                    .filter(|s| index < s.len())
                    .map(|s| s[index].abs()),
            )
        })
        .collect()
}

fn names_and_colors<'r>(records: &'r [Record<'_>]) -> (Vec<&'r str>, Vec<&'r str>) {
    (
        records.iter().map(|r| r.name.as_str()).collect(),
        records.iter().map(|r| r.color.as_str()).collect(),
    )
}

/// v3 `_chart_line_or_area_svg`.
fn line_or_area_svg(
    chart: &Chart<'_>,
    chart_type: &str,
    records: &[Record<'_>],
    categories: &[String],
) -> R<String> {
    let stacked = chart_type.contains("STACKED");
    let hundred = chart_type.contains("100");
    let count = records.iter().map(|r| r.values.len()).max().unwrap_or(0);
    let series: Vec<&[f64]> = records.iter().map(|r| r.values.as_slice()).collect();
    let totals = totals(&series, count);
    let mut cumulative = vec![0.0; count];
    let mut display: Vec<Vec<f64>> = Vec::new();
    for record in records {
        let mut current = Vec::with_capacity(count);
        for index in 0..count {
            let mut value = record.values.get(index).copied().unwrap_or(0.0);
            if hundred {
                value /= if totals[index] == 0.0 {
                    1.0
                } else {
                    totals[index]
                };
            }
            if stacked {
                cumulative[index] += value;
                value = cumulative[index];
            }
            current.push(value);
        }
        display.push(current);
    }
    let flat: Vec<f64> = display.iter().flatten().copied().collect();
    let value_axis = chart.value_axis();
    let (lower, upper) = scale(&flat, value_axis)?;
    let (left, right) = horizontal_bounds(chart);
    let plot = Plot {
        left,
        right,
        top: 28.0,
        bottom: 248.0,
    };
    let map_y =
        |value: f64| plot.bottom - (value - lower) / (upper - lower) * (plot.bottom - plot.top);
    let baseline = map_y(0.0);
    let mut parts = axes_svg(
        lower,
        upper,
        baseline,
        chart.major_gridlines(),
        value_axis,
        &plot,
    );
    let data_labels = chart.data_labels();
    let show_markers = chart_type.contains("MARKERS") && !chart_type.contains("NO_MARKERS");
    let area = chart_type.contains("AREA");
    for (series_index, record) in records.iter().enumerate() {
        let values = &display[series_index];
        let points: Vec<(f64, f64)> = values
            .iter()
            .enumerate()
            .map(|(index, value)| {
                let step = (plot.right - plot.left) / (values.len() as i64 - 1).max(1) as f64;
                (plot.left + index as f64 * step, map_y(*value))
            })
            .collect();
        let point_text = points
            .iter()
            .map(|(x, y)| format!("{},{}", f(*x, 2), f(*y, 2)))
            .collect::<Vec<_>>()
            .join(" ");
        let color = &record.color;
        if area && !points.is_empty() {
            let previous: Vec<f64> = if stacked && series_index > 0 {
                display[series_index - 1].clone()
            } else {
                vec![0.0; points.len()]
            };
            let mut polygon: Vec<String> = points
                .iter()
                .map(|(x, y)| format!("{},{}", f(*x, 2), f(*y, 2)))
                .collect();
            for index in (0..points.len()).rev() {
                polygon.push(format!(
                    "{},{}",
                    f(points[index].0, 2),
                    f(map_y(previous[index]), 2)
                ));
            }
            parts.push_str(&format!(
                "<polygon class=\"chart-area\" points=\"{}\" fill=\"{color}\" fill-opacity=\".24\"/>",
                polygon.join(" ")
            ));
        }
        parts.push_str(&format!(
            "<polyline class=\"chart-series-line\" points=\"{point_text}\" fill=\"none\" stroke=\"{color}\" stroke-width=\"3\"/>"
        ));
        if show_markers {
            for (x, y) in &points {
                parts.push_str(&format!(
                    "<circle class=\"chart-marker\" cx=\"{}\" cy=\"{}\" r=\"4\" fill=\"{color}\"/>",
                    f(*x, 2),
                    f(*y, 2)
                ));
            }
        }
        if data_labels {
            for (index, (x, y)) in points.iter().enumerate() {
                parts.push_str(&format!(
                    "<text class=\"chart-data-label\" x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#404040\">{}</text>",
                    f(*x, 2),
                    f(y - 7.0, 2),
                    g(values[index])
                ));
            }
        }
    }
    parts.push_str(&category_labels(categories, false, &plot));
    if chart.has_legend() {
        let (names, colors) = names_and_colors(records);
        parts.push_str(&legend_svg(chart, &names, &colors, None));
    }
    let semantic = if area { "area" } else { "line" };
    let stacked_class = if stacked { " chart-stacked" } else { "" };
    Ok(format!(
        "<svg class=\"chart-svg chart-{semantic}{stacked_class}\" viewBox=\"0 0 600 300\" preserveAspectRatio=\"none\">{parts}</svg>"
    ))
}

/// v3 `_chart_scatter_svg`.
fn scatter_svg(
    chart: &Chart<'_>,
    chart_type: &str,
    records: &[Record<'_>],
    chart_aspect: f64,
) -> R<String> {
    let mut series_points: Vec<Vec<(f64, f64)>> = Vec::new();
    for record in records {
        let mut x_values = cache_values(record.ser, "xVal");
        if x_values.is_empty() {
            x_values = (0..record.values.len()).map(|i| (i + 1) as f64).collect();
        }
        series_points.push(
            x_values
                .into_iter()
                .zip(record.values.iter().copied())
                .collect(),
        );
    }
    let mut all_x: Vec<f64> = series_points.iter().flatten().map(|p| p.0).collect();
    let mut all_y: Vec<f64> = series_points.iter().flatten().map(|p| p.1).collect();
    if all_x.is_empty() {
        all_x = vec![0.0, 1.0];
    }
    if all_y.is_empty() {
        all_y = vec![0.0, 1.0];
    }
    let x_axis = chart.category_axis();
    let y_axis = chart.value_axis();
    let (x_lower, x_upper) = scale(&all_x, x_axis)?;
    let (y_lower, y_upper) = scale(&all_y, y_axis)?;
    let (left, right) = horizontal_bounds(chart);
    let plot = Plot {
        left,
        right,
        top: 28.0,
        bottom: 248.0,
    };
    let map_x =
        |value: f64| plot.left + (value - x_lower) / (x_upper - x_lower) * (plot.right - plot.left);
    let map_y = |value: f64| {
        plot.bottom - (value - y_lower) / (y_upper - y_lower) * (plot.bottom - plot.top)
    };
    let baseline = map_y(0.0);
    let mut parts = axes_svg(
        y_lower,
        y_upper,
        baseline,
        axis_gridlines(y_axis),
        y_axis,
        &plot,
    );
    for tick in tick_values(x_lower, x_upper, x_axis) {
        let x = map_x(tick);
        if axis_gridlines(x_axis) {
            parts.push_str(&format!(
                "<line class=\"chart-gridline chart-gridline-x\" x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#d9d9d9\" stroke-width=\"1\"/>",
                f(x, 2),
                f(plot.top, 2),
                f(x, 2),
                f(plot.bottom, 2)
            ));
        }
        parts.push_str(&format!(
            "<line class=\"chart-axis-tick chart-axis-tick-x\" x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#7f7f7f\"/><text class=\"chart-axis-label chart-axis-label-x\" x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#666\">{}</text>",
            f(x, 2),
            f(plot.bottom, 2),
            f(x, 2),
            f(plot.bottom + 4.0, 2),
            f(x, 2),
            f(plot.bottom + 20.0, 2),
            g(tick)
        ));
    }
    let has_lines = chart_type.contains("LINES") || chart_type.contains("SMOOTH");
    let has_markers = !chart_type.contains("NO_MARKERS");
    let data_labels = chart.data_labels();
    let x_compensation = (2.0 / chart_aspect.max(0.1)).clamp(0.5, 4.0);
    for (series_index, points) in series_points.iter().enumerate() {
        let record = &records[series_index];
        let color = &record.color;
        let mapped: Vec<(f64, f64, f64)> = points
            .iter()
            .map(|(x, y)| (map_x(*x), map_y(*y), *y))
            .collect();
        if has_lines {
            let coordinates = mapped
                .iter()
                .map(|(x, y, _)| format!("{},{}", f(*x, 2), f(*y, 2)))
                .collect::<Vec<_>>()
                .join(" ");
            parts.push_str(&format!(
                "<polyline class=\"chart-series-line\" points=\"{coordinates}\" fill=\"none\" stroke=\"{color}\" stroke-width=\"3\"/>"
            ));
        }
        if has_markers {
            for (x, y, _) in &mapped {
                parts.push_str(&marker_svg(
                    record.ser,
                    *x,
                    *y,
                    color,
                    x_compensation,
                    "DIAMOND",
                ));
            }
        }
        if data_labels {
            for (x, y, raw_y) in &mapped {
                let label_y = (plot.top + 10.0).max((y - 7.0).min(plot.bottom - 4.0));
                parts.push_str(&format!(
                    "<text class=\"chart-data-label\" x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#404040\">{}</text>",
                    f(*x, 2),
                    f(label_y, 2),
                    g(*raw_y)
                ));
            }
        }
    }
    if chart.has_legend() {
        let (names, colors) = names_and_colors(records);
        let styles: Vec<String> = records
            .iter()
            .map(|r| marker_style(r.ser, "DIAMOND"))
            .collect();
        parts.push_str(&legend_svg(chart, &names, &colors, Some(&styles)));
    }
    Ok(format!("<svg class=\"chart-svg chart-scatter\" viewBox=\"0 0 600 300\" preserveAspectRatio=\"none\">{parts}</svg>"))
}

/// v3 `_chart_bar_or_column_svg`.
fn bar_or_column_svg(
    chart: &Chart<'_>,
    chart_type: &str,
    records: &[Record<'_>],
    categories: &[String],
) -> R<String> {
    let horizontal = chart_type.starts_with("BAR_");
    let stacked = chart_type.contains("STACKED");
    let hundred = chart_type.contains("100");
    let category_count = records.iter().map(|r| r.values.len()).max().unwrap_or(0);
    let series: Vec<&[f64]> = records.iter().map(|r| r.values.as_slice()).collect();
    let totals = totals(&series, category_count);
    let normalise = |raw: f64, index: usize| {
        if hundred {
            raw / if totals[index] == 0.0 {
                1.0
            } else {
                totals[index]
            }
        } else {
            raw
        }
    };
    let scale_values: Vec<f64> = if stacked {
        let mut positive = vec![0.0; category_count];
        let mut negative = vec![0.0; category_count];
        for values in &series {
            for (index, raw) in values.iter().enumerate() {
                let value = normalise(*raw, index);
                if value >= 0.0 {
                    positive[index] += value;
                } else {
                    negative[index] += value;
                }
            }
        }
        positive.into_iter().chain(negative).collect()
    } else {
        series.iter().flat_map(|s| s.iter().copied()).collect()
    };
    let value_axis = chart.value_axis();
    let (lower, upper) = scale(&scale_values, value_axis)?;
    let data_labels = chart.data_labels();
    let mut parts = String::new();
    let (top, bottom) = (28.0, 248.0);
    let mut positive = vec![0.0; category_count];
    let mut negative = vec![0.0; category_count];
    let mut stack = |value: f64, index: usize| {
        let start = if value >= 0.0 {
            positive[index]
        } else {
            negative[index]
        };
        let end = start + value;
        if value >= 0.0 {
            positive[index] = end;
        } else {
            negative[index] = end;
        }
        (start, end)
    };
    if horizontal {
        let right = if chart.has_legend() && matches!(chart.legend_position(), "right" | "corner") {
            430.0
        } else {
            564.0
        };
        let plot = Plot {
            left: 150.0,
            right,
            top,
            bottom,
        };
        let map_x =
            |value: f64| plot.left + (value - lower) / (upper - lower) * (plot.right - plot.left);
        let baseline = map_x(0.0);
        for tick in tick_values(lower, upper, value_axis) {
            let x = map_x(tick);
            if chart.major_gridlines() {
                parts.push_str(&format!(
                    "<line class=\"chart-gridline\" x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#d9d9d9\"/>",
                    f(x, 2),
                    f(plot.top, 2),
                    f(x, 2),
                    f(plot.bottom, 2)
                ));
            }
            parts.push_str(&format!(
                "<text class=\"chart-axis-label chart-axis-label-x\" x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#666\">{}</text>",
                f(x, 2),
                f(plot.bottom + 20.0, 2),
                g(tick)
            ));
        }
        parts.push_str(&format!(
            "<line class=\"chart-axis chart-axis-y\" x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#7f7f7f\"/>",
            f(baseline, 2),
            f(plot.top, 2),
            f(baseline, 2),
            f(plot.bottom, 2)
        ));
        let slot = (plot.bottom - plot.top) / category_count.max(1) as f64;
        let clustered = slot * 0.72 / records.len().max(1) as f64;
        let stacked_height = slot * 0.72;
        for (series_index, record) in records.iter().enumerate() {
            for category in 0..category_count {
                let raw = record.values.get(category).copied().unwrap_or(0.0);
                let value = normalise(raw, category);
                let (start, end, height, y) = if stacked {
                    let (start, end) = stack(value, category);
                    (
                        start,
                        end,
                        stacked_height,
                        plot.top + category as f64 * slot + slot * 0.14,
                    )
                } else {
                    (
                        0.0,
                        value,
                        clustered,
                        plot.top
                            + category as f64 * slot
                            + slot * 0.14
                            + series_index as f64 * clustered,
                    )
                };
                let (x1, x2) = (map_x(start), map_x(end));
                let visible_x1 = x1.max(plot.left).min(plot.right);
                let visible_x2 = x2.max(plot.left).min(plot.right);
                parts.push_str(&format!(
                    "<rect class=\"chart-bar\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" fill=\"{}\"/>",
                    f(visible_x1.min(visible_x2), 2),
                    f(y, 2),
                    f((visible_x2 - visible_x1).abs(), 2),
                    f(height, 2),
                    record.color
                ));
                if data_labels {
                    let (label_x, anchor) = if stacked {
                        ((visible_x1 + visible_x2) / 2.0, "middle")
                    } else {
                        (
                            (x2 + if value >= 0.0 { 4.0 } else { -4.0 })
                                .max(plot.left + 4.0)
                                .min(plot.right - 4.0),
                            if value >= 0.0 { "start" } else { "end" },
                        )
                    };
                    parts.push_str(&format!(
                        "<text class=\"chart-data-label\" x=\"{}\" y=\"{}\" text-anchor=\"{anchor}\" font-size=\"11\" fill=\"#404040\">{}</text>",
                        f(label_x, 2),
                        f(y + height / 2.0 + 4.0, 2),
                        g(raw)
                    ));
                }
            }
        }
        parts.push_str(&category_labels(categories, true, &plot));
    } else {
        let (left, right) = horizontal_bounds(chart);
        let plot = Plot {
            left,
            right,
            top,
            bottom,
        };
        let map_y =
            |value: f64| plot.bottom - (value - lower) / (upper - lower) * (plot.bottom - plot.top);
        let baseline = map_y(0.0);
        parts.push_str(&axes_svg(
            lower,
            upper,
            baseline,
            chart.major_gridlines(),
            value_axis,
            &plot,
        ));
        let slot = (plot.right - plot.left) / category_count.max(1) as f64;
        let clustered = slot * 0.72 / records.len().max(1) as f64;
        let stacked_width = slot * 0.72;
        for (series_index, record) in records.iter().enumerate() {
            for category in 0..category_count {
                let raw = record.values.get(category).copied().unwrap_or(0.0);
                let value = normalise(raw, category);
                let (start, end, width, x) = if stacked {
                    let (start, end) = stack(value, category);
                    (
                        start,
                        end,
                        stacked_width,
                        plot.left + category as f64 * slot + slot * 0.14,
                    )
                } else {
                    (
                        0.0,
                        value,
                        clustered,
                        plot.left
                            + category as f64 * slot
                            + slot * 0.14
                            + series_index as f64 * clustered,
                    )
                };
                let (y1, y2) = (map_y(start), map_y(end));
                let visible_y1 = y1.max(plot.top).min(plot.bottom);
                let visible_y2 = y2.max(plot.top).min(plot.bottom);
                parts.push_str(&format!(
                    "<rect class=\"chart-column\" x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" fill=\"{}\"/>",
                    f(x, 2),
                    f(visible_y1.min(visible_y2), 2),
                    f(width, 2),
                    f((visible_y2 - visible_y1).abs(), 2),
                    record.color
                ));
                if data_labels {
                    let label_y = if stacked {
                        (visible_y1 + visible_y2) / 2.0 + 4.0
                    } else {
                        (y2 + if value >= 0.0 { -4.0 } else { 12.0 })
                            .max(plot.top + 10.0)
                            .min(plot.bottom - 4.0)
                    };
                    parts.push_str(&format!(
                        "<text class=\"chart-data-label\" x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#404040\">{}</text>",
                        f(x + width / 2.0, 2),
                        f(label_y, 2),
                        g(raw)
                    ));
                }
            }
        }
        parts.push_str(&category_labels(categories, false, &plot));
    }
    if chart.has_legend() {
        let (names, colors) = names_and_colors(records);
        parts.push_str(&legend_svg(chart, &names, &colors, None));
    }
    let semantic = if horizontal { "bar" } else { "column" };
    let grouping = if stacked { "stacked" } else { "clustered" };
    Ok(format!(
        "<svg class=\"chart-svg chart-{semantic} chart-{grouping}\" data-chart-grouping=\"{grouping}\" viewBox=\"0 0 600 300\" preserveAspectRatio=\"none\">{parts}</svg>"
    ))
}

/// The chart title text (`chart.chart_title.text_frame.text`), when the
/// chart has a title.
pub(super) fn chart_title(space: Nd<'_>) -> String {
    let Some(chart) = c_child(space, "chart") else {
        return String::new();
    };
    let Some(title) = c_child(chart, "title") else {
        return String::new();
    };
    let rich = c_child(title, "tx").and_then(|tx| c_child(tx, "rich"));
    let text = super::text::text_frame_text(rich);
    super::util::py_strip(&text).to_string()
}

/// The note v3 drew for a chart type it does not draw.
fn unsupported(chart_type: &str) -> String {
    let semantic = chart_type.to_lowercase().replace('_', "-");
    format!(
        "<div class=\"chart-unsupported\" data-chart-type=\"{}\">Unsupported chart type: {}</div>",
        escape(&semantic),
        escape(chart_type)
    )
}

/// v3 `_chart_svg` for the chart part rooted at `space` (`c:chartSpace`).
pub(super) fn chart_svg(space: Nd<'_>, palette: &Palette, chart_aspect: f64) -> R<String> {
    // Fix over v3 (failed the deck): a chart part without a plot area shows
    // the unsupported-chart note.
    let Some(chart_node) = c_child(space, "chart") else {
        return Ok(unsupported("UNKNOWN"));
    };
    let Some(plot_area) = c_child(chart_node, "plotArea") else {
        return Ok(unsupported("UNKNOWN"));
    };
    let chart = Chart {
        chart: chart_node,
        plot_area,
    };
    let chart_type = chart_type_name(&chart)?;
    let supported = [
        "COLUMN_",
        "BAR_",
        "LINE",
        "AREA",
        "PIE",
        "DOUGHNUT",
        "XY_SCATTER",
    ]
    .iter()
    .any(|p| chart_type.starts_with(p));
    if chart_type == "UNKNOWN" || chart_type.contains("_3D") || !supported {
        return Ok(unsupported(&chart_type));
    }
    let records = series_records(&chart, palette)?;
    if records.is_empty() {
        return Ok("<div class=\"chart-empty\">Chart data unavailable</div>".into());
    }
    let categories = categories(&chart)?;
    if chart_type.starts_with("PIE") || chart_type.starts_with("DOUGHNUT") {
        return Ok(pie_svg(&chart, &chart_type, &records, &categories));
    }
    if chart_type.starts_with("XY_SCATTER") {
        return scatter_svg(&chart, &chart_type, &records, chart_aspect);
    }
    if chart_type.starts_with("LINE") || chart_type.starts_with("AREA") {
        return line_or_area_svg(&chart, &chart_type, &records, &categories);
    }
    bar_or_column_svg(&chart, &chart_type, &records, &categories)
}
