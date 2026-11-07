//! Workbook features the openpyxl object model drops or the grid renderer
//! skipped (v3 `xlsx_features.py`): conditional formatting, drawing shapes and
//! text boxes, the sanitized copy for packages openpyxl cannot parse, and the
//! visible sheet names.

use std::collections::{HashMap, HashSet};

use super::book::{Cfvo, Color, ColorKind, DataBar, Dxf, IconSet, Rule, Worksheet};
use super::formula::column_letter;
use super::value::{casefold, parse_py_float, py_strip, Value};
use crate::preview::html::{escape, parse_xml};
use crate::preview::package::Package;

const EMU_PER_PX: f64 = 914_400.0 / 96.0;

/// The Office theme, in Excel's theme-index order (lt1, dk1, lt2, dk2,
/// accent1–6, hlink, folHlink); used when a workbook has no theme part.
const THEME_FALLBACK: [&str; 12] = [
    "#ffffff", "#000000", "#e7e6e6", "#44546a", "#4472c4", "#ed7d31", "#a5a5a5", "#ffc000",
    "#5b9bd5", "#70ad47", "#0563c1", "#954f72",
];

/// The colours theme and indexed references resolve to: the workbook's theme
/// part and `indexedColors` palette, else the Office defaults (v3 always used
/// the defaults).
#[derive(Debug, Clone, PartialEq)]
pub struct Palette {
    pub theme: Vec<String>,
    pub indexed: Vec<String>,
}

impl Default for Palette {
    fn default() -> Self {
        Self {
            theme: THEME_FALLBACK.iter().map(|s| s.to_string()).collect(),
            indexed: COLOR_INDEX
                .iter()
                .map(|s| format!("#{}", s[2..].to_lowercase()))
                .collect(),
        }
    }
}

impl Palette {
    /// Read `<a:clrScheme>` from a theme part, keeping defaults for gaps.
    pub fn with_theme(mut self, theme_xml: Option<&str>) -> Self {
        let Some(doc) = theme_xml.and_then(|x| parse_xml(x).ok()) else {
            return self;
        };
        let Some(scheme) = doc
            .descendants()
            .find(|n| n.is_element() && n.tag_name().name() == "clrScheme")
        else {
            return self;
        };
        let order = [
            "lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5",
            "accent6", "hlink", "folHlink",
        ];
        for (index, name) in order.iter().enumerate() {
            let Some(slot) = child(scheme, name) else {
                continue;
            };
            for c in slot.children().filter(|c| c.is_element()) {
                let value = match c.tag_name().name() {
                    "srgbClr" => c.attribute("val"),
                    "sysClr" => c.attribute("lastClr"),
                    _ => None,
                };
                if let Some(v) = value.filter(|v| hex6(v)) {
                    self.theme[index] = format!("#{}", v.to_lowercase());
                    break;
                }
            }
        }
        self
    }

    /// Replace the indexed palette with `<colors><indexedColors>`.
    pub fn with_indexed(mut self, colors: &[String]) -> Self {
        for (index, rgb) in colors.iter().enumerate().take(self.indexed.len()) {
            let tail = &rgb[rgb.len().saturating_sub(6)..];
            if hex6(tail) {
                self.indexed[index] = format!("#{}", tail.to_lowercase());
            }
        }
        self
    }
}

thread_local! {
    static PALETTE: std::cell::RefCell<Palette> = std::cell::RefCell::new(Palette::default());
}

/// Makes `palette` the one colours resolve to until the guard drops.
pub struct PaletteGuard(Option<Palette>);

pub fn use_palette(palette: Palette) -> PaletteGuard {
    PaletteGuard(Some(PALETTE.with(|p| p.replace(palette))))
}

impl Drop for PaletteGuard {
    fn drop(&mut self) {
        if let Some(previous) = self.0.take() {
            PALETTE.with(|p| *p.borrow_mut() = previous);
        }
    }
}

fn theme_color(index: usize) -> Option<String> {
    PALETTE.with(|p| p.borrow().theme.get(index).cloned())
}

/// openpyxl `COLOR_INDEX`.
const COLOR_INDEX: [&str; 64] = [
    "00000000", "00FFFFFF", "00FF0000", "0000FF00", "000000FF", "00FFFF00", "00FF00FF", "0000FFFF",
    "00000000", "00FFFFFF", "00FF0000", "0000FF00", "000000FF", "00FFFF00", "00FF00FF", "0000FFFF",
    "00800000", "00008000", "00000080", "00808000", "00800080", "00008080", "00C0C0C0", "00808080",
    "009999FF", "00993366", "00FFFFCC", "00CCFFFF", "00660066", "00FF8080", "000066CC", "00CCCCFF",
    "00000080", "00FF00FF", "00FFFF00", "0000FFFF", "00800080", "00800000", "00008080", "000000FF",
    "0000CCFF", "00CCFFFF", "00CCFFCC", "00FFFF99", "0099CCFF", "00FF99CC", "00CC99FF", "00FFCC99",
    "003366FF", "0033CCCC", "0099CC00", "00FFCC00", "00FF9900", "00FF6600", "00666699", "00969696",
    "00003366", "00339966", "00003300", "00333300", "00993300", "00993366", "00333399", "00333333",
];

// ---------------------------------------------------------------- markup-compatibility sanitising

