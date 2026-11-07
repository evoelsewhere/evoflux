//! Shape surfaces: fills (solid, gradient, pattern), outlines and dashes,
//! shadows, preset geometry and connectors (v3 `_shape_fill_svg`,
//! `_shape_line_properties`, `_shape_shadow_css`, `_preset_svg_geometry`,
//! `_shape_surface_svg`, `_connector_svg`).

use super::super::html::escape;
use super::color::{shape_color, Palette};
use super::model::{Dim, Shape, SlideCtx};
use super::text::paragraphs;
use super::util::{
    child, descendant, descendants, descendants_ns, elements, f, first_child, local, percent_of,
    py_int, sha1_hex, Nd, A, R,
};

/// `./p:style/a:<name>` of a shape.
fn style_reference<'a>(shape: &Shape<'a>, name: &str) -> Option<Nd<'a>> {
    child(child(shape.node, "style")?, name)
}

/// v3 `_shape_reference_color`.
pub(super) fn reference_color(shape: &Shape<'_>, name: &str, palette: &Palette) -> Option<String> {
    let reference = style_reference(shape, name)?;
    shape_color(first_child(Some(reference)), palette, None, 1.0)
}

/// v3 `_shape_theme_style_node`: the theme format-scheme entry a style
/// reference points at.
fn theme_style_node<'a>(
    ctx: &SlideCtx<'a>,
    shape: &Shape<'_>,
    reference_name: &str,
    list_name: &str,
) -> Option<Nd<'a>> {
    let reference = style_reference(shape, reference_name)?;
    let index = py_int(reference.attribute("idx").unwrap_or("0"))?.checked_sub(1)?;
    if index < 0 {
        return None;
    }
    let theme = ctx.theme?;
    let styles: Vec<Nd<'a>> = descendants_ns(theme, A, "fmtScheme")
        .flat_map(|scheme| {
            elements(scheme)
                .filter(|e| e.tag_name().name() == list_name && e.tag_name().namespace() == Some(A))
        })
        .flat_map(elements)
        .collect();
    styles.get(index as usize).copied()
}

fn sp_pr<'a>(shape: &Shape<'a>) -> Option<Nd<'a>> {
    child(shape.node, "spPr")
}

/// The shape's own `spPr/a:ln`.
fn own_line<'a>(shape: &Shape<'a>) -> Option<Nd<'a>> {
    child(sp_pr(shape)?, "ln")
}

/// v3 `_shape_line_properties`: colour, CSS-pixel width and preset dash.
pub(super) fn line_properties(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
) -> (Option<String>, f64, Option<String>) {
    let palette = &ctx.palette;
    let line = own_line(shape);
    let placeholder = reference_color(shape, "lnRef", palette);
    let theme_line = theme_style_node(ctx, shape, "lnRef", "lnStyleLst");
    let effective = line.or(theme_line);
    let Some(effective) = effective else {
        return (None, 1.0, None);
    };
    if child(effective, "noFill").is_some() {
        return (None, 1.0, None);
    }
    let solid = child(effective, "solidFill");
    let mut color = shape_color(first_child(solid), palette, placeholder.as_deref(), 1.0);
    if color.is_none() && line.is_some() {
        if let Some(theme_line) = theme_line {
            let solid = child(theme_line, "solidFill");
            color = shape_color(first_child(solid), palette, placeholder.as_deref(), 1.0);
        }
    }
    let raw_width = match line.and_then(|l| l.attribute("w")) {
        Some(w) => py_int(w),
        None => match theme_line {
            Some(t) => py_int(t.attribute("w").unwrap_or("9525")),
            None => Some(9525),
        },
    }
    .unwrap_or(9525);
    let mut dash = line.and_then(|l| child(l, "prstDash"));
    if dash.is_none() {
        dash = theme_line.and_then(|t| child(t, "prstDash"));
    }
    let dash = dash.map(|d| d.attribute("val").unwrap_or("None").to_string());
    (color, (raw_width as f64 / 9525.0).max(0.5), dash)
}

