//! Tables (v3 `_render_table`, `_table_cell_html`, `_table_style_*`).

use std::collections::BTreeMap;

use super::super::html::escape;
use super::color::{apply_brightness, solid_fill_color, Palette};
use super::fill::{identity, shape_box, Coords};
use super::model::{Shape, SlideCtx};
use super::text::{paragraphs, table_cell_paragraph_html, TextEnv};
use super::util::{
    child, cqw, elements, local, own_text, path, py_int, xml_bool, xsd_bool, Nd, Skip, R,
};

/// "Medium Style 2 - Accent 1", the one built-in style v3 painted.
const MEDIUM_STYLE_2_ACCENT_1: &str = "5C22544A-7EE6-4342-B048-85BDC9FD1C3A";

struct TableStyle {
    style_id: String,
    medium_style_2_accent_1: bool,
    accent: String,
    first_row: bool,
    last_row: bool,
    first_column: bool,
    last_column: bool,
    band_rows: bool,
    band_columns: bool,
}

fn style_context(table: Nd<'_>, palette: &Palette) -> TableStyle {
    let properties = child(table, "tblPr");
    let style_id = properties
        .and_then(|p| child(p, "tableStyleId"))
        .and_then(own_text)
        .filter(|t| !t.is_empty())
        .map(|t| {
            t.trim()
                .trim_matches(|c| c == '{' || c == '}')
                .to_uppercase()
        })
        .unwrap_or_default();
    let flag =
        |name: &str| properties.is_some_and(|p| xml_bool(p.attribute(name)).unwrap_or(false));
    TableStyle {
        medium_style_2_accent_1: style_id == MEDIUM_STYLE_2_ACCENT_1,
        style_id,
        accent: palette
            .get("accent1")
            .cloned()
            .unwrap_or_else(|| "#4f81bd".into()),
        first_row: flag("firstRow"),
        last_row: flag("lastRow"),
        first_column: flag("firstCol"),
        last_column: flag("lastCol"),
        band_rows: flag("bandRow"),
        band_columns: flag("bandCol"),
    }
}

struct CellPosition {
    row: usize,
    column: usize,
    rows: usize,
    columns: usize,
}

/// v3 `_table_style_cell_defaults`.
fn style_cell_defaults(
    style: &TableStyle,
    at: &CellPosition,
    slide_width: i64,
) -> (Vec<String>, Vec<String>) {
    let mut styles = Vec::new();
    let mut classes = vec!["table-cell".to_string()];
    if !style.medium_style_2_accent_1 {
        return (styles, classes);
    }
    let accent = &style.accent;
    styles.push(format!(
        "border:{} solid #ffffff",
        cqw(12700.0, slide_width)
    ));
    let first_row = style.first_row && at.row == 0;
    let last_row = style.last_row && at.row + 1 == at.rows;
    if first_row || last_row {
        classes.push(
            if first_row {
                "table-first-row"
            } else {
                "table-last-row"
            }
            .into(),
        );
        styles.extend([
            format!("background:{accent}"),
            "color:#ffffff".into(),
            "font-weight:700".into(),
        ]);
    } else if style.band_rows {
        let body_row = at.row as i64 - i64::from(style.first_row);
        let primary = body_row.rem_euclid(2) == 0;
        classes.push(
            if primary {
                "table-band-row-primary"
            } else {
                "table-band-row-secondary"
            }
            .into(),
        );
        styles.push(format!(
            "background:{}",
            apply_brightness(accent, if primary { 0.78 } else { 0.9 })
        ));
    }
    if style.band_columns {
        let body_column = at.column as i64 - i64::from(style.first_column);
        if body_column >= 0 && body_column % 2 == 0 {
            classes.push("table-band-column".into());
            styles.push(format!("background:{}", apply_brightness(accent, 0.82)));
        }
    }
    if style.first_column && at.column == 0 {
        classes.push("table-first-column".into());
        styles.push("font-weight:700".into());
    }
    if style.last_column && at.column + 1 == at.columns {
        classes.push("table-last-column".into());
        styles.push("font-weight:700".into());
    }
    (styles, classes)
}