/// Replace every `mc:AlternateContent` with its `mc:Fallback` content.
pub fn resolve_markup_compatibility(xml: &str) -> Option<String> {
    if !xml.contains("AlternateContent") {
        return None;
    }
    let doc = parse_xml(xml).ok()?;
    fn is_ac(n: &roxmltree::Node) -> bool {
        n.is_element() && n.tag_name().name() == "AlternateContent"
    }
    fn render(xml: &str, node: roxmltree::Node) -> String {
        // The node's source with nested AlternateContent resolved.
        let range = node.range();
        let mut out = String::new();
        let mut cursor = range.start;
        let mut stack: Vec<roxmltree::Node> = node.children().collect();
        stack.reverse();
        let mut edits: Vec<(std::ops::Range<usize>, String)> = Vec::new();
        while let Some(n) = stack.pop() {
            if is_ac(&n) {
                edits.push((n.range(), fallback(xml, n)));
                continue;
            }
            let mut kids: Vec<roxmltree::Node> = n.children().collect();
            kids.reverse();
            stack.extend(kids);
        }
        edits.sort_by_key(|(r, _)| r.start);
        for (r, replacement) in edits {
            if r.start < cursor {
                continue;
            }
            out.push_str(&xml[cursor..r.start]);
            out.push_str(&replacement);
            cursor = r.end;
        }
        out.push_str(&xml[cursor..range.end]);
        out
    }
    fn fallback(xml: &str, ac: roxmltree::Node) -> String {
        ac.children()
            .find(|c| c.is_element() && c.tag_name().name() == "Fallback")
            .map(|f| {
                f.children()
                    .filter(|c| c.is_element())
                    .map(|c| {
                        if is_ac(&c) {
                            fallback(xml, c)
                        } else {
                            render(xml, c)
                        }
                    })
                    .collect()
            })
            .unwrap_or_default()
    }
    let root = doc.root_element();
    let mut out = xml[..root.range().start].to_string();
    out.push_str(&render(xml, root));
    out.push_str(&xml[root.range().end..]);
    Some(out)
}

fn name_unnamed_cell_styles(xml: &str) -> Option<String> {
    if !xml.contains("cellStyle") {
        return None;
    }
    let doc = parse_xml(xml).ok()?;
    let mut edits: Vec<(std::ops::Range<usize>, String)> = Vec::new();
    for (index, style) in doc
        .descendants()
        .filter(|n| n.is_element() && n.tag_name().name() == "cellStyle")
        .enumerate()
    {
        if style.attribute("name").is_some_and(|n| !n.is_empty()) {
            continue;
        }
        let name = format!(" name=\"Style {}\"", index + 1);
        match style
            .attributes()
            .find(|a| a.name() == "name" && a.namespace().is_none())
        {
            Some(attr) => edits.push((attr.range(), name.trim_start().to_string())),
            None => {
                let start = style.range().start
                    + 1
                    + xml[style.range().start + 1..]
                        .find(|c: char| c.is_whitespace() || c == '/' || c == '>')
                        .unwrap_or(0);
                edits.push((start..start, name));
            }
        }
    }
    (!edits.is_empty()).then(|| splice(xml, edits))
}

fn drop_children(xml: &str, wanted: impl Fn(&roxmltree::Node) -> bool) -> Option<String> {
    let doc = parse_xml(xml).ok()?;
    let edits: Vec<_> = doc
        .descendants()
        .filter(|n| n.is_element() && wanted(n))
        .map(|n| (n.range(), String::new()))
        .collect();
    (!edits.is_empty()).then(|| splice(xml, edits))
}

fn splice(xml: &str, mut edits: Vec<(std::ops::Range<usize>, String)>) -> String {
    edits.sort_by_key(|(r, _)| std::cmp::Reverse(r.start));
    let mut out = xml.to_string();
    for (range, replacement) in edits {
        out.replace_range(range, &replacement);
    }
    out
}

/// v3 `sanitized_workbook_bytes`: a copy whose XML parts openpyxl can load
/// (markup compatibility resolved to fallbacks, unnamed cell styles named,
/// pivot caches and pivot-table relationships dropped).
pub fn sanitized_package(package: &Package) -> Package {
    let parts = package.names().map(|name| {
        let bytes = package.bytes(name).unwrap_or_default();
        let mut payload = bytes.to_vec();
        if name.ends_with(".xml") || name.starts_with("xl/worksheets/_rels/") {
            if let Some(mut text) = package.text(name) {
                let mut changed = false;
                if name.ends_with(".xml") {
                    if let Some(t) = resolve_markup_compatibility(&text) {
                        text = t;
                        changed = true;
                    }
                    if name == "xl/styles.xml" {
                        if let Some(t) = name_unnamed_cell_styles(&text) {
                            text = t;
                            changed = true;
                        }
                    } else if name == "xl/workbook.xml" && text.contains("pivotCaches") {
                        let root_depth = |n: &roxmltree::Node| {
                            n.tag_name().name() == "pivotCaches"
                                && n.parent()
                                    .is_some_and(|p| p.parent().is_some_and(|g| g.is_root()))
                        };
                        if let Some(t) = drop_children(&text, root_depth) {
                            text = t;
                            changed = true;
                        }
                    }
                } else if text.contains("pivotTable") {
                    let pivot = |n: &roxmltree::Node| {
                        n.tag_name().name() == "Relationship"
                            && n.attribute("Type")
                                .unwrap_or_default()
                                .ends_with("/pivotTable")
                    };
                    if let Some(t) = drop_children(&text, pivot) {
                        text = t;
                        changed = true;
                    }
                }
                if changed {
                    payload = text.into_bytes();
                }
            }
        }
        (name.to_string(), payload)
    });
    Package::from_parts(parts.collect::<Vec<_>>())
}

// ---------------------------------------------------------------- sheet names and drawings