/// v3 `_line_dash_array`.
pub(super) fn line_dash_array(preset: Option<&str>, width: f64) -> Option<String> {
    let units: &[f64] = match preset? {
        "dot" => &[1.0, 2.4],
        "sysDot" => &[1.0, 2.0],
        "dash" => &[4.0, 3.0],
        "sysDash" => &[3.0, 2.0],
        "lgDash" => &[8.0, 3.0],
        "dashDot" => &[4.0, 2.0, 1.0, 2.0],
        "sysDashDot" => &[3.0, 2.0, 1.0, 2.0],
        "lgDashDot" => &[8.0, 3.0, 1.0, 3.0],
        "lgDashDotDot" => &[8.0, 3.0, 1.0, 3.0, 1.0, 3.0],
        "sysDashDotDot" => &[3.0, 2.0, 1.0, 2.0, 1.0, 2.0],
        _ => return None,
    };
    Some(
        units
            .iter()
            .map(|v| f((v * width).max(1.0), 2))
            .collect::<Vec<_>>()
            .join(" "),
    )
}

/// v3 `_shape_shadow_node`.
fn shadow_node<'a>(ctx: &SlideCtx<'a>, shape: &Shape<'a>) -> Option<Nd<'a>> {
    if let Some(shadow) = sp_pr(shape)
        .and_then(|s| child(s, "effectLst"))
        .and_then(|e| child(e, "outerShdw"))
    {
        return Some(shadow);
    }
    let effect = theme_style_node(ctx, shape, "effectRef", "effectStyleLst")?;
    effect
        .descendants()
        .find(|n| n.is_element() && local(*n) == "outerShdw")
}

/// v3 `_shape_shadow_css`.
pub(super) fn shadow_css(ctx: &SlideCtx<'_>, shape: &Shape<'_>) -> Option<String> {
    let shadow = shadow_node(ctx, shape)?;
    let color_node =
        elements(shadow).find(|c| matches!(local(*c), "srgbClr" | "sysClr" | "schemeClr"));
    let placeholder = reference_color(shape, "effectRef", &ctx.palette);
    let color = shape_color(color_node, &ctx.palette, placeholder.as_deref(), 0.16)
        .unwrap_or_else(|| "rgba(0,0,0,.16)".into());
    let parsed = (
        py_int(shadow.attribute("dist").unwrap_or("0")),
        py_int(shadow.attribute("dir").unwrap_or("0")),
        py_int(shadow.attribute("blurRad").unwrap_or("0")),
    );
    let (distance_pt, angle, blur) = match parsed {
        (Some(d), Some(a), Some(b)) => (
            d as f64 / 12700.0,
            (a as f64 / 60000.0).to_radians(),
            b as f64 / 12700.0 * 96.0 / 72.0,
        ),
        _ => (0.0, 0.0, 0.0),
    };
    let offset_x = angle.cos() * distance_pt * 96.0 / 72.0;
    let offset_y = angle.sin() * distance_pt * 96.0 / 72.0;
    Some(format!(
        "{}px {}px {}px {color}",
        f(offset_x, 2),
        f(offset_y, 2),
        f(blur, 2)
    ))
}

/// v3 `_preset_geometry_name`.
pub(super) fn preset_geometry_name(shape: &Shape<'_>) -> String {
    sp_pr(shape)
        .and_then(|s| child(s, "prstGeom"))
        .map(|g| {
            g.attribute("prst")
                .filter(|p| !p.is_empty())
                .unwrap_or("rect")
                .to_string()
        })
        .unwrap_or_else(|| "rect".into())
}

/// v3 `_connector_adjustment`.
fn connector_adjustment(shape: &Shape<'_>) -> f64 {
    let guides: Vec<Nd<'_>> = sp_pr(shape)
        .into_iter()
        .flat_map(|s| elements(s).filter(|e| local(*e) == "prstGeom"))
        .flat_map(|g| elements(g).filter(|e| local(*e) == "avLst"))
        .flat_map(|av| elements(av).filter(|g| local(*g) == "gd"))
        .collect();
    for guide in guides {
        let formula = guide.attribute("fmla").unwrap_or("");
        let parts: Vec<&str> = formula.split_whitespace().collect();
        if parts.len() == 2 && parts[0] == "val" {
            if let Some(value) = super::util::py_float(parts[1]) {
                return (value / 100000.0).clamp(0.0, 1.0);
            }
        }
    }
    0.5
}

