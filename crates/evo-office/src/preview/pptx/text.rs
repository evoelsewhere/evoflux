//! Text frames: paragraph/run styles resolved through the placeholder and
//! master text-style chain, bullets and numbering (v3 `_effective_*`,
//! `_paragraph_runs_html`, `_bullet_marker_styles`, `_shape_text`).

use std::collections::{BTreeMap, HashMap};

use super::super::html::{css_font_family, escape};
use super::color::{drawing_color, solid_fill_color, Palette};
use super::model::{matching_placeholder, ph_type, Shape, SlideCtx};
use super::util::{
    child, cqw, elements, f, first_child, local, own_text, pt_cqw, py_int, py_round, xml_bool, Nd,
    R,
};

/// What run and paragraph styling needs from the slide.
pub(super) struct TextEnv<'c> {
    pub palette: &'c Palette,
    pub fonts: &'c HashMap<String, String>,
    pub slide_width: i64,
}

impl<'c> TextEnv<'c> {
    pub fn of(ctx: &'c SlideCtx<'_>) -> Self {
        Self {
            palette: &ctx.palette,
            fonts: &ctx.fonts,
            slide_width: ctx.slide_width,
        }
    }
}

/// `paragraph.level` (`a:pPr/@lvl`; python-pptx does not range-check it on
/// read, lookups clamp it to 0–8).
pub(super) fn paragraph_level(paragraph: Nd<'_>) -> R<i64> {
    match child(paragraph, "pPr").and_then(|p| p.attribute("lvl")) {
        None => Ok(0),
        // Fix over v3 (raised, lost the shape): an unreadable level is 0.
        Some(raw) => Ok(py_int(raw).unwrap_or(0)),
    }
}

/// v3 `_level_properties`.
pub(super) fn level_properties<'a>(list_style: Option<Nd<'a>>, level: i64) -> Option<Nd<'a>> {
    let list_style = list_style?;
    let name = format!("lvl{}pPr", level.clamp(0, 8) + 1);
    child(list_style, &name).or_else(|| child(list_style, "defPPr"))
}

/// The `a:p` children of a text body.
pub(super) fn paragraphs<'a>(tx_body: Option<Nd<'a>>) -> Vec<Nd<'a>> {
    tx_body
        .map(|b| elements(b).filter(|e| local(*e) == "p").collect())
        .unwrap_or_default()
}

/// The text body of a layout/master placeholder. Fix over v3: a matching
/// placeholder that is not an autoshape (a picture or graphic frame) has no
/// text frame; v3 raised and lost the slide shape, here it adds nothing.
fn placeholder_body<'a>(placeholder: &Shape<'a>) -> Option<Nd<'a>> {
    placeholder.tx_body().ok().flatten()
}

/// The `a:lstStyle` of a text body. Fix over v3: v3 read `txBody.lstStyle`,
/// an attribute python-pptx's `CT_TextBody` does not define, so list styles
/// (shape, layout and master placeholders, table cells) never applied.
pub(super) fn list_style(tx_body: Option<Nd<'_>>) -> Option<Nd<'_>> {
    tx_body.and_then(|b| child(b, "lstStyle"))
}

/// v3 `_placeholder_paragraph_properties`.
fn placeholder_paragraph_properties<'a>(placeholder: &Shape<'a>, level: i64) -> R<Option<Nd<'a>>> {
    let Ok(tx_body) = placeholder.tx_body() else {
        return Ok(None);
    };
    let mut fallback = None;
    for paragraph in paragraphs(tx_body) {
        let Some(properties) = child(paragraph, "pPr") else {
            continue;
        };
        if fallback.is_none() {
            fallback = Some(properties);
        }
        if paragraph_level(paragraph)? == level {
            return Ok(Some(properties));
        }
    }
    Ok(fallback)
}