fn workbook_doc_sheets(package: &Package) -> Option<Vec<(String, String, Option<String>)>> {
    let text = package.text("xl/workbook.xml")?;
    let doc = parse_xml(&text).ok()?;
    Some(
        doc.descendants()
            .filter(|n| n.is_element() && n.tag_name().name() == "sheet")
            .map(|n| {
                let id = n
                    .attributes()
                    .find(|a| a.name() == "id" && a.namespace().is_some())
                    .map(|a| a.value().to_string());
                (
                    n.attribute("name").unwrap_or_default().to_string(),
                    n.attribute("state").unwrap_or("visible").to_string(),
                    id,
                )
            })
            .collect(),
    )
}

/// Workbook sheet names in tab order, hidden sheets skipped.
pub fn visible_sheet_names(package: &Package) -> Vec<String> {
    workbook_doc_sheets(package)
        .unwrap_or_default()
        .into_iter()
        .filter(|(_, state, _)| state == "visible")
        .map(|(name, _, _)| name)
        .collect()
}

fn relationship_targets(package: &Package, part: &str) -> HashMap<String, String> {
    package
        .rels(part)
        .into_iter()
        .filter(|r| !r.external)
        .map(|r| (r.id, r.target))
        .collect()
}

/// Worksheet titles → the drawing part each one references.
pub fn worksheet_drawing_parts(package: &Package) -> HashMap<String, String> {
    let mut result = HashMap::new();
    let Some(sheets) = workbook_doc_sheets(package) else {
        return result;
    };
    let targets = relationship_targets(package, "xl/workbook.xml");
    for (name, _, id) in sheets {
        let Some(part) = id.and_then(|id| targets.get(&id).cloned()) else {
            continue;
        };
        let Some(text) = package.text(&part) else {
            continue;
        };
        let Ok(doc) = parse_xml(&text) else {
            return HashMap::new();
        };
        let Some(drawing) = doc
            .root_element()
            .children()
            .find(|n| n.is_element() && n.tag_name().name() == "drawing")
        else {
            continue;
        };
        let id = drawing
            .attributes()
            .find(|a| a.name() == "id" && a.namespace().is_some())
            .map(|a| a.value())
            .unwrap_or_default();
        if let Some(target) = relationship_targets(package, &part).get(id) {
            if !target.is_empty() {
                result.insert(name, target.clone());
            }
        }
    }
    result
}

fn child<'a, 'i>(node: roxmltree::Node<'a, 'i>, name: &str) -> Option<roxmltree::Node<'a, 'i>> {
    node.children()
        .find(|c| c.is_element() && c.tag_name().name() == name)
}

fn hex6(text: &str) -> bool {
    text.len() == 6 && text.chars().all(|c| c.is_ascii_hexdigit())
}

fn drawing_color(element: Option<roxmltree::Node>) -> Option<String> {
    for c in element?.children().filter(|c| c.is_element()) {
        match c.tag_name().name() {
            "srgbClr" => {
                let v = c.attribute("val").unwrap_or_default();
                if hex6(v) {
                    return Some(format!("#{}", v.to_lowercase()));
                }
            }
            "schemeClr" => {
                let index = match c.attribute("val").unwrap_or_default() {
                    "lt1" | "bg1" => Some(0),
                    "dk1" | "tx1" => Some(1),
                    "lt2" | "bg2" => Some(2),
                    "dk2" | "tx2" => Some(3),
                    "accent1" => Some(4),
                    "accent2" => Some(5),
                    "accent3" => Some(6),
                    "accent4" => Some(7),
                    "accent5" => Some(8),
                    "accent6" => Some(9),
                    "hlink" => Some(10),
                    "folHlink" => Some(11),
                    _ => None,
                };
                if let Some(color) = index.and_then(theme_color) {
                    return Some(color);
                }
            }
            "sysClr" => {
                let v = c.attribute("lastClr").unwrap_or_default();
                if hex6(v) {
                    return Some(format!("#{}", v.to_lowercase()));
                }
            }
            _ => {}
        }
    }
    None
}

fn py_int(text: Option<&str>, default: i64) -> i64 {
    text.and_then(|t| t.trim().replace('_', "").parse::<i64>().ok())
        .unwrap_or(default)
}

fn marker_px(
    marker: roxmltree::Node,
    column_left: &dyn Fn(i64) -> f64,
    row_top: &dyn Fn(i64) -> f64,
) -> (f64, f64) {
    let number = |name: &str| {
        child(marker, name)
            .map(|n| n.text().unwrap_or("0").trim().parse::<i64>().unwrap_or(0))
            .unwrap_or(0)
    };
    (
        column_left(number("col")) + number("colOff") as f64 / EMU_PER_PX,
        row_top(number("row")) + number("rowOff") as f64 / EMU_PER_PX,
    )
}

type BoxPx = (f64, f64, f64, f64);

fn anchor_box(
    anchor: roxmltree::Node,
    column_left: &dyn Fn(i64) -> f64,
    row_top: &dyn Fn(i64) -> f64,
) -> Option<BoxPx> {
    let kind = anchor.tag_name().name();
    let ext = |e: roxmltree::Node| {
        (
            py_int(e.attribute("cx"), 0) as f64 / EMU_PER_PX,
            py_int(e.attribute("cy"), 0) as f64 / EMU_PER_PX,
        )
    };
    if kind == "absoluteAnchor" {
        let (pos, extent) = (child(anchor, "pos")?, child(anchor, "ext")?);
        let (w, h) = ext(extent);
        return Some((
            44.0 + py_int(pos.attribute("x"), 0) as f64 / EMU_PER_PX,
            25.0 + py_int(pos.attribute("y"), 0) as f64 / EMU_PER_PX,
            w,
            h,
        ));
    }
    let (left, top) = marker_px(child(anchor, "from")?, column_left, row_top);
    if kind == "twoCellAnchor" {
        let (right, bottom) = marker_px(child(anchor, "to")?, column_left, row_top);
        return Some((left, top, (right - left).max(1.0), (bottom - top).max(1.0)));
    }
    let (w, h) = ext(child(anchor, "ext")?);
    Some((left, top, w, h))
}

