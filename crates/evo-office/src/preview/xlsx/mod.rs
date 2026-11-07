//! XLSX → HTML: a port of v3 `service.py` `_render_xlsx` and its helpers,
//! `xlsx_features.py` and `xlsx_formula.py`.
//!
//! v3 read workbooks with openpyxl; [`book`] reproduces the parts of its object
//! model the output depends on (values, styles, dimensions, merges, links,
//! comments, conditional formatting, charts, images), [`formula`] evaluates the
//! whitelisted formula subset, [`features`] adds conditional formatting and
//! drawing shapes, and this module lays the grid out exactly as v3 did:
//! a `<section data-preview-item>` per visible sheet with a sticky header row
//! and column, `td[data-cell]` carrying `data-display-value` and
//! `data-formula`, at least 40 rows × 20 columns and at most 500 × 100.
//!
//! Design: `docs/features/office-v3-parity/sdd.md`.

mod book;
mod chart;
mod css;
mod features;
mod formula;
mod numfmt;
mod value;

use std::collections::{HashMap, HashSet};

use self::book::{Anchor, Color, Formula, SheetRef, Side, Workbook, Worksheet};
use self::formula::{column_letter, parse_cell, Evaluation};
use self::numfmt::format_computed_value;
use self::value::{py_strip, Num, PySum, Value};
use super::html::{css_color, css_font_family, escape, page};
use super::{DeckPlan, Package, PreviewError, MIN_XLSX_COLUMNS, MIN_XLSX_ROWS};

/// Rows and columns a sheet shows at most.
const MAX_ROWS: u32 = 500;
const MAX_COLUMNS: u32 = 100;

/// `bytes` is the workbook file: a workbook that fails to parse is retried once
/// from a sanitized copy (v3 `sanitized_workbook_bytes`).
pub fn render(bytes: &[u8], title: &str, live: Option<&DeckPlan>) -> Result<String, PreviewError> {
    let package = Package::open(bytes)?;
    let workbook = load_preview_workbook(&package)?;
    Ok(render_workbook(&package, &workbook, title, live))
}

/// Workbook sheet names in tab order, skipping hidden and very hidden sheets.
pub fn visible_sheet_names(bytes: &[u8]) -> Vec<String> {
    match Package::open(bytes) {
        Ok(package) => features::visible_sheet_names(&package),
        Err(_) => Vec::new(),
    }
}

/// v3 `_load_preview_workbooks`: load, else retry once from the sanitized copy.
fn load_preview_workbook(package: &Package) -> Result<Workbook, PreviewError> {
    match book::load(package) {
        Ok(workbook) => Ok(workbook),
        Err(first) => {
            let repaired = features::sanitized_package(package);
            book::load(&repaired).map_err(|_| {
                PreviewError::failed(format!("Could not render this document: {}", first.0))
            })
        }
    }
}

// ---------------------------------------------------------------- geometry

/// v3 `_xlsx_column_width_px`.
fn column_width_px(sheet: &Worksheet, column: u32) -> Num {
    let dimension = sheet.column(column);
    if dimension.hidden {
        return Num::Int(1);
    }
    Num::Int(1).max(Num::Float(dimension.width * 7.0).min(Num::Int(280)))
}

/// v3 `_xlsx_row_height_px` (the default height is the sheet's own).
fn row_height_px(sheet: &Worksheet, row: u32) -> Num {
    let dimension = sheet.row(row);
    if dimension.hidden {
        return Num::Int(1);
    }
    let height = dimension
        .height
        .filter(|h| *h != 0.0)
        .unwrap_or(sheet.default_height);
    Num::Float(height * 96.0 / 72.0)
}

/// Rendered pitch of a column / row (hidden ones collapse; rows are at least
/// 25px plus a 1px border).
fn column_pitch_px(sheet: &Worksheet, column: u32) -> f64 {
    if sheet.column(column).hidden {
        0.0
    } else {
        column_width_px(sheet, column).f()
    }
}