/// v3 `_table_cell_fill`.
fn cell_fill(properties: Option<Nd<'_>>, palette: &Palette) -> R<(bool, Option<String>)> {
    let Some(properties) = properties else {
        return Ok((false, None));
    };
    if let Some(color) = solid_fill_color(Some(properties), palette)? {
        return Ok((true, Some(color)));
    }
    if child(properties, "noFill").is_some() {
        return Ok((true, None));
    }
    Ok((false, None))
}

/// v3 `_table_cell_border_styles`.
fn cell_borders(properties: Option<Nd<'_>>, palette: &Palette, slide_width: i64) -> R<Vec<String>> {
    let Some(properties) = properties else {
        return Ok(Vec::new());
    };
    let mut result = Vec::new();
    for (xml_name, css_name) in [
        ("lnL", "left"),
        ("lnR", "right"),
        ("lnT", "top"),
        ("lnB", "bottom"),
    ] {
        let Some(line) = child(properties, xml_name) else {
            continue;
        };
        if child(line, "noFill").is_some() {
            result.push(format!("border-{css_name}:none"));
            continue;
        }
        let color = solid_fill_color(Some(line), palette)?.unwrap_or_else(|| "#808080".into());
        let width = py_int(line.attribute("w").unwrap_or("12700"))
            .map(|w| w.max(1))
            .unwrap_or(12700);
        let dash = child(line, "prstDash")
            .map(|d| {
                d.attribute("val")
                    .filter(|v| !v.is_empty())
                    .unwrap_or("solid")
            })
            .unwrap_or("solid");
        let line_style = match dash {
            "dash" | "dashDot" | "lgDash" | "lgDashDot" | "lgDashDotDot" | "sysDash"
            | "sysDashDot" | "sysDashDotDot" => "dashed",
            "dot" | "sysDot" => "dotted",
            _ => "solid",
        };
        result.push(format!(
            "border-{css_name}:{} {line_style} {color}",
            cqw(width as f64, slide_width)
        ));
    }
    Ok(result)
}

/// A python-pptx `ST_Coordinate32`-ish attribute with a default.
fn margin(properties: Option<Nd<'_>>, name: &str, default: i64) -> i64 {
    properties
        .and_then(|p| p.attribute(name))
        .map(|raw| py_int(raw).unwrap_or(default))
        .unwrap_or(default)
}

fn cell_html(
    cell: Nd<'_>,
    env: &TextEnv<'_>,
    style: &TableStyle,
    at: &CellPosition,
    spans: (i64, i64),
) -> R<String> {
    let (mut styles, classes) = style_cell_defaults(style, at, env.slide_width);
    let properties = child(cell, "tcPr");
    let (has_fill, fill) = cell_fill(properties, env.palette)?;
    if has_fill {
        styles.push(format!(
            "background:{}",
            fill.as_deref().unwrap_or("transparent")
        ));
    }
    styles.extend(cell_borders(properties, env.palette, env.slide_width)?);
    let vertical = match properties.and_then(|p| p.attribute("anchor")) {
        Some("ctr") => "middle",
        Some("b") => "bottom",
        _ => "top",
    };
    styles.push(format!("vertical-align:{vertical}"));
    let margins = [
        margin(properties, "marT", 45720),
        margin(properties, "marR", 91440),
        margin(properties, "marB", 45720),
        margin(properties, "marL", 91440),
    ];
    styles.push(format!(
        "padding:{}",
        margins
            .iter()
            .map(|m| cqw(*m as f64, env.slide_width))
            .collect::<Vec<_>>()
            .join(" ")
    ));
    let tx_body = child(cell, "txBody");
    let list_style = super::text::list_style(tx_body);
    let mut counters = BTreeMap::new();
    let mut rendered = String::new();
    for paragraph in paragraphs(tx_body) {
        rendered.push_str(&table_cell_paragraph_html(
            paragraph,
            env,
            list_style,
            &mut counters,
        )?);
    }
    let (colspan, rowspan) = spans;
    let mut span_attributes = String::new();
    if colspan > 1 {
        span_attributes.push_str(&format!(" colspan=\"{colspan}\""));
    }
    if rowspan > 1 {
        span_attributes.push_str(&format!(" rowspan=\"{rowspan}\""));
    }
    span_attributes.push_str(&format!(
        " data-row-index=\"{}\" data-column-index=\"{}\"",
        at.row, at.column
    ));
    let style_attr = if styles.is_empty() {
        String::new()
    } else {
        format!(" style=\"{}\"", styles.join(";"))
    };
    Ok(format!(
        "<td class=\"{}\"{span_attributes}{style_attr}>{rendered}</td>",
        classes.join(" ")
    ))
}