fn shape_html(shape: roxmltree::Node, (left, top, width, height): BoxPx) -> String {
    let mut styles = vec![
        format!("left:{left:.2}px"),
        format!("top:{top:.2}px"),
        format!("width:{width:.2}px"),
        format!("height:{height:.2}px"),
    ];
    if let Some(props) = child(shape, "spPr") {
        if let Some(fill) = child(props, "solidFill") {
            if let Some(color) = drawing_color(Some(fill)) {
                styles.push(format!("background:{color}"));
            }
        }
        if let Some(line) = child(props, "ln") {
            if child(line, "noFill").is_none() {
                let color =
                    drawing_color(child(line, "solidFill")).unwrap_or_else(|| "#4472c4".into());
                let w = py_int(line.attribute("w").filter(|w| !w.is_empty()), 9525) as f64;
                styles.push(format!(
                    "border:{:.1}px solid {color}",
                    (w / EMU_PER_PX).max(1.0)
                ));
            }
        }
        let preset = child(props, "prstGeom")
            .and_then(|g| g.attribute("prst"))
            .unwrap_or_default();
        if matches!(preset, "ellipse" | "flowChartConnector" | "donut") {
            styles.push("border-radius:50%".into());
        } else if matches!(preset, "roundRect" | "flowChartAlternateProcess") {
            styles.push("border-radius:12px".into());
        }
        let rotation = child(props, "xfrm").map_or(0, |x| {
            py_int(x.attribute("rot").filter(|r| !r.is_empty()), 0)
        });
        if rotation != 0 {
            styles.push(format!(
                "transform:rotate({:.2}deg)",
                rotation as f64 / 60000.0
            ));
        }
    }
    let mut paragraphs = String::new();
    if let Some(body) = child(shape, "txBody") {
        for paragraph in body
            .children()
            .filter(|c| c.is_element() && c.tag_name().name() == "p")
        {
            let mut runs = String::new();
            let mut align = "";
            for node in paragraph.children().filter(|c| c.is_element()) {
                match node.tag_name().name() {
                    "pPr" => {
                        align = match node.attribute("algn").unwrap_or_default() {
                            "ctr" => "center",
                            "r" => "right",
                            "just" => "justify",
                            _ => "",
                        };
                    }
                    "r" | "fld" => {
                        let text = child(node, "t").and_then(|t| t.text()).unwrap_or_default();
                        let mut run_styles = Vec::new();
                        if let Some(rp) = child(node, "rPr") {
                            if rp.attribute("b") == Some("1") {
                                run_styles.push("font-weight:700".to_string());
                            }
                            if rp.attribute("i") == Some("1") {
                                run_styles.push("font-style:italic".to_string());
                            }
                            if let Some(size) = rp
                                .attribute("sz")
                                .filter(|s| !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()))
                            {
                                let size: f64 = size.parse().unwrap_or(0.0);
                                run_styles.push(format!("font-size:{:.1}pt", size / 100.0));
                            }
                            if let Some(color) = drawing_color(child(rp, "solidFill")) {
                                run_styles.push(format!("color:{color}"));
                            }
                        }
                        let style = if run_styles.is_empty() {
                            String::new()
                        } else {
                            format!(" style=\"{}\"", run_styles.join(";"))
                        };
                        runs.push_str(&format!("<span{style}>{}</span>", escape(text)));
                    }
                    "br" => runs.push_str("<br>"),
                    _ => {}
                }
            }
            let style = if align.is_empty() {
                String::new()
            } else {
                format!(" style=\"text-align:{align}\"")
            };
            let content = if runs.is_empty() {
                "&nbsp;".to_string()
            } else {
                runs
            };
            paragraphs.push_str(&format!("<p{style}>{content}</p>"));
        }
    }
    let name_node = child(shape, "nvSpPr").and_then(|n| child(n, "cNvPr"));
    let name = escape(
        name_node
            .and_then(|n| n.attribute("name"))
            .unwrap_or_default(),
    );
    let shape_id = escape(
        name_node
            .and_then(|n| n.attribute("id"))
            .unwrap_or_default(),
    );
    let label = if name.is_empty() {
        "Shape".to_string()
    } else {
        name.clone()
    };
    format!(
        "<div class=\"workbook-shape\" data-shape-id=\"{shape_id}\" data-shape-name=\"{name}\" data-qa-label=\"{label}\" style=\"{}\">{paragraphs}</div>",
        styles.join(";")
    )
}

/// The anchors of the drawing's shapes and text boxes (for the sheet bounds).
pub fn drawing_anchors(package: &Package, drawing_part: &str) -> Vec<super::book::Anchor> {
    let Some(text) = package.text(drawing_part) else {
        return Vec::new();
    };
    let Ok(doc) = parse_xml(&text) else {
        return Vec::new();
    };
    doc.root_element()
        .children()
        .filter(|a| {
            a.is_element()
                && matches!(
                    a.tag_name().name(),
                    "twoCellAnchor" | "oneCellAnchor" | "absoluteAnchor"
                )
                && a.descendants()
                    .any(|n| n.is_element() && n.tag_name().name() == "sp")
        })
        .map(super::book::parse_anchor)
        .collect()
}