/// v3 `_connector_marker`.
fn connector_marker(marker: Option<Nd<'_>>, marker_id: &str, color: &str) -> (String, String) {
    let Some(marker) = marker else {
        return (String::new(), String::new());
    };
    let kind = marker
        .attribute("type")
        .filter(|t| !t.is_empty())
        .unwrap_or("none");
    if kind == "none" {
        return (String::new(), String::new());
    }
    let size_key = marker
        .attribute("w")
        .filter(|v| !v.is_empty())
        .or_else(|| marker.attribute("len").filter(|v| !v.is_empty()))
        .unwrap_or("med");
    let size = match size_key {
        "sm" => 2.8,
        "lg" => 4.4,
        _ => 3.6,
    };
    let path = match kind {
        "diamond" => format!("<path d=\"M0 5L5 0L10 5L5 10Z\" fill=\"{color}\"/>"),
        "oval" => format!("<circle cx=\"5\" cy=\"5\" r=\"4\" fill=\"{color}\"/>"),
        "arrow" | "open" => format!(
            "<path d=\"M1 1L9 5L1 9\" fill=\"none\" stroke=\"{color}\" stroke-width=\"1.7\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>"
        ),
        "stealth" => format!("<path d=\"M0 0L10 5L0 10L3.5 5Z\" fill=\"{color}\"/>"),
        _ => format!("<path d=\"M0 0L10 5L0 10Z\" fill=\"{color}\"/>"),
    };
    let definition = format!(
        "<marker id=\"{marker_id}\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" markerWidth=\"{size:.1}\" markerHeight=\"{size:.1}\" orient=\"auto-start-reverse\">{path}</marker>"
    );
    (definition, format!("url(#{marker_id})"))
}

/// The coordinate frame a shape is positioned in (slide or group).
#[derive(Clone, Copy, Default)]
pub(super) struct Coords {
    pub left: i64,
    pub top: i64,
    pub width: Option<i64>,
    pub height: Option<i64>,
}

/// `left/top/width/height` in percent of the frame.
pub(super) fn box_percentages(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
    coords: Coords,
) -> R<[f64; 4]> {
    let width_basis = coords
        .width
        .filter(|w| *w != 0)
        .unwrap_or(ctx.slide_width)
        .max(1) as f64;
    let height_basis = coords
        .height
        .filter(|h| *h != 0)
        .unwrap_or(ctx.slide_height)
        .max(1) as f64;
    let left = percent_of(
        shape.dim0(ctx, Dim::Left)?.saturating_sub(coords.left),
        width_basis,
    );
    let top = percent_of(
        shape.dim0(ctx, Dim::Top)?.saturating_sub(coords.top),
        height_basis,
    );
    let width = percent_of(shape.dim0(ctx, Dim::Width)?, width_basis);
    let height = percent_of(shape.dim0(ctx, Dim::Height)?, height_basis);
    Ok([left, top, width, height])
}

/// The first `xfrm` anywhere below the shape (v3 `.//*[local-name()='xfrm']`).
pub(super) fn first_xfrm<'a>(shape: &Shape<'a>) -> Option<Nd<'a>> {
    descendant(shape.node, "xfrm")
}

/// v3 `_shape_transform_css`.
fn transform_css(shape: &Shape<'_>) -> Option<String> {
    let transform = first_xfrm(shape);
    let mut values = Vec::new();
    let rotation = shape.rotation();
    if rotation != 0.0 {
        values.push(format!("rotate({}deg)", f(rotation, 3)));
    }
    if transform.and_then(|t| t.attribute("flipH")) == Some("1") {
        values.push("scaleX(-1)".to_string());
    }
    if transform.and_then(|t| t.attribute("flipV")) == Some("1") {
        values.push("scaleY(-1)".to_string());
    }
    (!values.is_empty()).then(|| values.join(" "))
}

/// v3 `_shape_box`.
pub(super) fn shape_box(ctx: &SlideCtx<'_>, shape: &Shape<'_>, coords: Coords) -> R<String> {
    let [left, top, width, height] = box_percentages(ctx, shape, coords)?;
    let mut styles = format!(
        "left:{}%;top:{}%;width:{}%;height:{}%",
        f(left, 3),
        f(top, 3),
        f(width, 3),
        f(height, 3)
    );
    if let Some(transform) = transform_css(shape) {
        styles.push_str(&format!(";transform:{transform}"));
    }
    Ok(styles)
}