fn span(cell: Nd<'_>, name: &str) -> R<i64> {
    match cell.attribute(name) {
        None => Ok(1),
        // Fix over v3 (raised, lost the table): an unreadable span is 1.
        Some(raw) => Ok(py_int(raw).unwrap_or(1)),
    }
}

/// v3 `_render_table`.
pub(super) fn render_table(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
    layer: &str,
    coords: Coords,
) -> R<String> {
    let table = path(shape.node, &["graphic", "graphicData", "tbl"]).ok_or(Skip)?;
    let env = TextEnv::of(ctx);
    let style = style_context(table, &ctx.palette);
    let rows: Vec<Nd<'_>> = elements(table).filter(|e| local(*e) == "tr").collect();
    let grid: Vec<Nd<'_>> = child(table, "tblGrid")
        .map(|g| elements(g).filter(|e| local(*e) == "gridCol").collect())
        .unwrap_or_default();
    let widths: Vec<i64> = grid
        .iter()
        // Fix over v3 (raised, lost the table): unreadable sizes are 0.
        .map(|c| Ok(c.attribute("w").and_then(py_int).unwrap_or(0)))
        .collect::<R<_>>()?;
    let heights: Vec<i64> = rows
        .iter()
        .map(|r| Ok(r.attribute("h").and_then(py_int).unwrap_or(0)))
        .collect::<R<_>>()?;
    let total_width = match widths.iter().fold(0i64, |a, b| a.saturating_add(*b)) {
        0 => 1,
        v => v,
    };
    let total_height = match heights.iter().fold(0i64, |a, b| a.saturating_add(*b)) {
        0 => 1,
        v => v,
    };
    let columns: String = widths
        .iter()
        .map(|w| {
            format!(
                "<col style=\"width:{}%\">",
                super::util::f(super::util::percent_of(*w, total_width as f64), 4)
            )
        })
        .collect();
    let mut rendered_rows = String::new();
    for (row_index, row) in rows.iter().enumerate() {
        let mut cells = String::new();
        for (column_index, cell) in elements(*row).filter(|e| local(*e) == "tc").enumerate() {
            if xsd_bool(cell.attribute("hMerge")) || xsd_bool(cell.attribute("vMerge")) {
                continue;
            }
            let (width, height) = (span(cell, "gridSpan")?, span(cell, "rowSpan")?);
            let origin = width > 1 || height > 1;
            let spans = if origin { (width, height) } else { (1, 1) };
            let at = CellPosition {
                row: row_index,
                column: column_index,
                rows: rows.len(),
                columns: grid.len(),
            };
            cells.push_str(&cell_html(cell, &env, &style, &at, spans)?);
        }
        let row_height = super::util::percent_of(heights[row_index], total_height as f64);
        rendered_rows.push_str(&format!(
            "<tr style=\"height:{}%\">{cells}</tr>",
            super::util::f(row_height, 4)
        ));
    }
    let box_style = shape_box(ctx, shape, coords)?;
    let identity = identity(shape, layer)?;
    Ok(format!(
        "<div class=\"shape table-shape\" {identity} style=\"{box_style}\"><table data-table-style-id=\"{}\"><colgroup>{columns}</colgroup><tbody>{rendered_rows}</tbody></table></div>",
        escape(&style.style_id)
    ))
}