/// Render the shapes/text boxes of a worksheet drawing, with the right and
/// bottom edges they occupy.
pub fn drawing_shapes_html(
    package: &Package,
    drawing_part: &str,
    column_left: &dyn Fn(i64) -> f64,
    row_top: &dyn Fn(i64) -> f64,
) -> (Vec<String>, f64, f64) {
    let Some(text) = package.text(drawing_part) else {
        return (Vec::new(), 0.0, 0.0);
    };
    let Ok(doc) = parse_xml(&text) else {
        return (Vec::new(), 0.0, 0.0);
    };
    let mut fragments = Vec::new();
    let (mut right, mut bottom) = (0.0f64, 0.0f64);
    for anchor in doc.root_element().children().filter(|c| c.is_element()) {
        if !matches!(
            anchor.tag_name().name(),
            "twoCellAnchor" | "oneCellAnchor" | "absoluteAnchor"
        ) {
            continue;
        }
        let Some(bx) = anchor_box(anchor, column_left, row_top) else {
            continue;
        };
        if let Some(shape) = anchor
            .descendants()
            .find(|n| n.is_element() && n.tag_name().name() == "sp")
        {
            fragments.push(shape_html(shape, bx));
            right = right.max(bx.0 + bx.2);
            bottom = bottom.max(bx.1 + bx.3);
        }
    }
    (fragments, right, bottom)
}

// ---------------------------------------------------------------- conditional formatting

/// Presentation produced by conditional formatting for one cell.
#[derive(Debug, Clone, Default)]
pub struct CellFormat {
    styles: Vec<(String, String)>,
    pub icon: String,
    pub hide_value: bool,
}

impl CellFormat {
    /// Rules apply in priority order; the first to set a property wins.
    fn set(&mut self, name: &str, value: String) {
        if !self.styles.iter().any(|(n, _)| n == name) {
            self.styles.push((name.to_string(), value));
        }
    }

    pub fn css(&self) -> Vec<String> {
        self.styles
            .iter()
            .map(|(n, v)| format!("{n}:{v}"))
            .collect()
    }
}

/// v3 `numeric_value`.
pub fn numeric_value(value: &Value) -> Option<f64> {
    match value {
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        Value::Int(_) | Value::Float(_) => value.py_float().filter(|f| f.is_finite()),
        Value::Str(s) => parse_py_float(&s.replace(',', "")).filter(|f| f.is_finite()),
        _ => None,
    }
}

/// v3 `color_css`: an openpyxl colour as CSS, theme colours and tint included.
pub fn color_css(color: Option<&Color>) -> Option<String> {
    let color = color?;
    let rgb = match &color.kind {
        ColorKind::Rgb(rgb) => {
            let tail: String = rgb
                .chars()
                .rev()
                .take(6)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect();
            (hex6(&tail) && rgb != "00000000").then(|| format!("#{}", tail.to_lowercase()))
        }
        ColorKind::Theme(index) => theme_color(*index as usize),
        ColorKind::Indexed(index) => {
            let i = *index as usize;
            PALETTE.with(|p| p.borrow().indexed.get(i).cloned())
        }
        ColorKind::Auto => None,
    }?;
    Some(if color.tint != 0.0 {
        apply_tint(&rgb, color.tint)
    } else {
        rgb
    })
}

fn channels(rgb: &str) -> [i64; 3] {
    [1, 3, 5].map(|i| i64::from_str_radix(&rgb[i..i + 2], 16).unwrap_or(0))
}

fn apply_tint(rgb: &str, tint: f64) -> String {
    let c = channels(rgb).map(|ch| {
        let ch = ch as f64;
        let v = if tint < 0.0 {
            ch * (1.0 + tint)
        } else {
            ch + (255.0 - ch) * tint
        };
        (v.round_ties_even() as i64).clamp(0, 255)
    });
    format!("#{:02x}{:02x}{:02x}", c[0], c[1], c[2])
}

fn mix(start: &str, end: &str, ratio: f64) -> String {
    let ratio = ratio.clamp(0.0, 1.0);
    let (a, b) = (channels(start), channels(end));
    let c: Vec<String> = (0..3)
        .map(|i| {
            let v = (a[i] as f64 + (b[i] - a[i]) as f64 * ratio).round_ties_even() as i64;
            format!("{v:02x}")
        })
        .collect();
    format!("#{}", c.concat())
}

fn dxf_styles(dxf: Option<&Dxf>) -> Vec<(&'static str, String)> {
    let mut styles = Vec::new();
    let Some(dxf) = dxf else {
        return styles;
    };
    if let Some(fill) = &dxf.fill {
        let color = if fill.gradient {
            None
        } else {
            color_css(Some(&fill.bg)).or_else(|| color_css(Some(&fill.fg)))
        };
        if let Some(color) = color {
            styles.push(("background", color));
        }
    }
    if let Some(font) = &dxf.font {
        if let Some(color) = color_css(font.color.as_ref()) {
            styles.push(("color", color));
        }
        if font.bold {
            styles.push(("font-weight", "700".into()));
        }
        if font.italic {
            styles.push(("font-style", "italic".into()));
        }
        if font.strike {
            styles.push(("text-decoration", "line-through".into()));
        } else if font.underline.is_some() {
            styles.push(("text-decoration", "underline".into()));
        }
    }
    styles
}