/// v3 `_shape_identity`.
pub(super) fn identity(shape: &Shape<'_>, layer: &str) -> R<String> {
    let shape_id = escape(&shape.shape_id()?);
    let name = escape(shape.name());
    let label = if name.is_empty() { &shape_id } else { &name };
    Ok(format!(
        "data-shape-id=\"{shape_id}\" data-shape-name=\"{name}\" data-qa-label=\"{label}\" data-source-layer=\"{layer}\""
    ))
}

fn svg_key(ctx: &SlideCtx<'_>, shape: &Shape<'_>, suffix: &str) -> R<String> {
    let value = format!(
        "{}:{}:{suffix}",
        ctx.deck.partname(shape.part),
        shape.shape_id()?
    );
    Ok(sha1_hex(&value)[..12].to_string())
}

/// v3 `_connector_svg`.
pub(super) fn connector_svg(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
    layer: &str,
    coords: Coords,
) -> R<String> {
    let [left, top, width, height] = box_percentages(ctx, shape, coords)?;
    let transform = first_xfrm(shape);
    let flip_h = transform.and_then(|t| t.attribute("flipH")) == Some("1");
    let flip_v = transform.and_then(|t| t.attribute("flipV")) == Some("1");
    let (mut x1, mut x2) = if flip_h { (1000, 0) } else { (0, 1000) };
    let (mut y1, mut y2) = if flip_v { (1000, 0) } else { (0, 1000) };
    if shape.dim(ctx, Dim::Width)? == Some(0) {
        x1 = 500;
        x2 = 500;
    }
    if shape.dim(ctx, Dim::Height)? == Some(0) {
        y1 = 500;
        y2 = 500;
    }
    let (color, line_width, dash) = line_properties(ctx, shape);
    let color = color
        .filter(|c| !c.is_empty())
        .unwrap_or_else(|| "#66717c".into());
    let line_node = own_line(shape);
    let head = line_node.and_then(|l| child(l, "headEnd"));
    let tail = line_node.and_then(|l| child(l, "tailEnd"));
    let prefix = sha1_hex(&format!(
        "{}:{}",
        ctx.deck.partname(shape.part),
        shape.shape_id()?
    ))[..12]
        .to_string();
    let (head_definition, marker_start) =
        connector_marker(head, &format!("connector-head-{prefix}"), &color);
    let (tail_definition, marker_end) =
        connector_marker(tail, &format!("connector-tail-{prefix}"), &color);
    let definitions = if head_definition.is_empty() && tail_definition.is_empty() {
        String::new()
    } else {
        format!("<defs>{head_definition}{tail_definition}</defs>")
    };
    let mut marker_attributes = String::new();
    if !marker_start.is_empty() {
        marker_attributes.push_str(&format!(" marker-start=\"{marker_start}\""));
    }
    if !marker_end.is_empty() {
        marker_attributes.push_str(&format!(" marker-end=\"{marker_end}\""));
    }
    let dash_attribute = line_dash_array(dash.as_deref(), line_width)
        .map(|d| format!(" stroke-dasharray=\"{d}\""))
        .unwrap_or_default();
    let preset = preset_geometry_name(shape);
    let path = if preset.starts_with("bentConnector") {
        let middle = x1 as f64 + (x2 - x1) as f64 * connector_adjustment(shape);
        format!("M{x1} {y1}H{}V{y2}H{x2}", f(middle, 2))
    } else if preset.starts_with("curvedConnector") {
        let middle = x1 as f64 + (x2 - x1) as f64 * connector_adjustment(shape);
        let m = f(middle, 2);
        format!("M{x1} {y1}C{m} {y1} {m} {y2} {x2} {y2}")
    } else {
        format!("M{x1} {y1}L{x2} {y2}")
    };
    let shadow_style = shadow_css(ctx, shape)
        .map(|s| format!(" style=\"filter:drop-shadow({s})\""))
        .unwrap_or_default();
    let identity = identity(shape, layer)?;
    let mut style = format!(
        "left:{}%;top:{}%;width:max({}%,2px);height:max({}%,2px)",
        f(left, 3),
        f(top, 3),
        f(width, 3),
        f(height, 3)
    );
    let rotation = shape.rotation();
    if rotation != 0.0 {
        style.push_str(&format!(";transform:rotate({}deg)", f(rotation, 3)));
    }
    Ok(format!(
        "<svg class=\"shape connector\" {identity} style=\"{style}\" data-connector-geometry=\"{}\" viewBox=\"0 0 1000 1000\" preserveAspectRatio=\"none\">{definitions}<path d=\"{path}\" fill=\"none\" stroke=\"{color}\" stroke-width=\"{}\" stroke-linejoin=\"miter\" vector-effect=\"non-scaling-stroke\"{dash_attribute}{marker_attributes}{shadow_style}/></svg>",
        escape(&preset),
        f(line_width, 2)
    ))
}