/// `_placeholder_style_name`: the master `txStyles` entry for the shape.
fn placeholder_style_name(shape: &Shape<'_>) -> &'static str {
    let Some(ph) = shape.ph() else {
        return "otherStyle";
    };
    let Ok(name) = ph_type(ph) else {
        return "otherStyle";
    };
    // Fix over v3: v3 matched `"TITLE" in name`, which sent subtitles to the
    // title style; a subtitle inherits the body style.
    if matches!(name, "TITLE" | "CENTER_TITLE") {
        "titleStyle"
    } else if matches!(name, "BODY" | "OBJECT" | "SUBTITLE") {
        "bodyStyle"
    } else {
        "otherStyle"
    }
}

/// v3 `_effective_paragraph_nodes`: most to least specific.
pub(super) fn effective_paragraph_nodes<'a>(
    ctx: &SlideCtx<'a>,
    shape: &Shape<'a>,
    paragraph: Nd<'a>,
) -> R<Vec<Nd<'a>>> {
    let level = paragraph_level(paragraph)?;
    let mut result = Vec::new();
    if let Some(direct) = child(paragraph, "pPr") {
        result.push(direct);
    }
    if let Some(props) = level_properties(list_style(shape.tx_body()?), level) {
        result.push(props);
    }
    let layout_placeholder = matching_placeholder(ctx.layout_root, ctx.layout_part, shape, true);
    let mut master_placeholder = None;
    if let Some(layout_placeholder) = layout_placeholder {
        if let Some(props) = placeholder_paragraph_properties(&layout_placeholder, level)? {
            result.push(props);
        }
        if let Some(props) =
            level_properties(list_style(placeholder_body(&layout_placeholder)), level)
        {
            result.push(props);
        }
        master_placeholder =
            matching_placeholder(ctx.master_root, ctx.master_part, &layout_placeholder, false);
    } else if shape.is_placeholder() {
        master_placeholder = matching_placeholder(ctx.master_root, ctx.master_part, shape, false);
    }
    if let Some(master_placeholder) = master_placeholder {
        if let Some(props) = placeholder_paragraph_properties(&master_placeholder, level)? {
            result.push(props);
        }
        if let Some(props) =
            level_properties(list_style(placeholder_body(&master_placeholder)), level)
        {
            result.push(props);
        }
    }
    if let Some(styles) = child(ctx.master_root, "txStyles") {
        if let Some(style) = child(styles, placeholder_style_name(shape)) {
            if let Some(props) = level_properties(Some(style), level) {
                result.push(props);
            }
        }
    }
    Ok(result)
}

/// v3 `_effective_body_nodes`.
pub(super) fn effective_body_nodes<'a>(ctx: &SlideCtx<'a>, shape: &Shape<'a>) -> R<Vec<Nd<'a>>> {
    let mut result = Vec::new();
    if let Some(direct) = shape.tx_body()?.and_then(|b| child(b, "bodyPr")) {
        result.push(direct);
    }
    let layout_placeholder = matching_placeholder(ctx.layout_root, ctx.layout_part, shape, true);
    let mut master_placeholder = None;
    if let Some(layout_placeholder) = layout_placeholder {
        if let Some(body) = placeholder_body(&layout_placeholder).and_then(|b| child(b, "bodyPr")) {
            result.push(body);
        }
        master_placeholder =
            matching_placeholder(ctx.master_root, ctx.master_part, &layout_placeholder, false);
    } else if shape.is_placeholder() {
        master_placeholder = matching_placeholder(ctx.master_root, ctx.master_part, shape, false);
    }
    if let Some(master_placeholder) = master_placeholder {
        if let Some(body) = placeholder_body(&master_placeholder).and_then(|b| child(b, "bodyPr")) {
            result.push(body);
        }
    }
    Ok(result)
}

pub(super) fn first_attribute<'a>(nodes: &[Nd<'a>], name: &str) -> Option<&'a str> {
    nodes.iter().find_map(|n| n.attribute(name))
}