fn formula_number(formula: &[String], index: usize) -> Option<f64> {
    formula
        .get(index)
        .and_then(|f| numeric_value(&Value::Str(py_strip(f).to_string())))
}

fn formula_text(formula: &[String], text: Option<&str>) -> String {
    if let Some(text) = text.filter(|t| !t.is_empty()) {
        return text.to_string();
    }
    if let Some(first) = formula.first() {
        if let Some(start) = first.find('"') {
            if let Some(len) = first[start + 1..].find('"') {
                return first[start + 1..start + 1 + len].to_string();
            }
        }
    }
    String::new()
}

fn cell_is(operator: Option<&str>, value: &Value, formula: &[String]) -> bool {
    let number = numeric_value(value);
    let first = formula_number(formula, 0);
    let second = formula_number(formula, 1);
    let (Some(number), Some(first)) = (number, first) else {
        if matches!(operator, Some("equal" | "notEqual")) && !formula.is_empty() {
            let expected = py_strip(&formula[0]).trim_matches('"').to_string();
            let actual = if value.is_none() {
                String::new()
            } else {
                value.py_str()
            };
            let matched = actual == expected;
            return if operator == Some("equal") {
                matched
            } else {
                !matched
            };
        }
        return false;
    };
    match (operator, second) {
        (Some("between"), Some(second)) => {
            first.min(second) <= number && number <= first.max(second)
        }
        (Some("notBetween"), Some(second)) => {
            !(first.min(second) <= number && number <= first.max(second))
        }
        (Some("equal"), _) => number == first,
        (Some("notEqual"), _) => number != first,
        (Some("greaterThan"), _) => number > first,
        (Some("greaterThanOrEqual"), _) => number >= first,
        (Some("lessThan"), _) => number < first,
        (Some("lessThanOrEqual"), _) => number <= first,
        _ => false,
    }
}

fn threshold(cfvo: Option<&Cfvo>, numbers: &[f64], default: f64) -> f64 {
    if numbers.is_empty() {
        return default;
    }
    let kind = cfvo.and_then(|c| c.kind.as_deref());
    let raw = cfvo
        .and_then(|c| c.val.as_deref())
        .and_then(|v| numeric_value(&Value::Str(v.to_string())));
    let low = numbers.iter().copied().fold(f64::INFINITY, f64::min);
    let high = numbers.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    match (kind, raw) {
        (Some("min"), _) => low,
        (Some("max"), _) => high,
        (Some("percent"), Some(raw)) => low + (high - low) * raw / 100.0,
        (Some("percentile"), Some(raw)) => {
            let mut ordered = numbers.to_vec();
            ordered.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            let position = (ordered.len() - 1) as f64 * raw / 100.0;
            let lower = position.floor().max(0.0) as usize;
            let upper = (position.ceil().max(0.0) as usize).min(ordered.len() - 1);
            let lower = lower.min(ordered.len() - 1);
            ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower as f64)
        }
        (_, Some(raw)) => raw,
        _ => default,
    }
}

/// Glyph sets per icon set (colour, glyph), lowest band first.
fn icon_set(name: &str) -> Option<&'static [(&'static str, &'static str)]> {
    Some(match name {
        "3Arrows" => &[("#e74c3c", "▼"), ("#f1c40f", "►"), ("#27ae60", "▲")],
        "3ArrowsGray" => &[("#7f8c8d", "▼"), ("#7f8c8d", "►"), ("#7f8c8d", "▲")],
        "3TrafficLights1" | "3TrafficLights2" => {
            &[("#e74c3c", "●"), ("#f1c40f", "●"), ("#27ae60", "●")]
        }
        "3Signs" => &[("#e74c3c", "◆"), ("#f1c40f", "▲"), ("#27ae60", "●")],
        "3Symbols" | "3Symbols2" => &[("#e74c3c", "✖"), ("#f1c40f", "!"), ("#27ae60", "✔")],
        "3Flags" => &[("#e74c3c", "⚑"), ("#f1c40f", "⚑"), ("#27ae60", "⚑")],
        "4Arrows" => &[
            ("#e74c3c", "▼"),
            ("#e67e22", "◢"),
            ("#f1c40f", "◥"),
            ("#27ae60", "▲"),
        ],
        "4TrafficLights" => &[
            ("#2c3e50", "●"),
            ("#e74c3c", "●"),
            ("#f1c40f", "●"),
            ("#27ae60", "●"),
        ],
        "5Arrows" => &[
            ("#e74c3c", "▼"),
            ("#e67e22", "◢"),
            ("#f1c40f", "►"),
            ("#9acd32", "◥"),
            ("#27ae60", "▲"),
        ],
        "5Quarters" => &[
            ("#bdc3c7", "○"),
            ("#7f8c8d", "◔"),
            ("#7f8c8d", "◑"),
            ("#7f8c8d", "◕"),
            ("#2c3e50", "●"),
        ],
        "5Rating" => &[
            ("#bdc3c7", "▁"),
            ("#3498db", "▂"),
            ("#3498db", "▃"),
            ("#3498db", "▅"),
            ("#3498db", "▇"),
        ],
        _ => return None,
    })
}

type Values = Vec<(String, Value)>;
type Coordinates = Vec<(u32, u32)>;