/// v3 `_shape_gradient_svg`.
fn gradient_svg(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
    gradient: Nd<'_>,
    placeholder: Option<&str>,
) -> R<Option<(String, String)>> {
    let mut stops = Vec::new();
    for list in elements(gradient).filter(|e| local(*e) == "gsLst") {
        for stop in elements(list).filter(|e| local(*e) == "gs") {
            let Some(color) = shape_color(first_child(Some(stop)), &ctx.palette, placeholder, 1.0)
            else {
                continue;
            };
            let offset = py_int(stop.attribute("pos").unwrap_or("0"))
                .map(|v| v as f64 / 1000.0)
                .unwrap_or(0.0);
            stops.push(format!(
                "<stop offset=\"{}%\" stop-color=\"{}\"/>",
                f(offset, 2),
                escape(&color)
            ));
        }
    }
    if stops.len() < 2 {
        return Ok(None);
    }
    let id = format!("shape-gradient-{}", svg_key(ctx, shape, "gradient")?);
    let definition = if child(gradient, "path").is_some() {
        format!(
            "<radialGradient id=\"{id}\" cx=\"50%\" cy=\"50%\" r=\"70%\">{}</radialGradient>",
            stops.concat()
        )
    } else {
        let angle = match child(gradient, "lin") {
            Some(linear) => py_int(linear.attribute("ang").unwrap_or("0"))
                .map(|v| v as f64 / 60000.0)
                .unwrap_or(0.0),
            None => 0.0,
        };
        format!(
            "<linearGradient id=\"{id}\" x1=\"0\" y1=\"0.5\" x2=\"1\" y2=\"0.5\" gradientTransform=\"rotate({} .5 .5)\">{}</linearGradient>",
            f(angle, 3),
            stops.concat()
        )
    };
    Ok(Some((definition, format!("url(#{id})"))))
}

/// v3 `_shape_pattern_svg`.
fn pattern_svg(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
    pattern: Nd<'_>,
    placeholder: Option<&str>,
) -> R<(String, String, String)> {
    let pick = |name: &str| {
        let holder = child(pattern, name);
        holder
            .and_then(|h| child(h, "srgbClr"))
            .or_else(|| first_child(holder))
    };
    let foreground = shape_color(pick("fgClr"), &ctx.palette, placeholder, 1.0)
        .unwrap_or_else(|| "#000000".into());
    let background = shape_color(pick("bgClr"), &ctx.palette, placeholder, 1.0)
        .unwrap_or_else(|| "#ffffff".into());
    let preset = pattern
        .attribute("prst")
        .filter(|p| !p.is_empty())
        .unwrap_or("diagCross")
        .to_string();
    let id = format!("shape-pattern-{}", svg_key(ctx, shape, &preset)?);
    let marks = match preset.as_str() {
        "cross" | "smGrid" | "lgGrid" => "<path d=\"M50 0V100M0 50H100\"/>",
        "horz" | "ltHorz" | "dkHorz" | "narHorz" | "dashHorz" => "<path d=\"M0 50H100\"/>",
        "vert" | "ltVert" | "dkVert" | "narVert" | "dashVert" => "<path d=\"M50 0V100\"/>",
        "upDiag" | "ltUpDiag" | "dkUpDiag" | "wdUpDiag" | "dashUpDiag" => {
            "<path d=\"M-25 75L75-25M25 125L125 25\"/>"
        }
        "dnDiag" | "ltDnDiag" | "dkDnDiag" | "wdDnDiag" | "dashDnDiag" => {
            "<path d=\"M-25 25L75 125M25-25L125 75\"/>"
        }
        "pct5" | "pct10" | "pct20" | "pct25" | "pct30" | "pct40" => {
            "<circle cx=\"25\" cy=\"25\" r=\"4\"/><circle cx=\"75\" cy=\"75\" r=\"4\"/>"
        }
        _ => "<path d=\"M-25 25L75 125M25-25L125 75M-25 75L75-25M25 125L125 25\"/>",
    };
    let fg = escape(&foreground);
    let definition = format!(
        "<pattern id=\"{id}\" width=\"100\" height=\"100\" patternUnits=\"userSpaceOnUse\"><rect width=\"100\" height=\"100\" fill=\"{}\"/><g fill=\"{fg}\" stroke=\"{fg}\" stroke-width=\"3\">{marks}</g></pattern>",
        escape(&background)
    );
    Ok((definition, format!("url(#{id})"), preset))
}

