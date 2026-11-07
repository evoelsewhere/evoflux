//! DOCX → HTML (v3 `service.py` `_render_docx`).
//!
//! v3 read the document through python-docx; this port reads the same XML and
//! keeps python-docx's semantics where the output depends on them:
//!
//! - the first section is the first `w:sectPr` in document order (a section
//!   break in a paragraph, else the body's);
//! - a paragraph's style is its `w:pStyle` when that names a paragraph style,
//!   else the document's default paragraph style; only the style's *own*
//!   properties count (no `basedOn` inheritance);
//! - `runs` are the paragraph's direct `w:r` children (hyperlink runs are not
//!   runs, but their text is part of the paragraph text);
//! - table rows repeat a cell once per grid column it spans, and a cell that
//!   continues a vertical merge shows the content of the cell it continues;
//! - lengths parse like python-docx's simple types (twips, half-points, or a
//!   universal measure such as `2.5cm`).
//!
//! Where python-docx raised on a malformed value (an unknown alignment, an
//! invalid on/off or colour value, a missing header part), the value is
//! ignored here instead of failing the whole render.

use roxmltree::{Document, Node};

use super::html::{css_font_family, escape, page, parse_xml};
use super::{Package, PreviewError};

const W: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
const R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const WP: &str = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing";

const EMU_PER_INCH: f64 = 914_400.0;
const EMU_PER_POINT: f64 = 12_700.0;
const EMU_PER_TWIP: f64 = 635.0;