/// Evaluate the sheet's conditional formatting into per-cell presentation.
/// `value_of` reads a cell (without growing the sheet, unlike v3).
pub fn conditional_formats(
    sheet: &Worksheet,
    value_of: &mut dyn FnMut(u32, u32) -> Value,
) -> HashMap<String, CellFormat> {
    let mut entries: Vec<(i64, Coordinates, &Rule)> = Vec::new();
    for block in &sheet.conditional {
        let mut coordinates = Vec::new();
        for range in &block.ranges {
            for row in range.min_row..=range.max_row.min(5000) {
                for column in range.min_col..=range.max_col.min(200) {
                    coordinates.push((row, column));
                }
            }
        }
        for rule in &block.rules {
            entries.push((rule.priority, coordinates.clone(), rule));
        }
    }
    entries.sort_by_key(|e| e.0);

    let mut result: HashMap<String, CellFormat> = HashMap::new();
    for (_, coordinates, rule) in entries {
        let mut seen = HashSet::new();
        let mut values: Values = Vec::new();
        for (row, column) in coordinates {
            let value = value_of(row, column);
            let name = format!("{}{row}", column_letter(column));
            if seen.insert(name.clone()) {
                values.push((name, value));
            } else if let Some(slot) = values.iter_mut().find(|(n, _)| *n == name) {
                slot.1 = value;
            }
        }
        let numbers: Vec<f64> = values
            .iter()
            .filter_map(|(_, v)| numeric_value(v))
            .collect();
        match rule.kind.as_str() {
            "colorScale" if rule.color_scale.is_some() => {
                let (cfvo, colors) = rule.color_scale.as_ref().expect("checked");
                apply_color_scale(cfvo, colors, &values, &numbers, &mut result);
                continue;
            }
            "dataBar" if rule.data_bar.is_some() => {
                apply_data_bar(
                    rule.data_bar.as_ref().expect("checked"),
                    &values,
                    &numbers,
                    &mut result,
                );
                continue;
            }
            "iconSet" if rule.icon_set.is_some() => {
                apply_icon_set(
                    rule.icon_set.as_ref().expect("checked"),
                    &values,
                    &numbers,
                    &mut result,
                );
                continue;
            }
            _ => {}
        }
        let matched = matching_cells(rule, &values, &numbers);
        let styles = dxf_styles(rule.dxf.as_ref());
        if styles.is_empty() {
            continue;
        }
        for coordinate in matched {
            let target = result.entry(coordinate).or_default();
            for (name, value) in &styles {
                target.set(name, value.clone());
            }
        }
    }
    result
}

fn matching_cells(rule: &Rule, values: &Values, numbers: &[f64]) -> Vec<String> {
    let kind = rule.kind.as_str();
    let formula = &rule.formula;
    let pick = |f: &dyn Fn(&Value) -> bool| {
        values
            .iter()
            .filter(|(_, v)| f(v))
            .map(|(c, _)| c.clone())
            .collect()
    };
    match kind {
        "cellIs" => pick(&|v| cell_is(rule.operator.as_deref(), v, formula)),
        "containsText" | "notContainsText" | "beginsWith" | "endsWith" => {
            let needle = casefold(&formula_text(formula, rule.text.as_deref()));
            if needle.is_empty() {
                return Vec::new();
            }
            pick(&|v| {
                if v.is_none() {
                    return false;
                }
                let text = casefold(&v.py_str());
                match kind {
                    "containsText" => text.contains(&needle),
                    "notContainsText" => !text.contains(&needle),
                    "beginsWith" => text.starts_with(&needle),
                    _ => text.ends_with(&needle),
                }
            })
        }
        "containsBlanks" | "notContainsBlanks" => {
            let blank = kind == "containsBlanks";
            pick(&|v| (v.is_none() || py_strip(&v.py_str()).is_empty()) == blank)
        }
        "top10" if !numbers.is_empty() => {
            let rank = rule.rank.unwrap_or(10);
            let count = if rule.percent {
                ((numbers.len() as f64 * rank as f64 / 100.0).floor() as i64).max(1)
            } else {
                rank
            };
            let mut ordered = numbers.to_vec();
            ordered.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            if !rule.bottom {
                ordered.reverse();
            }
            let index = count.min(ordered.len() as i64) - 1;
            // Python indexes from the end for negative positions.
            let index = if index < 0 {
                (ordered.len() as i64 + index).max(0)
            } else {
                index
            } as usize;
            let cutoff = ordered[index];
            pick(&|v| {
                numeric_value(v).is_some_and(|n| {
                    if rule.bottom {
                        n <= cutoff
                    } else {
                        n >= cutoff
                    }
                })
            })
        }
        "aboveAverage" if !numbers.is_empty() => {
            let mean = numbers.iter().sum::<f64>() / numbers.len() as f64;
            let mean = {
                // Python sum(): compensated.
                super::value::py_sum(numbers).py_float().unwrap_or(mean) / numbers.len() as f64
            };
            let above = rule.above_average != Some(false);
            let inclusive = rule.equal_average;
            pick(&|v| {
                numeric_value(v).is_some_and(|n| {
                    (inclusive && n == mean) || if above { n > mean } else { n < mean }
                })
            })
        }
        "duplicateValues" | "uniqueValues" => {
            let mut counts: HashMap<String, usize> = HashMap::new();
            for (_, v) in values {
                if !v.is_blank() {
                    *counts.entry(v.py_str()).or_default() += 1;
                }
            }
            let duplicate = kind == "duplicateValues";
            pick(&|v| {
                !v.is_blank() && (counts.get(&v.py_str()).copied().unwrap_or(0) > 1) == duplicate
            })
        }
        _ => Vec::new(),
    }
}