/// v3 `_shape_fill_svg`: (definitions, fill paint, metadata attributes).
fn fill_svg(ctx: &SlideCtx<'_>, shape: &Shape<'_>) -> R<(String, String, String)> {
    let mut fill = sp_pr(shape).and_then(|s| {
        elements(s).find(|c| matches!(local(*c), "solidFill" | "gradFill" | "pattFill" | "noFill"))
    });
    let placeholder = reference_color(shape, "fillRef", &ctx.palette);
    if fill.is_none() {
        fill = theme_style_node(ctx, shape, "fillRef", "fillStyleLst");
    }
    let Some(fill) = fill.filter(|f| local(*f) != "noFill") else {
        return Ok((
            String::new(),
            "none".into(),
            "data-shape-fill=\"none\"".into(),
        ));
    };
    match local(fill) {
        "solidFill" => {
            let color = shape_color(
                first_child(Some(fill)),
                &ctx.palette,
                placeholder.as_deref(),
                1.0,
            );
            return Ok((
                String::new(),
                color.unwrap_or_else(|| "none".into()),
                "data-shape-fill=\"solid\"".into(),
            ));
        }
        "gradFill" => {
            if let Some((definition, paint)) =
                gradient_svg(ctx, shape, fill, placeholder.as_deref())?
            {
                return Ok((definition, paint, "data-shape-fill=\"gradient\"".into()));
            }
        }
        "pattFill" => {
            let (definition, paint, preset) =
                pattern_svg(ctx, shape, fill, placeholder.as_deref())?;
            return Ok((
                definition,
                paint,
                format!(
                    "data-shape-fill=\"pattern\" data-pattern=\"{}\"",
                    escape(&preset)
                ),
            ));
        }
        _ => {}
    }
    Ok((
        String::new(),
        placeholder.unwrap_or_else(|| "none".into()),
        "data-shape-fill=\"fallback\"".into(),
    ))
}