const CSS: &str = "
    *{box-sizing:border-box}body{margin:0;padding:32px;background:#e8eaed;
    color:#202124;font-family:Arial,sans-serif}.document{margin:0 auto}
    .document-flow,.document-page{width:var(--page-width);background:#fff;
    box-shadow:0 2px 12px #0002}.document-flow{min-height:var(--page-height);
    padding:var(--margin-top) var(--margin-right) var(--margin-bottom)
    var(--margin-left)}.document-pages{display:flex;flex-direction:column;gap:24px;
    align-items:center}.document-page{height:var(--page-height);position:relative;
    padding:var(--margin-top) var(--margin-right) var(--margin-bottom)
    var(--margin-left);overflow:hidden}.document-page-body{height:100%;overflow:hidden}
    .document-page-header,.document-page-footer{position:absolute;left:var(--margin-left);
    right:var(--margin-right);font-size:9pt;color:#5f6368;overflow:hidden}
    .document-page-header{top:16px;height:calc(var(--margin-top) - 20px)}
    .document-page-footer{bottom:12px;height:calc(var(--margin-bottom) - 16px)}
    .document-header-template,.document-footer-template{display:none}
    h1{font-size:26pt;line-height:1.15;margin:0 0
    18pt}h2{font-size:18pt;margin:20pt 0 8pt}h3{font-size:14pt;margin:16pt 0
    6pt}h4{font-size:12pt;margin:12pt 0 5pt}p{font-size:11pt;line-height:1.5;
    margin:0 0 8pt;white-space:pre-wrap}.list-item{display:grid;
    grid-template-columns:1.4em 1fr;column-gap:.25em;align-items:start;
    margin:0 0 6pt;white-space:pre-wrap}.list-marker{text-align:right;
    font-weight:600}.list-content{min-width:0}
    table{width:100%;border-collapse:collapse;margin:12pt 0 18pt;table-layout:fixed}
    th,td{border:1px solid #c7c7c7;padding:7px 9px;vertical-align:top;overflow-wrap:anywhere}
    th{background:#f1f3f4;text-align:left}td p,th p{margin:0;font-size:10pt}
    .inline-image{display:inline-block;vertical-align:middle}
    ";

/// Render the Word document in `package`.
pub fn render(package: &Package, title: &str) -> Result<String, PreviewError> {
    let document_part = package
        .rel_of_kind("", "officeDocument")
        .filter(|r| !r.external)
        .map(|r| r.target)
        .unwrap_or_else(|| "word/document.xml".to_string());
    let text = package
        .text(&document_part)
        .ok_or_else(|| failed("the document part is missing"))?;
    let document = parse_xml(&text).map_err(|e| failed(&e.to_string()))?;
    let body =
        child(document.root_element(), "body").ok_or_else(|| failed("the document has no body"))?;

    let styles_text = package
        .rel_of_kind(&document_part, "styles")
        .filter(|r| !r.external)
        .and_then(|r| package.text(&r.target));
    let styles_doc = match styles_text.as_deref() {
        Some(text) => Some(parse_xml(text).map_err(|e| failed(&e.to_string()))?),
        None => None,
    };
    let styles = Styles::read(styles_doc.as_ref());

    let section = first_section(body);
    let size = section.and_then(|s| child(s, "pgSz"));
    let margins = section.and_then(|s| child(s, "pgMar"));
    let length =
        |node: Option<Node>, name: &str| node.and_then(|n| w_attr(n, name)).and_then(twips_emu);
    let pixels = |emu: Option<i64>, default_inches: f64| match emu {
        Some(emu) => emu as f64 / EMU_PER_INCH * 96.0,
        None => default_inches * 96.0,
    };
    let page_width = pixels(length(size, "w"), 8.5);
    let page_height = pixels(length(size, "h"), 11.0);
    let margin_top = pixels(length(margins, "top"), 1.0);
    let margin_right = pixels(length(margins, "right"), 1.0);
    let margin_bottom = pixels(length(margins, "bottom"), 1.0);
    let margin_left = pixels(length(margins, "left"), 1.0);

    let mut renderer = Renderer {
        package,
        styles: &styles,
        part: document_part.clone(),
        list_number: 0,
    };
    let mut blocks = String::new();
    for block in body.children().filter(Node::is_element) {
        if is(block, "p") {
            blocks.push_str(&renderer.paragraph(block));
        } else if is(block, "tbl") {
            blocks.push_str(&renderer.table(block));
        }
    }

    let header = section.map_or_else(String::new, |s| {
        renderer.header_footer(s, "headerReference", &document_part)
    });
    let footer = section.map_or_else(String::new, |s| {
        renderer.header_footer(s, "footerReference", &document_part)
    });
    let geometry = format!(
        "--page-width:{page_width:.2}px;--page-height:{page_height:.2}px;\
--margin-top:{margin_top:.2}px;--margin-right:{margin_right:.2}px;\
--margin-bottom:{margin_bottom:.2}px;--margin-left:{margin_left:.2}px"
    );
    Ok(page(
        title,
        &format!(
            "<main class=\"document\" style=\"{geometry}\">\
<div class=\"document-header-template\">{header}</div>\
<div class=\"document-footer-template\">{footer}</div>\
<div class=\"document-flow\" data-preview-item data-preview-label=\"Document\">{blocks}</div></main>"
        ),
        CSS,
    ))
}

fn failed(reason: &str) -> PreviewError {
    PreviewError::failed(format!("Could not render this document: {reason}"))
}

// ── XML helpers ─────────────────────────────────────────────────────────────

fn is(node: Node, name: &str) -> bool {
    node.is_element() && node.tag_name().name() == name && node.tag_name().namespace() == Some(W)
}

fn child<'a, 'input>(node: Node<'a, 'input>, name: &str) -> Option<Node<'a, 'input>> {
    node.children().find(|c| is(*c, name))
}

fn children<'a, 'input: 'a>(
    node: Node<'a, 'input>,
    name: &'a str,
) -> impl Iterator<Item = Node<'a, 'input>> + 'a {
    node.children().filter(move |c| is(*c, name))
}

fn w_attr<'a>(node: Node<'a, '_>, name: &str) -> Option<&'a str> {
    node.attribute((W, name))
}

/// The first `w:sectPr` in document order (python-docx `sections[0]`).
fn first_section<'a, 'input>(body: Node<'a, 'input>) -> Option<Node<'a, 'input>> {
    body.children().find_map(|block| {
        if is(block, "sectPr") {
            Some(block)
        } else if is(block, "p") {
            child(block, "pPr").and_then(|p| child(p, "sectPr"))
        } else {
            None
        }
    })
}

/// `ST_OnOff` on an element's `w:val` (absent means on).
fn on_off(node: Node) -> Option<bool> {
    match w_attr(node, "val") {
        None => Some(true),
        Some("1" | "true" | "on") => Some(true),
        Some("0" | "false" | "off") => Some(false),
        Some(_) => None,
    }
}

fn universal_emu(value: &str) -> Option<i64> {
    if value.len() < 2 || !value.is_char_boundary(value.len() - 2) {
        return None;
    }
    let (quantity, units) = value.split_at(value.len() - 2);
    let multiplier = match units {
        "mm" => 36_000.0,
        "cm" => 360_000.0,
        "in" => 914_400.0,
        "pt" => 12_700.0,
        "pc" | "pi" => 152_400.0,
        _ => return None,
    };
    let quantity: f64 = quantity.trim().parse().ok()?;
    Some((quantity * multiplier).round_ties_even() as i64)
}

/// A (signed) twips measure in EMU (`ST_TwipsMeasure`, `ST_SignedTwipsMeasure`).
fn twips_emu(value: &str) -> Option<i64> {
    if value.contains(['i', 'm', 'p']) {
        return universal_emu(value);
    }
    let twips: f64 = value.trim().parse().ok()?;
    Some((twips.round_ties_even() * EMU_PER_TWIP) as i64)
}

/// A half-point measure in EMU (`ST_HpsMeasure`).
fn half_points_emu(value: &str) -> Option<i64> {
    if value.contains(['m', 'n', 'p']) {
        return universal_emu(value);
    }
    let half_points: i64 = value.trim().parse().ok()?;
    Some((half_points as f64 / 2.0 * EMU_PER_POINT) as i64)
}

fn points(emu: i64) -> String {
    format!("{:.2}", emu as f64 / EMU_PER_POINT)
}

/// `ST_HexColor`: `auto` is no colour; a hex value prints upper-case.
fn hex_color(value: &str) -> Option<String> {
    (value.len() == 6 && value.chars().all(|c| c.is_ascii_hexdigit()))
        .then(|| value.to_ascii_uppercase())
}

// ── properties ──────────────────────────────────────────────────────────────

/// Character properties set directly on a run or a style (`w:rPr`).
#[derive(Debug, Clone, Default)]
struct Font {
    name: Option<String>,
    size: Option<i64>,
    bold: Option<bool>,
    italic: Option<bool>,
    underline: bool,
    color: Option<String>,
}

impl Font {
    fn read(rpr: Option<Node>) -> Self {
        let Some(rpr) = rpr else {
            return Self::default();
        };
        let flag = |name: &str| child(rpr, name).and_then(on_off);
        Self {
            name: child(rpr, "rFonts")
                .and_then(|f| w_attr(f, "ascii"))
                .map(str::to_string),
            size: child(rpr, "sz")
                .and_then(|s| w_attr(s, "val"))
                .and_then(half_points_emu),
            bold: flag("b"),
            italic: flag("i"),
            // `single` and every other style underline; `none` and a `w:u`
            // without a value do not.
            underline: child(rpr, "u")
                .and_then(|u| w_attr(u, "val"))
                .is_some_and(|v| v != "none"),
            color: child(rpr, "color")
                .and_then(|c| w_attr(c, "val"))
                .and_then(hex_color),
        }
    }
}

#[derive(Debug, Clone, Copy)]
enum LineSpacing {
    /// A multiple of single spacing.
    Lines(f64),
    /// An exact or minimum height, in EMU.
    Height(i64),
}

/// Paragraph properties set directly on a paragraph or a style (`w:pPr`).
#[derive(Debug, Clone, Default)]
struct ParagraphFormat {
    alignment: Option<&'static str>,
    space_before: Option<i64>,
    space_after: Option<i64>,
    line_spacing: Option<LineSpacing>,
    left_indent: Option<i64>,
    right_indent: Option<i64>,
    first_line_indent: Option<i64>,
    page_break_before: bool,
}

impl ParagraphFormat {
    fn read(ppr: Option<Node>) -> Self {
        let Some(ppr) = ppr else {
            return Self::default();
        };
        let spacing = child(ppr, "spacing");
        let spacing_length = |name: &str| spacing.and_then(|s| w_attr(s, name)).and_then(twips_emu);
        let line = spacing_length("line");
        let rule = spacing.and_then(|s| w_attr(s, "lineRule"));
        let line_spacing = line.and_then(|line| match rule {
            None | Some("auto") => Some(LineSpacing::Lines(line as f64 / (12.0 * EMU_PER_POINT))),
            Some("exact" | "atLeast") => Some(LineSpacing::Height(line)),
            Some(_) => None,
        });
        let ind = child(ppr, "ind");
        let ind_length = |name: &str| ind.and_then(|i| w_attr(i, name)).and_then(twips_emu);
        let first_line_indent = match ind_length("hanging") {
            Some(hanging) => Some(-hanging),
            None => ind_length("firstLine"),
        };
        Self {
            alignment: child(ppr, "jc")
                .and_then(|j| w_attr(j, "val"))
                .and_then(|v| match v {
                    "center" => Some("center"),
                    "right" => Some("right"),
                    "both" | "distribute" => Some("justify"),
                    _ => None,
                }),
            space_before: spacing_length("before"),
            space_after: spacing_length("after"),
            line_spacing,
            left_indent: ind_length("left"),
            right_indent: ind_length("right"),
            first_line_indent,
            page_break_before: child(ppr, "pageBreakBefore")
                .and_then(on_off)
                .unwrap_or(false),
        }
    }
}

#[derive(Debug, Clone, Default)]
struct Style {
    id: String,
    kind: String,
    name: Option<String>,
    is_default: bool,
    font: Font,
    format: ParagraphFormat,
}

/// The styles part (`word/styles.xml`).
#[derive(Debug, Default)]
struct Styles {
    styles: Vec<Style>,
}

impl Styles {
    fn read(document: Option<&Document>) -> Self {
        let Some(document) = document else {
            return Self::default();
        };
        let styles = children(document.root_element(), "style")
            .map(|style| Style {
                id: w_attr(style, "styleId").unwrap_or_default().to_string(),
                kind: w_attr(style, "type").unwrap_or("paragraph").to_string(),
                name: child(style, "name")
                    .and_then(|n| w_attr(n, "val"))
                    .map(str::to_string),
                is_default: matches!(w_attr(style, "default"), Some("1" | "true" | "on")),
                font: Font::read(child(style, "rPr")),
                format: ParagraphFormat::read(child(style, "pPr")),
            })
            .collect();
        Self { styles }
    }

    /// python-docx `Paragraph.style`: the named paragraph style, else the last
    /// default paragraph style.
    fn paragraph_style(&self, id: Option<&str>) -> Option<&Style> {
        if let Some(id) = id {
            if let Some(style) = self.styles.iter().find(|s| s.id == id) {
                if style.kind == "paragraph" {
                    return Some(style);
                }
            }
        }
        self.styles
            .iter()
            .rev()
            .find(|s| s.kind == "paragraph" && s.is_default)
    }
}

// ── text ────────────────────────────────────────────────────────────────────

/// python-docx `Run.text`.
fn run_text(run: Node) -> String {
    let mut text = String::new();
    for item in run
        .children()
        .filter(|c| c.is_element() && c.tag_name().namespace() == Some(W))
    {
        match item.tag_name().name() {
            "br" => {
                if w_attr(item, "type").unwrap_or("textWrapping") == "textWrapping" {
                    text.push('\n');
                }
            }
            "cr" => text.push('\n'),
            "noBreakHyphen" => text.push('-'),
            "ptab" | "tab" => text.push('\t'),
            "t" => text.push_str(item.text().unwrap_or_default()),
            _ => {}
        }
    }
    text
}

/// python-docx `Paragraph.text`: runs and hyperlink runs.
fn paragraph_text(paragraph: Node) -> String {
    let mut text = String::new();
    for item in paragraph.children() {
        if is(item, "r") {
            text.push_str(&run_text(item));
        } else if is(item, "hyperlink") {
            for run in children(item, "r") {
                text.push_str(&run_text(run));
            }
        }
    }
    text
}

// ── rendering ───────────────────────────────────────────────────────────────

struct Renderer<'a> {
    package: &'a Package,
    styles: &'a Styles,
    /// The part whose relationships resolve images (document, header, footer).
    part: String,
    list_number: u64,
}

impl Renderer<'_> {
    fn paragraph(&mut self, paragraph: Node) -> String {
        let ppr = child(paragraph, "pPr");
        let style = self.styles.paragraph_style(
            ppr.and_then(|p| child(p, "pStyle"))
                .and_then(|s| w_attr(s, "val")),
        );
        let style_name = style
            .and_then(|s| s.name.as_deref())
            .unwrap_or_default()
            .to_lowercase();
        let mut tag = "p";
        if style_name == "title" {
            tag = "h1";
        }
        for (level, heading) in [(1, "h2"), (2, "h3"), (3, "h4")] {
            if style_name.starts_with(&format!("heading {level}")) {
                tag = heading;
                break;
            }
        }
        let is_numbered = style_name.starts_with("list number");
        let is_bullet = style_name.starts_with("list bullet");
        if is_numbered {
            self.list_number += 1;
        } else if !is_bullet {
            self.list_number = 0;
        }

        let mut runs = String::new();
        for run in children(paragraph, "r") {
            runs.push_str(&self.run(run));
        }
        let text = paragraph_text(paragraph);
        let mut content = if runs.is_empty() { escape(&text) } else { runs };
        if content.is_empty() {
            content = "&nbsp;".to_string();
        }

        let mut styles: Vec<String> = Vec::new();
        if let Some(style) = style {
            if let Some(name) = style.font.name.as_deref().filter(|n| !n.is_empty()) {
                styles.push(format!("font-family:{}", css_font_family(name)));
            }
            if let Some(size) = style.font.size.filter(|s| *s != 0) {
                styles.push(format!("font-size:{}pt", points(size)));
            }
            if style.font.bold == Some(true) {
                styles.push("font-weight:700".to_string());
            }
            if let Some(color) = &style.font.color {
                styles.push(format!("color:#{color}"));
            }
        }
        let format = ParagraphFormat::read(ppr);
        let style_format = style.map(|s| &s.format);
        if let Some(alignment) = format.alignment {
            styles.push(format!("text-align:{alignment}"));
        }
        // python-docx lengths are ints: a zero is "unset" for `or`.
        let nonzero = |v: Option<i64>| v.filter(|v| *v != 0);
        let space_before = nonzero(format.space_before)
            .or_else(|| style_format.and_then(|f| nonzero(f.space_before)));
        let space_after = nonzero(format.space_after)
            .or_else(|| style_format.and_then(|f| nonzero(f.space_after)));
        let set_spacing = |v: Option<LineSpacing>| {
            v.filter(|s| match s {
                LineSpacing::Lines(lines) => *lines != 0.0,
                LineSpacing::Height(height) => *height != 0,
            })
        };
        let line_spacing = set_spacing(format.line_spacing)
            .or_else(|| style_format.and_then(|f| set_spacing(f.line_spacing)));
        if let Some(before) = space_before {
            styles.push(format!("margin-top:{}pt", points(before)));
        }
        if let Some(after) = space_after {
            styles.push(format!("margin-bottom:{}pt", points(after)));
        }
        match line_spacing {
            Some(LineSpacing::Lines(lines)) => styles.push(format!("line-height:{lines:.3}")),
            Some(LineSpacing::Height(height)) => {
                styles.push(format!("line-height:{}pt", points(height)));
            }
            None => {}
        }
        if let Some(left) = nonzero(format.left_indent) {
            styles.push(format!("margin-left:{}pt", points(left)));
        }
        if let Some(right) = nonzero(format.right_indent) {
            styles.push(format!("margin-right:{}pt", points(right)));
        }
        if let Some(first) = nonzero(format.first_line_indent) {
            styles.push(format!("text-indent:{}pt", points(first)));
        }
        let style_attr = if styles.is_empty() {
            String::new()
        } else {
            format!(" style=\"{}\"", styles.join(";"))
        };
        let page_break_before = format.page_break_before
            || paragraph
                .descendants()
                .any(|n| is(n, "br") && w_attr(n, "type") == Some("page"));
        let page_break = if page_break_before { "true" } else { "false" };
        let label = escape(&text.chars().take(80).collect::<String>());
        if is_numbered || is_bullet {
            let marker = if is_numbered {
                format!("{}.", self.list_number)
            } else {
                "•".to_string()
            };
            return format!(
                "<div class=\"list-item\"{style_attr} data-page-break-before=\"{page_break}\" \
data-qa-label=\"{label}\"><span class=\"list-marker\">{marker}</span>\
<span class=\"list-content\">{content}</span></div>"
            );
        }
        format!(
            "<{tag}{style_attr} data-page-break-before=\"{page_break}\" data-qa-label=\"{label}\">{content}</{tag}>"
        )
    }

    fn run(&self, run: Node) -> String {
        let font = Font::read(child(run, "rPr"));
        let mut styles: Vec<String> = Vec::new();
        if font.bold == Some(true) {
            styles.push("font-weight:700".to_string());
        }
        if font.italic == Some(true) {
            styles.push("font-style:italic".to_string());
        }
        if font.underline {
            styles.push("text-decoration:underline".to_string());
        }
        if let Some(size) = font.size.filter(|s| *s != 0) {
            styles.push(format!("font-size:{}pt", points(size)));
        }
        if let Some(name) = font.name.as_deref().filter(|n| !n.is_empty()) {
            styles.push(format!("font-family:{}", css_font_family(name)));
        }
        if let Some(color) = &font.color {
            styles.push(format!("color:#{color}"));
        }
        let text = escape(&run_text(run)).replace('\n', "<br>");
        let style_attr = if styles.is_empty() {
            String::new()
        } else {
            format!(" style=\"{}\"", styles.join(";"))
        };
        let mut html = format!("<span{style_attr}>{text}</span>");

        let extent = run.descendants().find(|n| {
            n.is_element()
                && n.tag_name().name() == "extent"
                && n.tag_name().namespace() == Some(WP)
        });
        for blip in run.descendants().filter(|n| {
            n.is_element() && n.tag_name().name() == "blip" && n.tag_name().namespace() == Some(A)
        }) {
            let Some(relation) = blip
                .attribute((R, "embed"))
                .and_then(|id| self.package.rel(&self.part, id))
                .filter(|r| !r.external)
            else {
                continue;
            };
            let Some(bytes) = self.package.bytes(&relation.target) else {
                continue;
            };
            let content_type = self
                .package
                .content_type(&relation.target)
                .unwrap_or_else(|| "image/png".to_string());
            let encoded = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, bytes);
            let mut image_styles = vec!["max-width:100%".to_string(), "height:auto".to_string()];
            if let Some(extent) = extent {
                let cx: i64 = extent
                    .attribute("cx")
                    .unwrap_or("0")
                    .trim()
                    .parse()
                    .unwrap_or(0);
                let width_px = cx as f64 / EMU_PER_INCH * 96.0;
                if width_px > 0.0 {
                    image_styles.push(format!("width:{width_px:.2}px"));
                }
            }
            html.push_str(&format!(
                "<img class=\"inline-image\" style=\"{}\" src=\"data:{content_type};base64,{encoded}\" alt=\"\">",
                image_styles.join(";")
            ));
        }
        html
    }

    fn table(&mut self, table: Node) -> String {
        let rows: Vec<Node> = children(table, "tr").collect();
        let mut html = String::from("<table>");
        for row_index in 0..rows.len() {
            let cell_tag = if row_index == 0 { "th" } else { "td" };
            html.push_str("<tr>");
            for cell in row_cells(&rows, row_index) {
                let body: String = children(cell, "p").map(|p| self.paragraph(p)).collect();
                html.push_str(&format!("<{cell_tag}>{body}</{cell_tag}>"));
            }
            html.push_str("</tr>");
        }
        html.push_str("</table>");
        html
    }

    /// The default header or footer of the first section (python-docx renders
    /// the definition, or nothing: the first section inherits from no one).
    fn header_footer(&mut self, section: Node, reference: &str, document_part: &str) -> String {
        let Some(target) = children(section, reference)
            .find(|r| w_attr(*r, "type") == Some("default"))
            .and_then(|r| r.attribute((R, "id")))
            .and_then(|id| self.package.rel(document_part, id))
            .filter(|r| !r.external)
            .map(|r| r.target)
        else {
            return String::new();
        };
        let Some(text) = self.package.text(&target) else {
            return String::new();
        };
        let Ok(part) = parse_xml(&text) else {
            return String::new();
        };
        let previous = std::mem::replace(&mut self.part, target);
        let html = children(part.root_element(), "p")
            .map(|p| self.paragraph(p))
            .collect();
        self.part = previous;
        html
    }
}