fn apply_color_scale(
    cfvo: &[Cfvo],
    colors: &[Color],
    values: &Values,
    numbers: &[f64],
    result: &mut HashMap<String, CellFormat>,
) {
    let colors: Vec<String> = colors
        .iter()
        .map(|c| color_css(Some(c)).unwrap_or_else(|| "#ffffff".into()))
        .collect();
    if colors.len() < 2 || numbers.is_empty() {
        return;
    }
    let stops: Vec<f64> = cfvo
        .iter()
        .take(colors.len())
        .map(|c| threshold(Some(c), numbers, numbers[0]))
        .collect();
    if stops.is_empty() {
        return;
    }
    for (coordinate, value) in values {
        let Some(number) = numeric_value(value) else {
            continue;
        };
        let color = if stops.len() == 3 && colors.len() >= 3 {
            if number <= stops[1] {
                let span = stops[1] - stops[0];
                mix(
                    &colors[0],
                    &colors[1],
                    if span != 0.0 {
                        (number - stops[0]) / span
                    } else {
                        0.0
                    },
                )
            } else {
                let span = stops[2] - stops[1];
                mix(
                    &colors[1],
                    &colors[2],
                    if span != 0.0 {
                        (number - stops[1]) / span
                    } else {
                        1.0
                    },
                )
            }
        } else {
            let span = stops[stops.len() - 1] - stops[0];
            mix(
                &colors[0],
                &colors[colors.len() - 1],
                if span != 0.0 {
                    (number - stops[0]) / span
                } else {
                    1.0
                },
            )
        };
        result
            .entry(coordinate.clone())
            .or_default()
            .set("background", color);
    }
}

fn apply_data_bar(
    bar: &DataBar,
    values: &Values,
    numbers: &[f64],
    result: &mut HashMap<String, CellFormat>,
) {
    if numbers.is_empty() {
        return;
    }
    let low_default = numbers.iter().copied().fold(f64::INFINITY, f64::min);
    let high_default = numbers.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let low = if bar.cfvo.is_empty() {
        low_default
    } else {
        threshold(bar.cfvo.first(), numbers, low_default)
    };
    let high = if bar.cfvo.len() > 1 {
        threshold(bar.cfvo.get(1), numbers, high_default)
    } else {
        high_default
    };
    let color = color_css(bar.color.as_ref()).unwrap_or_else(|| "#638ec6".into());
    let minimum = bar.min_length.unwrap_or(10) as f64;
    let maximum = bar.max_length.unwrap_or(90) as f64;
    for (coordinate, value) in values {
        let Some(number) = numeric_value(value) else {
            continue;
        };
        let ratio = if high > low {
            (number - low) / (high - low)
        } else {
            1.0
        };
        let length = minimum + (maximum - minimum) * ratio.clamp(0.0, 1.0);
        let target = result.entry(coordinate.clone()).or_default();
        target.set(
            "background",
            format!(
                "linear-gradient(90deg,{color} 0,{color}33 {length:.1}%,transparent {length:.1}%)"
            ),
        );
        if bar.show_value == Some(false) {
            target.hide_value = true;
        }
    }
}

fn apply_icon_set(
    set: &IconSet,
    values: &Values,
    numbers: &[f64],
    result: &mut HashMap<String, CellFormat>,
) {
    let Some(icons) = icon_set(set.name.as_deref().unwrap_or("3TrafficLights1")) else {
        return;
    };
    if numbers.is_empty() {
        return;
    }
    let mut icons: Vec<(&str, &str)> = icons.to_vec();
    if set.reverse {
        icons.reverse();
    }
    let low = numbers.iter().copied().fold(f64::INFINITY, f64::min);
    let thresholds: Vec<f64> = set
        .cfvo
        .iter()
        .take(icons.len())
        .map(|c| threshold(Some(c), numbers, low))
        .collect();
    for (coordinate, value) in values {
        let Some(number) = numeric_value(value) else {
            continue;
        };
        let mut level = 0;
        for (index, t) in thresholds.iter().enumerate() {
            if index > 0 && number >= *t {
                level = index;
            }
        }
        let (color, glyph) = icons[level.min(icons.len() - 1)];
        let target = result.entry(coordinate.clone()).or_default();
        if target.icon.is_empty() {
            target.icon = format!("<span class=\"cf-icon\" style=\"color:{color}\" aria-hidden=\"true\">{glyph}</span>");
        }
        if set.show_value == Some(false) {
            target.hide_value = true;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn markup_compatibility_keeps_fallback_content() {
        let xml = r#"<root xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><a/><mc:AlternateContent><mc:Choice Requires="hs"><choice/></mc:Choice><mc:Fallback><fallback/><second/></mc:Fallback></mc:AlternateContent><z/></root>"#;
        let resolved = resolve_markup_compatibility(xml).unwrap();
        assert!(!resolved.contains("AlternateContent"));
        assert!(!resolved.contains("<choice/>"));
        assert!(resolved.find("<a/>").unwrap() < resolved.find("<fallback/>").unwrap());
        assert!(resolved.find("<second/>").unwrap() < resolved.find("<z/>").unwrap());
        assert!(parse_xml(&resolved).is_ok());
    }

    #[test]
    fn colours_like_v3() {
        let theme = Color {
            kind: ColorKind::Theme(4),
            tint: -0.25,
        };
        assert_eq!(color_css(Some(&theme)).as_deref(), Some("#335693"));
        let rgb = Color {
            kind: ColorKind::Rgb("FFC7CE00".into()),
            tint: 0.0,
        };
        assert_eq!(color_css(Some(&rgb)).as_deref(), Some("#c7ce00"));
        let black = Color::default();
        assert_eq!(color_css(Some(&black)), None);
        assert_eq!(mix("#ffffff", "#63be7b", 0.5), "#b1debd");
    }
}