fn row_pitch_px(sheet: &Worksheet, row: u32) -> f64 {
    if sheet.row(row).hidden {
        0.0
    } else {
        row_height_px(sheet, row)
            .max(Num::Int(25))
            .add(Num::Int(1))
            .f()
    }
}

const EMU_PER_PX: f64 = 914_400.0 / 96.0;
/// openpyxl's default chart size, 15 × 7.5 cm, in px at 96 dpi.
const DEFAULT_CHART_SIZE: (f64, f64) = (15.0 / 2.54 * 96.0, 7.5 / 2.54 * 96.0);
/// Cells an anchor walk may cover before it stops (beyond the 500 × 100 grid).
const WALK_LIMIT: u32 = 1_000;

/// The 1-based (row, column) a span of `px` starting `offset_px` into cell
/// `first` (1-based) ends in, walking the rendered pitches.
fn walk(first: u32, offset_px: f64, px: f64, pitch: &dyn Fn(u32) -> f64) -> u32 {
    let mut cell = first.max(1);
    let mut remaining = offset_px + px;
    while cell < first + WALK_LIMIT {
        let size = pitch(cell);
        if remaining <= size {
            break;
        }
        remaining -= size;
        cell += 1;
    }
    cell
}

/// The last cell (1-based row, column) a drawing anchor covers, so the grid
/// is laid out under the whole object.
fn anchor_end(sheet: &Worksheet, anchor: &Anchor, default_size: (f64, f64)) -> (u32, u32) {
    let cell = |zero: i64| (zero.max(0) as u32).saturating_add(1);
    if let Some(to) = anchor.to.filter(|_| anchor.kind == "twoCellAnchor") {
        let column = cell(to.col) - u32::from(to.col_off == 0.0 && to.col > anchor.from.col);
        let row = cell(to.row) - u32::from(to.row_off == 0.0 && to.row > anchor.from.row);
        return (row, column);
    }
    let (w, h) = anchor
        .ext
        .map(|(cx, cy)| (cx / EMU_PER_PX, cy / EMU_PER_PX))
        .unwrap_or(default_size);
    let (first_col, first_row, x, y) = if anchor.kind == "absoluteAnchor" {
        let (x, y) = anchor.pos.unwrap_or((0.0, 0.0));
        (1, 1, x / EMU_PER_PX, y / EMU_PER_PX)
    } else {
        (
            cell(anchor.from.col),
            cell(anchor.from.row),
            anchor.from.col_off / EMU_PER_PX,
            anchor.from.row_off / EMU_PER_PX,
        )
    };
    (
        walk(first_row, y, h, &|r| row_pitch_px(sheet, r)),
        walk(first_col, x, w, &|c| column_pitch_px(sheet, c)),
    )
}

/// Box of a chart or picture on the rendered grid (the same geometry as
/// drawing shapes). v3 placed charts and pictures from raw column widths and
/// row heights, so they drifted from the cells they are anchored to, and sized
/// two-cell anchored ones from the object's own default size.
fn object_box(
    anchor: &Anchor,
    default_size: (f64, f64),
    column_left: &dyn Fn(i64) -> f64,
    row_top: &dyn Fn(i64) -> f64,
) -> (f64, f64, f64, f64) {
    let (w, h) = anchor
        .ext
        .map(|(cx, cy)| (cx / EMU_PER_PX, cy / EMU_PER_PX))
        .unwrap_or(default_size);
    if anchor.kind == "absoluteAnchor" {
        let (x, y) = anchor.pos.unwrap_or((0.0, 0.0));
        return (
            44.0 + x / EMU_PER_PX,
            25.0 + y / EMU_PER_PX,
            w.max(1.0),
            h.max(1.0),
        );
    }
    let left = column_left(anchor.from.col) + anchor.from.col_off / EMU_PER_PX;
    let top = row_top(anchor.from.row) + anchor.from.row_off / EMU_PER_PX;
    if let Some(to) = anchor.to.filter(|_| anchor.kind == "twoCellAnchor") {
        let right = column_left(to.col) + to.col_off / EMU_PER_PX;
        let bottom = row_top(to.row) + to.row_off / EMU_PER_PX;
        if right > left && bottom > top {
            return (left, top, right - left, bottom - top);
        }
    }
    (left, top, w.max(1.0), h.max(1.0))
}