/// v3 `_preset_svg_geometry`: (element markup, supported).
fn preset_svg_geometry(preset: &str) -> (String, bool) {
    let polygon = match preset {
        "triangle" => Some("500,0 1000,1000 0,1000"),
        "rtTriangle" => Some("0,0 1000,1000 0,1000"),
        "diamond" => Some("500,0 1000,500 500,1000 0,500"),
        "parallelogram" => Some("150,0 1000,0 850,1000 0,1000"),
        "trapezoid" => Some("200,0 800,0 1000,1000 0,1000"),
        "pentagon" => Some("500,0 1000,380 820,1000 180,1000 0,380"),
        "hexagon" => Some("250,0 750,0 1000,500 750,1000 250,1000 0,500"),
        "octagon" => Some("290,0 710,0 1000,290 1000,710 710,1000 290,1000 0,710 0,290"),
        "chevron" => Some("0,0 750,0 1000,500 750,1000 0,1000 250,500"),
        "homePlate" => Some("0,0 750,0 1000,500 750,1000 0,1000"),
        "rightArrow" => Some("0,200 650,200 650,0 1000,500 650,1000 650,800 0,800"),
        "leftArrow" => Some("350,0 350,200 1000,200 1000,800 350,800 350,1000 0,500"),
        "upArrow" => Some("500,0 1000,350 800,350 800,1000 200,1000 200,350 0,350"),
        "downArrow" => Some("200,0 800,0 800,650 1000,650 500,1000 0,650 200,650"),
        "leftRightArrow" => Some("200,0 200,250 800,250 800,0 1000,500 800,1000 800,750 200,750 200,1000 0,500"),
        "star5" => Some("500,0 610,350 980,350 680,570 790,920 500,700 210,920 320,570 20,350 390,350"),
        "star4" => Some("500,0 610,390 1000,500 610,610 500,1000 390,610 0,500 390,390"),
        "plus" => Some("350,0 650,0 650,350 1000,350 1000,650 650,650 650,1000 350,1000 350,650 0,650 0,350 350,350"),
        "heart" => Some("500,1000 70,550 0,320 80,120 250,20 420,80 500,220 580,80 750,20 920,120 1000,320 930,550"),
        _ => None,
    };
    match preset {
        "roundRect" | "round1Rect" | "round2SameRect" | "round2DiagRect" => {
            ("<rect x=\"0\" y=\"0\" width=\"1000\" height=\"1000\" rx=\"80\" ry=\"80\"/>".into(), true)
        }
        "ellipse" => ("<ellipse cx=\"500\" cy=\"500\" rx=\"500\" ry=\"500\"/>".into(), true),
        "arc" => ("<path d=\"M500 0A500 500 0 0 1 1000 500L500 500Z\"/>".into(), true),
        "cloud" => (
            "<path d=\"M110 665C20 630 15 505 95 450C55 330 160 235 275 265C320 120 475 75 585 175C690 70 860 130 880 275C1010 295 1045 450 950 535C980 665 845 770 725 710C650 845 455 850 365 720C255 795 135 760 110 665Z\"/>".into(),
            true,
        ),
        _ => match polygon {
            Some(points) => (format!("<polygon points=\"{points}\"/>"), true),
            None => ("<rect x=\"0\" y=\"0\" width=\"1000\" height=\"1000\"/>".into(), preset == "rect"),
        },
    }
}

/// v3 `_shape_surface_svg`.
pub(super) fn surface_svg(ctx: &SlideCtx<'_>, shape: &Shape<'_>) -> R<String> {
    let preset = preset_geometry_name(shape);
    let (geometry, supported) = preset_svg_geometry(&preset);
    let (definitions, fill, fill_metadata) = fill_svg(ctx, shape)?;
    let (line, line_width, dash) = line_properties(ctx, shape);
    if fill == "none" && line.is_none() {
        return Ok(String::new());
    }
    let stroke = line
        .as_deref()
        .filter(|l| !l.is_empty())
        .map(escape)
        .unwrap_or_else(|| "none".into());
    let mut attributes = format!(
        "fill=\"{}\" stroke=\"{stroke}\" stroke-width=\"{}\" stroke-linejoin=\"round\" vector-effect=\"non-scaling-stroke\"",
        escape(&fill),
        f(line_width, 2)
    );
    if let Some(dash_array) = line_dash_array(dash.as_deref(), line_width).filter(|d| !d.is_empty())
    {
        attributes.push_str(&format!(" stroke-dasharray=\"{dash_array}\""));
    }
    let surface_style = shadow_css(ctx, shape)
        .map(|s| format!(" style=\"filter:drop-shadow({s})\""))
        .unwrap_or_default();
    let fallback = if supported {
        ""
    } else {
        " data-geometry-fallback=\"rect\""
    };
    Ok(format!(
        "<svg class=\"shape-surface\" aria-hidden=\"true\" data-preset-geometry=\"{}\" {fill_metadata}{fallback} viewBox=\"0 0 1000 1000\" preserveAspectRatio=\"none\"{surface_style}><defs>{definitions}</defs>{} {attributes}/></svg>",
        escape(&preset),
        &geometry[..geometry.len() - 2]
    ))
}