fn grid_before(row: Node) -> usize {
    child(row, "trPr")
        .and_then(|p| child(p, "gridBefore"))
        .and_then(|g| w_attr(g, "val"))
        .and_then(|v| v.trim().parse().ok())
        .unwrap_or(0)
}

fn grid_span(cell: Node) -> usize {
    child(cell, "tcPr")
        .and_then(|p| child(p, "gridSpan"))
        .and_then(|g| w_attr(g, "val"))
        .and_then(|v| v.trim().parse().ok())
        .unwrap_or(1)
}

fn continues_vertical_merge(cell: Node) -> bool {
    child(cell, "tcPr")
        .and_then(|p| child(p, "vMerge"))
        .is_some_and(|m| w_attr(m, "val").unwrap_or("continue") == "continue")
}

/// python-docx `_Row.cells`: one entry per grid column a cell spans; a cell
/// continuing a vertical merge stands for the cell above it.
fn row_cells<'a, 'input>(rows: &[Node<'a, 'input>], row_index: usize) -> Vec<Node<'a, 'input>> {
    let row = rows[row_index];
    let mut cells = Vec::new();
    let mut offset = grid_before(row);
    for cell in children(row, "tc") {
        let span = grid_span(cell);
        if continues_vertical_merge(cell) {
            if let Some(root) = merge_root(rows, row_index, offset) {
                cells.extend(std::iter::repeat_n(root, grid_span(root)));
            }
        } else {
            cells.extend(std::iter::repeat_n(cell, span));
        }
        offset += span;
    }
    cells
}