/// A cell colour as CSS: explicit RGB as v3 wrote it, theme and indexed
/// colours resolved like conditional formatting (v3 dropped them).
fn cell_color(color: &Color, default: &str) -> String {
    match color.rgb() {
        Some(rgb) => css_color(Some(rgb), default),
        None => features::color_css(Some(color)).unwrap_or_else(|| default.to_string()),
    }
}

/// v3 `_xlsx_frozen_edges`: frozen (columns, rows).
fn frozen_edges(sheet: &Worksheet) -> (u32, u32) {
    let Some(pane) = sheet.pane.as_deref().filter(|p| !p.is_empty()) else {
        return (0, 0);
    };
    match parse_cell(pane) {
        Some((column, row)) if !pane.contains(':') => (column - 1, row - 1),
        _ => (0, 0),
    }
}

/// Python slice `items[:end]` length for a possibly negative `end`.
fn slice_len(len: usize, end: i64) -> usize {
    if end < 0 {
        (len as i64 + end).max(0) as usize
    } else {
        (end as usize).min(len)
    }
}

/// v3 `_border_css`.
fn border_css(side: &Side, name: &str) -> Option<String> {
    let style = side.style.as_deref().filter(|s| !s.is_empty())?;
    let color = side
        .color
        .as_ref()
        .map_or_else(|| "#80868b".to_string(), |c| cell_color(c, "#80868b"));
    let width = if matches!(style, "medium" | "thick" | "double") {
        "2px"
    } else {
        "1px"
    };
    let line = if style.contains("dash") {
        "dashed"
    } else {
        "solid"
    };
    Some(format!("border-{name}:{width} {line} {color}"))
}

// ---------------------------------------------------------------- rendering

fn render_workbook(
    package: &Package,
    workbook: &Workbook,
    title: &str,
    live: Option<&DeckPlan>,
) -> String {
    let _palette = features::use_palette(workbook.styles.palette.clone());
    let mut evaluation = Evaluation::new(workbook).evaluate_all();
    let drawing_parts = features::worksheet_drawing_parts(package);
    let mut sections: Vec<String> = Vec::new();
    // Sheets in tab order (v3 put every chart sheet after the worksheets).
    for sheet_ref in &workbook.order {
        let chartsheet = match *sheet_ref {
            SheetRef::Worksheet(index) => {
                let sheet = &workbook.worksheets[index];
                if sheet.state != "veryHidden" {
                    sections.push(render_sheet(
                        package,
                        workbook,
                        sheet,
                        &mut evaluation,
                        &drawing_parts,
                    ));
                }
                continue;
            }
            SheetRef::Chartsheet(index) => &workbook.chartsheets[index],
        };
        if chartsheet.state == "veryHidden" {
            continue;
        }
        let figures: String = chartsheet
            .charts
            .iter()
            .map(|c| {
                format!(
                    "<figure class=\"chartsheet-chart\">{}</figure>",
                    chart::chart_svg(workbook, c, &mut evaluation)
                )
            })
            .collect();
        let figures = if figures.is_empty() {
            "<p class=\"chart-empty\">This chart sheet has no readable chart.</p>".to_string()
        } else {
            figures
        };
        sections.push(format!(
            "<section class=\"sheet chartsheet\" data-preview-item data-preview-label=\"{}\" data-preview-fit-width=\"960\" data-preview-fit-height=\"600\">{figures}</section>",
            escape(&sheet_label(&chartsheet.title, &chartsheet.state))
        ));
    }

    let plan = live.filter(|plan| !plan.done);
    let mut css = css::SHEET_CSS.to_string();
    let body = match plan {
        Some(plan) => {
            // Until the first sheet is added the workbook holds a stand-in sheet.
            let finished = (plan.added.unwrap_or(0) as usize).min(sections.len());
            let mut marked: Vec<String> = sections
                .into_iter()
                .take(finished)
                .enumerate()
                .map(|(index, section)| {
                    let fresh = if index + 1 == finished {
                        " data-slide-fresh"
                    } else {
                        ""
                    };
                    section.replacen(
                        " data-preview-item ",
                        &format!(" data-preview-item data-slide-status=\"done\"{fresh} "),
                        1,
                    )
                })
                .collect();
            marked.extend(pending_sheet_skeletons(plan, finished));
            css.push_str(css::LIVE_SHEET_CSS);
            format!("<main data-deck-live=\"true\">{}</main>", marked.concat())
        }
        None => sections.concat(),
    };
    page(title, &body, &css)
}