/// v3 `_shape_text_container_attributes`: (styles, extra attributes).
pub(super) fn text_container_attributes(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
    preset: &str,
) -> R<(Vec<String>, String)> {
    let mut styles = vec!["overflow:visible".to_string()];
    let font_color = reference_color(shape, "fontRef", &ctx.palette);
    let tx_body = child(shape.node, "txBody");
    let has_explicit_run_color = tx_body.is_some_and(|body| {
        descendants(body, "rPr")
            .any(|r| elements(r).any(|c| matches!(local(c), "solidFill" | "gradFill" | "pattFill")))
    });
    let mut color_attribute = "";
    if let Some(color) = font_color.filter(|c| !c.is_empty()) {
        if !has_explicit_run_color {
            styles.push(format!("color:{color}"));
            styles.push(format!("--shape-text-color:{color}"));
            color_attribute = " data-shape-font-color=\"theme\"";
        }
    }
    let explicit_alignment = paragraphs(shape.tx_body()?)
        .iter()
        .any(|p| child(*p, "pPr").and_then(|p| p.attribute("algn")).is_some());
    let centered = matches!(
        preset,
        "rightArrow" | "leftArrow" | "upArrow" | "downArrow" | "leftRightArrow"
    );
    let mut attributes = if !explicit_alignment && centered {
        " data-default-text-align=\"center\"".to_string()
    } else {
        String::new()
    };
    attributes.push_str(color_attribute);
    let transform = first_xfrm(shape);
    let mut flips = Vec::new();
    if transform.and_then(|t| t.attribute("flipH")) == Some("1") {
        flips.push("horizontal");
    }
    if transform.and_then(|t| t.attribute("flipV")) == Some("1") {
        flips.push("vertical");
    }
    if !flips.is_empty() {
        attributes.push_str(&format!(" data-text-unflip=\"{}\"", flips.join(" ")));
    }
    Ok((styles, attributes))
}

/// v3 `_preset_clip_css`.
pub(super) fn preset_clip_css(preset: &str) -> Option<&'static str> {
    Some(match preset {
        "roundRect" => "inset(0 round 8%)",
        "ellipse" => "ellipse(50% 50% at 50% 50%)",
        "triangle" => "polygon(50% 0,100% 100%,0 100%)",
        "rtTriangle" => "polygon(0 0,100% 100%,0 100%)",
        "diamond" => "polygon(50% 0,100% 50%,50% 100%,0 50%)",
        "parallelogram" => "polygon(15% 0,100% 0,85% 100%,0 100%)",
        "trapezoid" => "polygon(20% 0,80% 0,100% 100%,0 100%)",
        "pentagon" => "polygon(50% 0,100% 38%,82% 100%,18% 100%,0 38%)",
        "hexagon" => "polygon(25% 0,75% 0,100% 50%,75% 100%,25% 100%,0 50%)",
        "octagon" => "polygon(29% 0,71% 0,100% 29%,100% 71%,71% 100%,29% 100%,0 71%,0 29%)",
        "chevron" => "polygon(0 0,75% 0,100% 50%,75% 100%,0 100%,25% 50%)",
        "homePlate" => "polygon(0 0,75% 0,100% 50%,75% 100%,0 100%)",
        "rightArrow" => "polygon(0 20%,65% 20%,65% 0,100% 50%,65% 100%,65% 80%,0 80%)",
        "leftArrow" => "polygon(35% 0,35% 20%,100% 20%,100% 80%,35% 80%,35% 100%,0 50%)",
        "upArrow" => "polygon(50% 0,100% 35%,80% 35%,80% 100%,20% 100%,20% 35%,0 35%)",
        "downArrow" => "polygon(20% 0,80% 0,80% 65%,100% 65%,50% 100%,0 65%,20% 65%)",
        "leftRightArrow" => "polygon(20% 0,20% 25%,80% 25%,80% 0,100% 50%,80% 100%,80% 75%,20% 75%,20% 100%,0 50%)",
        "star5" => "polygon(50% 0,61% 35%,98% 35%,68% 57%,79% 92%,50% 70%,21% 92%,32% 57%,2% 35%,39% 35%)",
        "star4" => "polygon(50% 0,61% 39%,100% 50%,61% 61%,50% 100%,39% 61%,0 50%,39% 39%)",
        "plus" => "polygon(35% 0,65% 0,65% 35%,100% 35%,100% 65%,65% 65%,65% 100%,35% 100%,35% 65%,0 65%,0 35%,35% 35%)",
        "heart" => "polygon(50% 100%,7% 55%,0 32%,8% 12%,25% 2%,42% 8%,50% 22%,58% 8%,75% 2%,92% 12%,100% 32%,93% 55%)",
        _ => return None,
    })
}