/// The cell holding the content of a vertical merge that reaches grid column
/// `offset` of row `row_index`.
fn merge_root<'a, 'input>(
    rows: &[Node<'a, 'input>],
    row_index: usize,
    offset: usize,
) -> Option<Node<'a, 'input>> {
    let mut row_index = row_index;
    loop {
        row_index = row_index.checked_sub(1)?;
        let above = cell_at_grid_offset(rows[row_index], offset)?;
        if !continues_vertical_merge(above) {
            return Some(above);
        }
    }
}

fn cell_at_grid_offset<'a, 'input>(
    row: Node<'a, 'input>,
    offset: usize,
) -> Option<Node<'a, 'input>> {
    let mut remaining = offset as i64 - grid_before(row) as i64;
    for cell in children(row, "tc") {
        if remaining < 0 {
            break;
        }
        if remaining == 0 {
            return Some(cell);
        }
        remaining -= grid_span(cell) as i64;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn measures_parse_like_python_docx() {
        assert_eq!(twips_emu("1440"), Some(914_400));
        assert_eq!(twips_emu("2.54cm"), Some(914_400));
        assert_eq!(twips_emu("-720"), Some(-457_200));
        assert_eq!(half_points_emu("31"), Some(196_850));
        assert_eq!(half_points_emu("12pt"), Some(152_400));
        assert_eq!(hex_color("ff0011").as_deref(), Some("FF0011"));
        assert_eq!(hex_color("auto"), None);
    }
}