fn render_sheet(
    package: &Package,
    workbook: &Workbook,
    sheet: &Worksheet,
    evaluation: &mut Evaluation<Workbook>,
    drawing_parts: &HashMap<String, String>,
) -> String {
    let styles = &workbook.styles;
    // Bounds: content (values, formulas, formats, notes, merges) and drawings.
    // v3 also counted every cell a formula or a conditional format had read.
    let shape_anchors = drawing_parts
        .get(&sheet.title)
        .map(|part| features::drawing_anchors(package, part))
        .unwrap_or_default();
    let (mut data_rows, mut data_columns) = (sheet.max_row(), sheet.max_column());
    let anchors = sheet
        .charts
        .iter()
        .map(|c| (&c.anchor, DEFAULT_CHART_SIZE))
        .chain(
            sheet
                .images
                .iter()
                .map(|i| (&i.anchor, (i.width, i.height))),
        )
        .chain(shape_anchors.iter().map(|a| (a, (0.0, 0.0))));
    for (anchor, size) in anchors {
        let (row, column) = anchor_end(sheet, anchor, size);
        data_rows = data_rows.max(row);
        data_columns = data_columns.max(column);
    }
    let used_max_row = data_rows.clamp(1, MAX_ROWS);
    let used_max_column = data_columns.clamp(1, MAX_COLUMNS);
    let max_row = data_rows.clamp(MIN_XLSX_ROWS, MAX_ROWS);
    let max_column = data_columns.clamp(MIN_XLSX_COLUMNS, MAX_COLUMNS);

    let mut merged_starts = HashMap::new();
    let mut merged_covered = HashSet::new();
    for range in &sheet.merges {
        merged_starts.insert((range.min_row, range.min_col), *range);
    }
    for range in &sheet.merges {
        for row in range.min_row..=range.max_row {
            for column in range.min_col..=range.max_col {
                if (row, column) != (range.min_row, range.min_col) {
                    merged_covered.insert((row, column));
                }
            }
        }
    }

    let column_widths: Vec<Num> = (1..=max_column)
        .map(|c| column_width_px(sheet, c))
        .collect();
    let row_heights: Vec<Num> = (1..=max_row).map(|r| row_height_px(sheet, r)).collect();
    let hidden_columns: HashSet<u32> = (1..=max_column)
        .filter(|c| sheet.column(*c).hidden)
        .collect();
    let hidden_rows: HashSet<u32> = (1..=max_row).filter(|r| sheet.row(*r).hidden).collect();
    // Rendered row pitch: CSS enforces a 25px minimum plus a 1px border, while
    // hidden rows collapse entirely.
    let row_pitch: Vec<Num> = (1..=max_row)
        .map(|r| {
            if hidden_rows.contains(&r) {
                Num::Float(0.0)
            } else {
                row_heights[r as usize - 1]
                    .max(Num::Int(25))
                    .add(Num::Int(1))
            }
        })
        .collect();
    let column_pitch: Vec<Num> = (1..=max_column)
        .map(|c| {
            if hidden_columns.contains(&c) {
                Num::Float(0.0)
            } else {
                column_widths[c as usize - 1]
            }
        })
        .collect();
    let row_prefix = PySum::prefixes(&row_pitch);
    let column_prefix = PySum::prefixes(&column_pitch);
    let (frozen_columns, frozen_rows) = frozen_edges(sheet);

    let conditional =
        features::conditional_formats(sheet, &mut |row, column| match sheet.cell(row, column) {
            Some(cell) if cell.formula.is_some() => {
                let coordinate = format!("{}{row}", column_letter(column));
                evaluation.display_value(&sheet.title, &coordinate, cell.cached.clone())
            }
            Some(cell) => cell.value.clone(),
            None => Value::None,
        });

    let mut columns = String::from("<col style=\"width:44px\">");
    let mut headers = String::from("<th class=\"corner\" aria-hidden=\"true\"></th>");
    for column in 1..=max_column {
        let width = column_widths[column as usize - 1].f();
        let collapse = if hidden_columns.contains(&column) {
            ";visibility:collapse"
        } else {
            ""
        };
        let letter = column_letter(column);
        columns.push_str(&format!("<col style=\"width:{width:.0}px{collapse}\">"));
        headers.push_str(&format!(
            "<th class=\"column-header\" data-column=\"{letter}\" style=\"min-width:{width:.0}px\">{letter}</th>"
        ));
    }

    let mut rows = format!("<tr>{headers}</tr>");
    for row_index in 1..=max_row {
        let row_height = row_heights[row_index as usize - 1].f();
        let header_style = if row_index <= frozen_rows {
            let offset = Num::Int(26).add(row_prefix[row_index as usize - 1]).f();
            format!(" style=\"top:{offset:.2}px;z-index:4\"")
        } else {
            String::new()
        };
        let mut cells = format!(
            "<th class=\"row-number\" data-row=\"{row_index}\"{header_style}>{row_index}</th>"
        );
        for column_index in 1..=max_column {
            if merged_covered.contains(&(row_index, column_index)) {
                continue;
            }
            let coordinate = format!("{}{row_index}", column_letter(column_index));
            let data = sheet.cell(row_index, column_index);
            let xf = styles.xf(sheet.style_at(row_index, column_index));
            let spans = merged_starts
                .get(&(row_index, column_index))
                .map(|m| {
                    format!(
                        " rowspan=\"{}\" colspan=\"{}\"",
                        m.max_row - m.min_row + 1,
                        m.max_col - m.min_col + 1
                    )
                })
                .unwrap_or_default();
            let mut style: Vec<String> = Vec::new();
            let fill = styles.fill(xf);
            if !fill.gradient {
                let color = cell_color(&fill.fg, "transparent");
                if color != "transparent" && fill.pattern.is_some() {
                    style.push(format!("background:{color}"));
                }
            }
            let font = styles.font(xf);
            if font.bold {
                style.push("font-weight:700".into());
            }
            if font.italic {
                style.push("font-style:italic".into());
            }
            if let Some(name) = font.name.as_deref().filter(|n| !n.is_empty()) {
                style.push(format!("font-family:{}", css_font_family(name)));
            }
            if let Some(size) = font.size.filter(|s| *s != 0.0) {
                style.push(format!("font-size:{size:.2}pt"));
            }
            // Theme and indexed text colours are resolved too, except the
            // workbook's default text colour (the page's own text colour).
            let default_color = styles.fonts.first().and_then(|f| f.color.as_ref());
            let color = match font.color.as_ref() {
                Some(c) if c.rgb().is_some() || Some(c) != default_color => {
                    cell_color(c, "transparent")
                }
                _ => "transparent".to_string(),
            };
            if color != "transparent" {
                style.push(format!("color:{color}"));
            }
            if let Some(h) = xf.alignment.horizontal.as_deref() {
                style.push(format!("text-align:{h}"));
            }
            if let Some(v) = xf.alignment.vertical.as_deref() {
                style.push(format!("vertical-align:{v}"));
            }
            if xf.alignment.wrap_text {
                style.push("white-space:normal".into());
            }
            let border = styles.border(xf);
            for (side, name) in [
                (&border.top, "top"),
                (&border.right, "right"),
                (&border.bottom, "bottom"),
                (&border.left, "left"),
            ] {
                if let Some(css) = border_css(side, name) {
                    style.push(css);
                }
            }
            let rule_format = conditional.get(&coordinate);
            if let Some(format) = rule_format {
                style.extend(format.css());
            }
            let mut classes = vec!["cell"];
            let frozen_column = column_index <= frozen_columns;
            let frozen_row = row_index <= frozen_rows;
            if frozen_column {
                let offset = Num::Int(44)
                    .add(column_prefix[column_index as usize - 1])
                    .f();
                style.push(format!("position:sticky;left:{offset:.2}px"));
            }
            if frozen_row {
                let offset = Num::Int(26).add(row_prefix[row_index as usize - 1]).f();
                style.push(format!("position:sticky;top:{offset:.2}px"));
            }
            if frozen_column || frozen_row {
                classes.push("frozen");
                style.push(format!(
                    "z-index:{}",
                    if frozen_column && frozen_row { 2 } else { 1 }
                ));
            }

            let formula = data.and_then(|d| d.formula.as_ref());
            let display_value = match data {
                None => String::new(),
                Some(cell) => match formula {
                    Some(formula) => {
                        let fallback = if cell.cached.is_none() {
                            Value::Str(formula.text())
                        } else {
                            cell.cached.clone()
                        };
                        let value = match formula {
                            Formula::Text(_) => {
                                evaluation.display_value(&sheet.title, &coordinate, fallback)
                            }
                            // openpyxl returned array / data-table formulas as
                            // objects v3 could not evaluate.
                            _ => fallback,
                        };
                        format_computed_value(&value, &xf.number_format)
                    }
                    None if cell.value.is_none() => String::new(),
                    None => format_computed_value(&cell.value, &xf.number_format),
                },
            };
            let mut value = escape(&display_value);
            if rule_format.is_some_and(|f| f.hide_value) {
                value.clear();
            }
            if let Some(icon) = rule_format
                .map(|f| f.icon.as_str())
                .filter(|i| !i.is_empty())
            {
                value = format!("{icon}{value}");
            }
            let mut formula_attr = String::new();
            if let Some(formula) = formula {
                classes.push("formula");
                let mut text = formula.text();
                if !text.starts_with('=') {
                    text = format!("={text}");
                }
                formula_attr = format!(" data-formula=\"{}\"", escape(&text));
            }
            let mut extra = String::new();
            if let Some(target) = sheet.hyperlinks.get(&(row_index, column_index)) {
                classes.push("hyperlink");
                extra.push_str(&format!(" data-href=\"{}\"", escape(target)));
            }
            if let Some((author, text)) = sheet.comments.get(&(row_index, column_index)) {
                if !text.is_empty() {
                    classes.push("has-comment");
                    let mut note = py_strip(text).to_string();
                    if let Some(author) = author.as_deref().filter(|a| !a.is_empty()) {
                        note = format!("{author}: {note}");
                    }
                    let note = escape(&note);
                    extra.push_str(&format!(" data-comment=\"{note}\" title=\"{note}\""));
                }
            }
            let style_attr = if style.is_empty() {
                String::new()
            } else {
                format!(" style=\"{}\"", style.join(";"))
            };
            cells.push_str(&format!(
                "<td class=\"{}\" data-cell=\"{coordinate}\" data-qa-label=\"{}\" data-display-value=\"{}\"{formula_attr}{extra}{spans}{style_attr}>{value}</td>",
                classes.join(" "),
                escape(&coordinate),
                escape(&display_value),
            ));
        }
        let mut row_style = format!("height:{row_height:.2}px");
        if hidden_rows.contains(&row_index) {
            row_style.push_str(";visibility:collapse");
        }
        rows.push_str(&format!("<tr style=\"{row_style}\">{cells}</tr>"));
    }
    let truncated = data_rows > max_row || data_columns > max_column;
    let notice = if truncated {
        "<p class=\"notice\">Preview limited to the first 500 rows and 100 columns.</p>"
    } else {
        ""
    };

    let mut objects = String::new();
    let mut stage_width = Num::Int(44).add(column_prefix[column_pitch.len()]).f();
    let mut fit_width = Num::Int(44)
        .add(column_prefix[used_max_column.min(max_column) as usize])
        .f();
    // CSS cells have a 25px minimum height; use the rendered minimum so the
    // final rows are not falsely clipped.
    let mut stage_height = Num::Int(32).add(row_prefix[row_pitch.len()]).f();
    let mut fit_height = Num::Int(32)
        .add(row_prefix[used_max_row.min(max_row) as usize])
        .f();

    let column_left = |zero_based: i64| -> f64 {
        let inside = column_prefix[slice_len(column_pitch.len(), zero_based)];
        let beyond = PySum::of(
            ((max_column as i64 + 1)..=zero_based).map(|c| column_width_px(sheet, c as u32)),
        );
        Num::Int(44).add(inside).add(beyond).f()
    };
    let row_top = |zero_based: i64| -> f64 {
        let inside = row_prefix[slice_len(row_pitch.len(), zero_based)];
        let beyond = PySum::of(((max_row as i64 + 1)..=zero_based).map(|r| {
            row_height_px(sheet, r as u32)
                .max(Num::Int(25))
                .add(Num::Int(1))
        }));
        Num::Int(26).add(inside).add(beyond).f()
    };
    if let Some(part) = drawing_parts.get(&sheet.title) {
        let (shapes, right, bottom) =
            features::drawing_shapes_html(package, part, &column_left, &row_top);
        for shape in shapes {
            objects.push_str(&shape);
        }
        stage_width = stage_width.max(right);
        stage_height = stage_height.max(bottom);
        fit_width = fit_width.max(right);
        fit_height = fit_height.max(bottom);
    }
    for (index, chart) in sheet.charts.iter().enumerate() {
        let label = chart
            .title
            .clone()
            .unwrap_or_else(|| format!("Chart {}", index + 1));
        let (left, top, width, height) =
            object_box(&chart.anchor, DEFAULT_CHART_SIZE, &column_left, &row_top);
        stage_width = stage_width.max(left + width);
        stage_height = stage_height.max(top + height);
        fit_width = fit_width.max(left + width);
        fit_height = fit_height.max(top + height);
        let svg = chart::chart_svg(workbook, chart, evaluation);
        objects.push_str(&format!(
            "<figure class=\"workbook-chart\" data-qa-label=\"{label_attr}\" style=\"left:{left:.2}px;top:{top:.2}px;width:{width:.2}px;height:{height:.2}px\"><figcaption>{label_text}</figcaption>{svg}</figure>",
            label_attr = escape(&label),
            label_text = escape(&label),
        ));
    }
    for (index, image) in sheet.images.iter().enumerate() {
        let number = index + 1;
        let (left, top, width, height) = object_box(
            &image.anchor,
            (image.width, image.height),
            &column_left,
            &row_top,
        );
        stage_width = stage_width.max(left + width);
        stage_height = stage_height.max(top + height);
        fit_width = fit_width.max(left + width);
        fit_height = fit_height.max(top + height);
        use base64::Engine as _;
        let encoded = base64::engine::general_purpose::STANDARD.encode(&image.data);
        objects.push_str(&format!(
            "<img class=\"workbook-image\" data-qa-label=\"Image {number}\" style=\"left:{left:.2}px;top:{top:.2}px;width:{width:.2}px;height:{height:.2}px\" src=\"data:{};base64,{encoded}\" alt=\"Image {number}\">",
            image.mime
        ));
    }
    let mut sheet_classes = String::from("sheet");
    if sheet.show_grid_lines == Some(false) {
        sheet_classes.push_str(" no-gridlines");
    }
    let label = sheet_label(&sheet.title, &sheet.state);
    format!(
        "<section class=\"{sheet_classes}\" data-preview-item data-preview-label=\"{}\" data-preview-fit-width=\"{fit_width:.2}\" data-preview-fit-height=\"{fit_height:.2}\">{notice}<div class=\"grid-wrap\"><div class=\"grid-stage\" style=\"width:{stage_width:.2}px;height:{stage_height:.2}px\"><table><colgroup>{columns}</colgroup>{rows}</table>{objects}</div></div></section>",
        escape(&label)
    )
}