fn run_property_nodes<'a>(
    run_properties: Option<Nd<'a>>,
    paragraph_nodes: &[Nd<'a>],
) -> Vec<Nd<'a>> {
    let mut result: Vec<Nd<'a>> = run_properties.into_iter().collect();
    result.extend(paragraph_nodes.iter().filter_map(|p| child(*p, "defRPr")));
    result
}

/// v3 `_theme_font_name`.
pub(super) fn theme_font_name(typeface: &str, fonts: &HashMap<String, String>) -> String {
    let key = match typeface {
        "+mj-lt" => "major-latin",
        "+mj-ea" => "major-east-asian",
        "+mj-cs" => "major-complex",
        "+mn-lt" => "minor-latin",
        "+mn-ea" => "minor-east-asian",
        "+mn-cs" => "minor-complex",
        _ => "",
    };
    fonts
        .get(key)
        .filter(|v| !v.is_empty())
        .cloned()
        .unwrap_or_else(|| typeface.to_string())
}

/// v3 `_effective_run_styles`.
pub(super) fn effective_run_styles(
    run_properties: Option<Nd<'_>>,
    paragraph_nodes: &[Nd<'_>],
    env: &TextEnv<'_>,
    default_size_pt: f64,
) -> R<(Vec<String>, f64)> {
    let nodes = run_property_nodes(run_properties, paragraph_nodes);
    let size_pt = match first_attribute(&nodes, "sz") {
        Some(raw) => py_int(raw)
            .map(|v| v as f64 / 100.0)
            .unwrap_or(default_size_pt),
        None => default_size_pt,
    };
    let mut styles = vec![format!("font-size:{}", pt_cqw(size_pt, env.slide_width))];

    let mut typeface = String::new();
    for node in &nodes {
        if let Some(face) = child(*node, "latin")
            .and_then(|l| l.attribute("typeface"))
            .filter(|t| !t.is_empty())
        {
            typeface = theme_font_name(face, env.fonts);
            break;
        }
    }
    if typeface.is_empty() {
        typeface = env
            .fonts
            .get("minor-latin")
            .cloned()
            .unwrap_or_else(|| "Arial".into());
    }
    styles.push(format!("font-family:{}", css_font_family(&typeface)));

    let bold = xml_bool(first_attribute(&nodes, "b"));
    let italic = xml_bool(first_attribute(&nodes, "i"));
    let underline = first_attribute(&nodes, "u");
    let strike = first_attribute(&nodes, "strike");
    if let Some(bold) = bold {
        styles.push(
            if bold {
                "font-weight:700"
            } else {
                "font-weight:400"
            }
            .into(),
        );
    }
    if let Some(italic) = italic {
        styles.push(
            if italic {
                "font-style:italic"
            } else {
                "font-style:normal"
            }
            .into(),
        );
    }
    let mut decorations = Vec::new();
    if underline.is_some_and(|u| !u.is_empty() && !matches!(u, "none" | "0" | "false")) {
        decorations.push("underline");
    }
    if strike.is_some_and(|s| !s.is_empty() && !matches!(s, "noStrike" | "none" | "0" | "false")) {
        decorations.push("line-through");
    }
    if !decorations.is_empty() {
        styles.push(format!("text-decoration-line:{}", decorations.join(" ")));
        if strike == Some("dblStrike") {
            styles.push("text-decoration-style:double".into());
        }
    } else if underline.is_some() || strike.is_some() {
        styles.push("text-decoration:none".into());
    }
    match first_attribute(&nodes, "cap") {
        Some("all") => styles.push("text-transform:uppercase".into()),
        Some("small") => styles.push("font-variant:small-caps".into()),
        _ => {}
    }
    if let Some(raw) = first_attribute(&nodes, "baseline") {
        let baseline = py_int(raw).unwrap_or(0);
        if baseline != 0 {
            styles.push(
                if baseline > 0 {
                    "vertical-align:super"
                } else {
                    "vertical-align:sub"
                }
                .into(),
            );
        }
    }
    if let Some(spacing) = first_attribute(&nodes, "spc").and_then(py_int) {
        styles.push(format!(
            "letter-spacing:{}",
            pt_cqw(spacing as f64 / 100.0, env.slide_width)
        ));
    }
    for node in &nodes {
        if let Some(color) = solid_fill_color(Some(*node), env.palette)? {
            styles.push(format!("color:{color}"));
            break;
        }
    }
    for node in &nodes {
        let Some(highlight) = child(*node, "highlight") else {
            continue;
        };
        if let Some(color) = drawing_color(first_child(Some(highlight)), env.palette)? {
            styles.push(format!("background-color:{color}"));
            break;
        }
    }
    Ok((styles, size_pt))
}

/// v3 `_spacing_css`.
pub(super) fn spacing_css(
    paragraph_nodes: &[Nd<'_>],
    element: &str,
    slide_width: i64,
) -> Option<String> {
    for properties in paragraph_nodes {
        let Some(container) = child(*properties, element) else {
            continue;
        };
        if let Some(points) = child(container, "spcPts") {
            return py_int(points.attribute("val").unwrap_or("0"))
                .map(|v| pt_cqw(v as f64 / 100.0, slide_width));
        }
        if let Some(percent) = child(container, "spcPct") {
            return py_int(percent.attribute("val").unwrap_or("0"))
                .map(|v| format!("{}em", f(v as f64 / 100000.0, 4)));
        }
    }
    None
}

/// v3 `_number_marker`.
pub(super) fn number_marker(format: &str, value: i64) -> String {
    fn alpha(mut index: i64) -> String {
        let mut result = String::new();
        while index > 0 {
            index -= 1;
            result.insert(0, (b'A' + (index % 26) as u8) as char);
            index /= 26;
        }
        result
    }
    fn roman(mut index: i64) -> String {
        const VALUES: [(i64, &str); 13] = [
            (1000, "M"),
            (900, "CM"),
            (500, "D"),
            (400, "CD"),
            (100, "C"),
            (90, "XC"),
            (50, "L"),
            (40, "XL"),
            (10, "X"),
            (9, "IX"),
            (5, "V"),
            (4, "IV"),
            (1, "I"),
        ];
        let mut result = String::new();
        for (amount, token) in VALUES {
            while index >= amount {
                result.push_str(token);
                index -= amount;
            }
        }
        result
    }
    // A hostile start value must not build a megabyte roman numeral.
    let huge = value > 1_000_000;
    let mut marker = if format.starts_with("alpha") {
        alpha(value)
    } else if format.starts_with("roman") && !huge {
        roman(value)
    } else {
        value.to_string()
    };
    if (format.starts_with("alpha") || format.starts_with("roman")) && format.contains("Lc") {
        marker = marker.to_lowercase();
    }
    if format.ends_with("ParenBoth") {
        format!("({marker})")
    } else if format.ends_with("ParenR") {
        format!("{marker})")
    } else if format.ends_with("Period") {
        format!("{marker}.")
    } else {
        marker
    }
}

/// v3 `_effective_bullet`.
pub(super) fn effective_bullet(
    paragraph_nodes: &[Nd<'_>],
    counters: &mut BTreeMap<i64, i64>,
    level: i64,
) -> String {
    for properties in paragraph_nodes {
        for item in elements(*properties) {
            match local(item) {
                "buNone" => return String::new(),
                "buChar" => {
                    return item
                        .attribute("char")
                        .filter(|c| !c.is_empty())
                        .unwrap_or("\u{2022}")
                        .to_string()
                }
                "buAutoNum" => {
                    if let Some(start) = item.attribute("startAt").and_then(py_int) {
                        counters.insert(level, start);
                    }
                    let value = counters.get(&level).copied().unwrap_or(1);
                    counters.insert(level, value.saturating_add(1));
                    let format = item
                        .attribute("type")
                        .filter(|t| !t.is_empty())
                        .unwrap_or("arabicPeriod");
                    return number_marker(format, value);
                }
                _ => {}
            }
        }
    }
    String::new()
}

/// v3 `_first_run_properties`.
fn first_run_properties(paragraph: Nd<'_>) -> Option<Nd<'_>> {
    let run = elements(paragraph).find(|c| matches!(local(*c), "r" | "fld"))?;
    child(run, "rPr")
}

/// v3 `_bullet_marker_styles`.
pub(super) fn bullet_marker_styles(
    paragraph: Nd<'_>,
    paragraph_nodes: &[Nd<'_>],
    env: &TextEnv<'_>,
) -> R<(Vec<String>, f64)> {
    let (mut styles, mut size_pt) =
        effective_run_styles(first_run_properties(paragraph), paragraph_nodes, env, 18.0)?;
    for properties in paragraph_nodes {
        let Some(font) = elements(*properties).find(|c| matches!(local(*c), "buFont" | "buFontTx"))
        else {
            continue;
        };
        if local(font) == "buFont" {
            if let Some(face) = font.attribute("typeface").filter(|t| !t.is_empty()) {
                styles.push(format!(
                    "font-family:{}",
                    css_font_family(&theme_font_name(face, env.fonts))
                ));
            }
        }
        break;
    }
    for properties in paragraph_nodes {
        let Some(color) = elements(*properties).find(|c| matches!(local(*c), "buClr" | "buClrTx"))
        else {
            continue;
        };
        if local(color) == "buClr" {
            if let Some(css) = drawing_color(first_child(Some(color)), env.palette)? {
                styles.push(format!("color:{css}"));
            }
        }
        break;
    }
    for properties in paragraph_nodes {
        let Some(size) =
            elements(*properties).find(|c| matches!(local(*c), "buSzPct" | "buSzPts" | "buSzTx"))
        else {
            continue;
        };
        match local(size) {
            "buSzPct" => {
                if let Some(v) = py_int(size.attribute("val").unwrap_or("100000")) {
                    size_pt *= v as f64 / 100000.0;
                    styles.push(format!("font-size:{}", pt_cqw(size_pt, env.slide_width)));
                }
            }
            "buSzPts" => {
                if let Some(v) = py_int(size.attribute("val").unwrap_or("1800")) {
                    size_pt = v as f64 / 100.0;
                    styles.push(format!("font-size:{}", pt_cqw(size_pt, env.slide_width)));
                }
            }
            _ => {}
        }
        break;
    }
    styles.push("line-height:inherit".into());
    styles.push("white-space:nowrap".into());
    Ok((styles, size_pt))
}

/// v3 `_escaped_run_text`.
fn escaped_run_text(value: &str) -> String {
    escape(value).replace(['\u{b}', '\n'], "<br>")
}

/// Text of an `a:r` (python-pptx `_Run.text`).
fn run_text(run: Nd<'_>) -> String {
    child(run, "t").and_then(own_text).unwrap_or("").to_string()
}

/// The text of an `a:fld` (v3 `"".join(child.itertext())`), whitespace-only
/// text between elements dropped like python-pptx's parser does.
///
/// Fix over v3: python-pptx's `CT_TextField` overrides `.text`, and lxml's
/// `itertext()` yielded that override as well as the `a:t` text below it, so
/// every field (slide numbers, dates) showed its text twice.
fn field_itertext(field: Nd<'_>) -> String {
    let mut text = String::new();
    for node in field.descendants().skip(1).filter(|n| n.is_text()) {
        let value = node.text().unwrap_or("");
        let blank = value.chars().all(char::is_whitespace);
        let between_elements = node
            .parent()
            .is_some_and(|p| p.children().any(|c| c.is_element()));
        if blank && between_elements {
            continue;
        }
        text.push_str(value);
    }
    text
}

/// python-pptx `_Paragraph.text`.
pub(super) fn paragraph_text(paragraph: Nd<'_>) -> String {
    let mut text = String::new();
    for item in elements(paragraph) {
        match local(item) {
            "r" | "fld" => text.push_str(&run_text(item)),
            "br" => text.push('\u{b}'),
            _ => {}
        }
    }
    text
}

/// python-pptx `TextFrame.text`.
pub(super) fn text_frame_text(tx_body: Option<Nd<'_>>) -> String {
    paragraphs(tx_body)
        .into_iter()
        .map(paragraph_text)
        .collect::<Vec<_>>()
        .join("\n")
}

/// v3 `_paragraph_runs_html`.
pub(super) fn paragraph_runs_html(
    paragraph: Nd<'_>,
    paragraph_nodes: &[Nd<'_>],
    env: &TextEnv<'_>,
    default_size_pt: f64,
) -> R<(String, f64)> {
    let mut parts: Vec<String> = Vec::new();
    let mut first_size = default_size_pt;
    for item in elements(paragraph) {
        let name = local(item);
        if name == "br" {
            parts.push("<br>".into());
            continue;
        }
        if !matches!(name, "r" | "fld") {
            continue;
        }
        let (styles, size_pt) =
            effective_run_styles(child(item, "rPr"), paragraph_nodes, env, default_size_pt)?;
        if parts.is_empty() {
            first_size = size_pt;
        }
        let text = if name == "r" {
            run_text(item)
        } else {
            field_itertext(item)
        };
        parts.push(format!(
            "<span style=\"{}\">{}</span>",
            styles.join(";"),
            escaped_run_text(&text)
        ));
    }
    if parts.is_empty() {
        let text = paragraph_text(paragraph);
        if !text.is_empty() {
            let (styles, size) = effective_run_styles(None, paragraph_nodes, env, default_size_pt)?;
            first_size = size;
            parts.push(format!(
                "<span style=\"{}\">{}</span>",
                styles.join(";"),
                escaped_run_text(&text)
            ));
        }
    }
    Ok((parts.concat(), first_size))
}

fn alignment_css(alignment: &str, thai: bool) -> &'static str {
    match alignment {
        "ctr" => "center",
        "r" => "right",
        "just" | "dist" => "justify",
        "thaiDist" if thai => "justify",
        _ => "left",
    }
}

/// The bullet column of a paragraph (marker html + paragraph styles), shared
/// by text frames and table cells.
fn bullet_layout(
    paragraph: Nd<'_>,
    paragraph_nodes: &[Nd<'_>],
    env: &TextEnv<'_>,
    marker: &str,
    margin: i64,
    indent: i64,
    styles: &mut Vec<String>,
) -> R<String> {
    let position = margin.saturating_add(indent).max(0);
    let (marker_styles, marker_size) = bullet_marker_styles(paragraph, paragraph_nodes, env)?;
    let width = margin
        .saturating_sub(position)
        .max(py_round(marker_size * 12700.0 * 0.8))
        .max(1);
    styles.push("display:grid".into());
    styles.push(format!(
        "padding-left:{}",
        cqw(position as f64, env.slide_width)
    ));
    styles.push(format!(
        "grid-template-columns:{} 1fr",
        cqw(width as f64, env.slide_width)
    ));
    styles.push("column-gap:0".into());
    Ok(format!(
        "<span class=\"bullet-marker\" style=\"{}\">{}</span>",
        marker_styles.join(";"),
        escape(marker)
    ))
}

/// v3 `_shape_text`: the text frame of an autoshape.
pub(super) fn shape_text<'a>(ctx: &SlideCtx<'a>, shape: &Shape<'a>) -> R<String> {
    let env = TextEnv::of(ctx);
    let is_slide_title = shape.name().to_lowercase().contains("[role:title]");
    let body_nodes = effective_body_nodes(ctx, shape)?;
    let wrap_mode = first_attribute(&body_nodes, "wrap").unwrap_or("square");
    let mut rendered = Vec::new();
    let mut counters: BTreeMap<i64, i64> = BTreeMap::new();
    for paragraph in paragraphs(shape.tx_body()?) {
        let paragraph_nodes = effective_paragraph_nodes(ctx, shape, paragraph)?;
        let (runs, _) = paragraph_runs_html(paragraph, &paragraph_nodes, &env, 18.0)?;
        let mut styles: Vec<String> = Vec::new();
        if is_slide_title {
            styles.extend(
                [
                    "white-space:nowrap",
                    "overflow-wrap:normal",
                    "line-height:1.05",
                    "letter-spacing:-.015em",
                ]
                .map(String::from),
            );
        }
        if wrap_mode == "none" {
            styles.push("white-space:pre".into());
        }
        let alignment = first_attribute(&paragraph_nodes, "algn").unwrap_or("l");
        styles.push(format!("text-align:{}", alignment_css(alignment, true)));
        let before = spacing_css(&paragraph_nodes, "spcBef", ctx.slide_width);
        let after = spacing_css(&paragraph_nodes, "spcAft", ctx.slide_width);
        let line = spacing_css(&paragraph_nodes, "lnSpc", ctx.slide_width);
        if let Some(before) = before.filter(|s| !s.is_empty()) {
            styles.push(format!("margin-top:{before}"));
        }
        if let Some(after) = after.filter(|s| !s.is_empty()) {
            styles.push(format!("margin-bottom:{after}"));
        }
        if let Some(line) = line.filter(|s| !s.is_empty()) {
            styles.push(format!("line-height:{line}"));
        }

        let level = paragraph_level(paragraph)?;
        counters.retain(|nested, _| *nested <= level);
        let marker = effective_bullet(&paragraph_nodes, &mut counters, level);
        let parse = |name: &str| first_attribute(&paragraph_nodes, name).unwrap_or("0");
        let raw = [parse("marL"), parse("marR"), parse("indent")];
        let parsed: Option<Vec<i64>> = raw
            .iter()
            .map(|r| if r.is_empty() { Some(0) } else { py_int(r) })
            .collect();
        let (margin, right, indent) = match parsed {
            Some(v) => (v[0], v[1], v[2]),
            None => (0, 0, 0),
        };
        if right != 0 {
            styles.push(format!(
                "padding-right:{}",
                cqw(right as f64, ctx.slide_width)
            ));
        }
        let mut marker_html = String::new();
        if !marker.is_empty() {
            marker_html = bullet_layout(
                paragraph,
                &paragraph_nodes,
                &env,
                &marker,
                margin,
                indent,
                &mut styles,
            )?;
        } else if margin != 0 || indent != 0 {
            styles.push(format!(
                "padding-left:{}",
                cqw(margin as f64, ctx.slide_width)
            ));
            if indent != 0 {
                styles.push(format!(
                    "text-indent:{}",
                    cqw(indent as f64, ctx.slide_width)
                ));
            }
        }
        let class_attr = if marker.is_empty() {
            ""
        } else {
            " class=\"has-bullet\""
        };
        let style_attr = if styles.is_empty() {
            String::new()
        } else {
            format!(" style=\"{}\"", styles.join(";"))
        };
        let content = if marker.is_empty() {
            runs
        } else {
            format!("<span class=\"paragraph-content\">{runs}</span>")
        };
        rendered.push(format!(
            "<p{class_attr}{style_attr}>{marker_html}{content}</p>"
        ));
    }
    let columns = match first_attribute(&body_nodes, "numCol") {
        None => 1,
        Some("") => 1,
        Some(raw) => py_int(raw)
            .map(|v| if v == 0 { 1 } else { v })
            .unwrap_or(1)
            .max(1),
    };
    let vertical = match first_attribute(&body_nodes, "anchor").unwrap_or("t") {
        "ctr" => "center",
        "b" => "flex-end",
        "just" => "space-between",
        "dist" => "space-around",
        _ => "flex-start",
    };
    let inset = |name: &str, default: i64| -> i64 {
        match first_attribute(&body_nodes, name) {
            None | Some("") => default,
            Some(raw) => py_int(raw)
                .map(|v| if v == 0 { 0 } else { v })
                .unwrap_or(default),
        }
    };
    let margins = [
        inset("tIns", 45720),
        inset("rIns", 91440),
        inset("bIns", 45720),
        inset("lIns", 91440),
    ];
    let padding = margins
        .iter()
        .map(|m| cqw(*m as f64, ctx.slide_width))
        .collect::<Vec<_>>()
        .join(" ");
    let common = format!("padding:{padding};justify-content:{vertical};");
    let frame_style = if columns > 1 {
        let spacing = match first_attribute(&body_nodes, "spcCol") {
            None | Some("") => 0,
            Some(raw) => py_int(raw).unwrap_or(0),
        };
        format!(
            "{common}column-count:{columns};column-gap:{};column-fill:auto;display:block;overflow:hidden",
            cqw(spacing as f64, ctx.slide_width)
        )
    } else {
        format!("{common}display:flex;flex-direction:column;overflow:hidden")
    };
    Ok(format!(
        "<div class=\"text-frame\" style=\"{frame_style}\">{}</div>",
        rendered.concat()
    ))
}

/// v3 `_table_cell_paragraph_html`.
pub(super) fn table_cell_paragraph_html(
    paragraph: Nd<'_>,
    env: &TextEnv<'_>,
    list_style: Option<Nd<'_>>,
    counters: &mut BTreeMap<i64, i64>,
) -> R<String> {
    let level = paragraph_level(paragraph)?;
    let mut paragraph_nodes: Vec<Nd<'_>> = child(paragraph, "pPr").into_iter().collect();
    if let Some(local_props) = level_properties(list_style, level) {
        paragraph_nodes.push(local_props);
    }
    let (runs, _) = paragraph_runs_html(paragraph, &paragraph_nodes, env, 18.0)?;
    let mut styles: Vec<String> = ["margin:0", "white-space:pre-wrap", "line-height:1.12"]
        .map(String::from)
        .to_vec();
    if let Some(alignment) = first_attribute(&paragraph_nodes, "algn").filter(|a| !a.is_empty()) {
        styles.push(format!("text-align:{}", alignment_css(alignment, false)));
    }
    let before = spacing_css(&paragraph_nodes, "spcBef", env.slide_width);
    let after = spacing_css(&paragraph_nodes, "spcAft", env.slide_width);
    let line = spacing_css(&paragraph_nodes, "lnSpc", env.slide_width);
    if let Some(before) = before.filter(|s| !s.is_empty()) {
        styles.push(format!("margin-top:{before}"));
    }
    if let Some(after) = after.filter(|s| !s.is_empty()) {
        styles.push(format!("margin-bottom:{after}"));
    }
    if let Some(line) = line.filter(|s| !s.is_empty()) {
        styles.push(format!("line-height:{line}"));
    }
    let marker = effective_bullet(&paragraph_nodes, counters, level);
    let mut marker_html = String::new();
    if !marker.is_empty() {
        let parse = |name: &str| match first_attribute(&paragraph_nodes, name) {
            None | Some("") => Some(0),
            Some(raw) => py_int(raw),
        };
        let (margin, indent) = match (parse("marL"), parse("indent")) {
            (Some(m), Some(i)) => (m, i),
            _ => (0, 0),
        };
        marker_html = bullet_layout(
            paragraph,
            &paragraph_nodes,
            env,
            &marker,
            margin,
            indent,
            &mut styles,
        )?;
    }
    let class_attr = if marker.is_empty() {
        ""
    } else {
        " class=\"has-bullet\""
    };
    let content = if marker.is_empty() {
        runs
    } else {
        format!("<span class=\"paragraph-content\">{runs}</span>")
    };
    Ok(format!(
        "<p{class_attr} style=\"{}\">{marker_html}{content}</p>",
        styles.join(";")
    ))
}