fn sheet_label(title: &str, state: &str) -> String {
    if state == "hidden" {
        format!("{title} (hidden)")
    } else {
        title.to_string()
    }
}

// ---------------------------------------------------------------- live build

/// Widths of the skeleton's cell bars, row by row (the header row first).
const SHEET_SKELETON_ROWS: [[&str; 6]; 8] = [
    ["70%", "60%", "64%", "56%", "62%", "58%"],
    ["82%", "40%", "46%", "38%", "44%", "50%"],
    ["64%", "48%", "36%", "52%", "40%", "46%"],
    ["76%", "42%", "50%", "44%", "38%", "54%"],
    ["58%", "52%", "40%", "48%", "56%", "36%"],
    ["70%", "38%", "54%", "42%", "46%", "44%"],
    ["62%", "46%", "44%", "50%", "40%", "52%"],
    ["80%", "56%", "48%", "40%", "52%", "42%"],
];

/// Loading skeletons for the sheets an agent has not added yet (v3
/// `_pending_sheet_skeletons`): the first missing sheet is the one being built.
fn pending_sheet_skeletons(plan: &DeckPlan, first: usize) -> Vec<String> {
    let mut cells = String::new();
    for (row, widths) in SHEET_SKELETON_ROWS.iter().enumerate() {
        let head = if row == 0 { " class=\"head\"" } else { "" };
        cells.push_str(&format!("<span{head}></span>"));
        for width in widths {
            cells.push_str(&format!(
                "<span{head}><i style=\"--w:{width};--d:{row}\"></i></span>"
            ));
        }
    }
    let grid = format!("<div class=\"sk-grid\" aria-hidden=\"true\">{cells}</div>");
    let total = plan.total as usize;
    (first..total)
        .map(|index| {
            let number = index + 1;
            let building = index == first;
            let state = if building { "building" } else { "pending" };
            let caption = if building {
                format!("Building sheet {number} of {total}")
            } else {
                "Up next".to_string()
            };
            let spinner = if building { "<span class=\"sk-spin\"></span>" } else { "" };
            let progress = if building {
                format!(
                    "<div class=\"sk-progress\" aria-hidden=\"true\"><span class=\"done\" style=\"width:{:.2}%\"></span><span class=\"now\" style=\"width:{:.2}%\"></span></div>",
                    100.0 * first as f64 / total as f64,
                    100.0 / total as f64
                )
            } else {
                String::new()
            };
            format!(
                "<section class=\"sheet sheet-skeleton\" data-preview-item data-preview-label=\"Sheet {number}\" data-slide-status=\"{state}\" data-preview-fit-width=\"960\" data-preview-fit-height=\"600\" aria-label=\"Sheet {number}, {}\"><span class=\"sk-chip\">{spinner}{caption}</span>{grid}{progress}</section>",
                caption.to_lowercase()
            )
        })
        .collect()
}
