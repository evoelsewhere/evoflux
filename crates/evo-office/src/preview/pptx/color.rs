//! Theme palette and fonts, DrawingML colours and their luminance transforms
//! (v3 `_pptx_theme_palette`, `_pptx_theme_fonts`, `_apply_brightness`,
//! `_xml_drawing_color_css`, `_shape_xml_color_css`, `_slide_background`).

use std::collections::HashMap;

use super::model::SlideCtx;
use super::util::{
    child, child_ns, descendants_ns, elements, f, first_child, local, py_int, py_round, Nd, Skip, A,
};

pub(super) type Palette = HashMap<String, String>;

/// v3 `_css_color` for a raw attribute (non-ASCII text is never a colour; the
/// shared helper slices bytes, so keep it away from multi-byte input).
pub(super) fn css_color(raw: Option<&str>, default: &str) -> String {
    match raw {
        Some(text) if !text.is_ascii() => default.to_string(),
        other => super::super::html::css_color(other, default),
    }
}

/// The colour scheme of the theme (with the `bg1`/`tx1`/`bg2`/`tx2` aliases).
pub(super) fn theme_palette(theme: Option<Nd<'_>>) -> Palette {
    let mut palette = Palette::new();
    let Some(root) = theme else {
        return palette;
    };
    let scheme = descendants_ns(root, A, "themeElements").find_map(|e| child_ns(e, A, "clrScheme"));
    let Some(scheme) = scheme else {
        return palette;
    };
    for entry in elements(scheme) {
        let Some(color) = elements(entry).next() else {
            continue;
        };
        let raw = color
            .attribute("val")
            .or_else(|| color.attribute("lastClr"));
        let css = css_color(raw, "transparent");
        if css != "transparent" {
            palette.insert(local(entry).to_string(), css);
        }
    }
    for (alias, source, default) in [
        ("bg1", "lt1", "#ffffff"),
        ("tx1", "dk1", "#000000"),
        ("bg2", "lt2", "#e7e6e6"),
        ("tx2", "dk2", "#44546a"),
    ] {
        let value = palette
            .get(source)
            .cloned()
            .unwrap_or_else(|| default.to_string());
        palette.insert(alias.to_string(), value);
    }
    palette
}

/// The major/minor theme fonts.
pub(super) fn theme_fonts(theme: Option<Nd<'_>>) -> HashMap<String, String> {
    let mut fonts = HashMap::new();
    let Some(root) = theme else {
        return fonts;
    };
    for (key, group, script) in [
        ("major-latin", "majorFont", "latin"),
        ("major-east-asian", "majorFont", "ea"),
        ("major-complex", "majorFont", "cs"),
        ("minor-latin", "minorFont", "latin"),
        ("minor-east-asian", "minorFont", "ea"),
        ("minor-complex", "minorFont", "cs"),
    ] {
        // ElementTree `.//a:fontScheme/a:majorFont/a:latin`.
        let node = descendants_ns(root, A, "fontScheme")
            .filter_map(|s| child_ns(s, A, group))
            .find_map(|g| child_ns(g, A, script));
        if let Some(typeface) = node
            .and_then(|n| n.attribute("typeface"))
            .filter(|t| !t.is_empty())
        {
            fonts.insert(key.to_string(), typeface.to_string());
        }
    }
    fonts
}

/// v3 `_apply_brightness`.
pub(super) fn apply_brightness(color: &str, brightness: f64) -> String {
    if !color.starts_with('#') || color.len() != 7 || brightness == 0.0 || !color.is_ascii() {
        return color.to_string();
    }
    let channels: Vec<i64> = [1, 3, 5]
        .iter()
        .map(|i| i64::from_str_radix(&color[*i..*i + 2], 16).unwrap_or(0))
        .collect();
    let adjusted: Vec<i64> = channels
        .iter()
        .map(|c| {
            let c = *c as f64;
            if brightness > 0.0 {
                py_round(c + (255.0 - c) * brightness)
            } else {
                py_round(c * (1.0 + brightness))
            }
        })
        .collect();
    let mut out = String::from("#");
    for channel in adjusted {
        out.push_str(&format!("{:02x}", channel.clamp(0, 255)));
    }
    out
}

/// The tint/shade/lumMod/lumOff brightness of a colour node. `Err` for an
/// unreadable value (callers treat it as no transform; v3's text colours
/// raised and lost the shape).
fn brightness_of(node: Nd<'_>) -> Result<f64, Skip> {
    let value =
        |n: Nd<'_>, default: &str| py_int(n.attribute("val").unwrap_or(default)).ok_or(Skip);
    if let Some(tint) = child(node, "tint") {
        return Ok((value(tint, "0")? as f64 / 100000.0).clamp(0.0, 1.0));
    }
    if let Some(shade) = child(node, "shade") {
        return Ok((value(shade, "100000")? as f64 / 100000.0 - 1.0).clamp(-1.0, 0.0));
    }
    let modulation = child(node, "lumMod");
    let offset = child(node, "lumOff");
    if modulation.is_some() || offset.is_some() {
        let modulation = match modulation {
            Some(n) => value(n, "100000")? as f64 / 100000.0,
            None => 1.0,
        };
        let offset = match offset {
            Some(n) => value(n, "0")? as f64 / 100000.0,
            None => 0.0,
        };
        return Ok(if offset != 0.0 {
            offset
        } else {
            modulation - 1.0
        });
    }
    Ok(0.0)
}

/// v3 `_xml_drawing_color_css`; `Err` where v3 raised (a bad transform value).
pub(super) fn drawing_color(
    node: Option<Nd<'_>>,
    palette: &Palette,
) -> Result<Option<String>, Skip> {
    let Some(node) = node else {
        return Ok(None);
    };
    let color = match local(node) {
        "srgbClr" => css_color(node.attribute("val"), "transparent"),
        "sysClr" => css_color(node.attribute("lastClr"), "transparent"),
        "schemeClr" => palette
            .get(node.attribute("val").unwrap_or(""))
            .cloned()
            .unwrap_or_else(|| "transparent".into()),
        _ => "transparent".into(),
    };
    if color == "transparent" {
        return Ok(None);
    }
    // Fix over v3: an unreadable tint/shade value raised and lost the shape;
    // it reads as no transform (as v3 already did for shape fills).
    Ok(Some(apply_brightness(
        &color,
        brightness_of(node).unwrap_or(0.0),
    )))
}

/// v3 `_xml_color_css`: the colour of an element's `a:solidFill`.
pub(super) fn solid_fill_color(
    element: Option<Nd<'_>>,
    palette: &Palette,
) -> Result<Option<String>, Skip> {
    let Some(fill) = element.and_then(|e| child(e, "solidFill")) else {
        return Ok(None);
    };
    drawing_color(first_child(Some(fill)), palette)
}

/// v3 `_shape_xml_color_css`: theme transforms, `phClr` and alpha.
pub(super) fn shape_color(
    node: Option<Nd<'_>>,
    palette: &Palette,
    placeholder: Option<&str>,
    default_alpha: f64,
) -> Option<String> {
    let node = node?;
    let color = match local(node) {
        "srgbClr" => Some(css_color(node.attribute("val"), "transparent")),
        "sysClr" => Some(css_color(node.attribute("lastClr"), "transparent")),
        "schemeClr" => {
            let key = node.attribute("val").unwrap_or("");
            if key == "phClr" {
                placeholder.map(str::to_string)
            } else {
                let alias = match key {
                    "lt1" => "bg1",
                    "dk1" => "tx1",
                    "lt2" => "bg2",
                    "dk2" => "tx2",
                    _ => "",
                };
                palette
                    .get(key)
                    .filter(|v| !v.is_empty())
                    .or_else(|| palette.get(alias))
                    .cloned()
            }
        }
        _ => None,
    };
    let color = color.filter(|c| !c.is_empty() && c != "transparent")?;
    let brightness = brightness_of(node).unwrap_or(0.0);
    let color = apply_brightness(&color, brightness);
    let mut alpha = default_alpha;
    if let Some(node) = child(node, "alpha") {
        alpha = match py_int(node.attribute("val").unwrap_or("100000")) {
            Some(v) => (v as f64 / 100000.0).clamp(0.0, 1.0),
            None => default_alpha,
        };
    }
    if alpha >= 0.999 || !color.starts_with('#') {
        return Some(color);
    }
    let channel = |i: usize| {
        color
            .get(i..i + 2)
            .and_then(|h| i64::from_str_radix(h, 16).ok())
    };
    match (channel(1), channel(3), channel(5)) {
        (Some(r), Some(g), Some(b)) => Some(format!("rgba({r},{g},{b},{})", f(alpha, 3))),
        _ => Some(color),
    }
}

/// v3 `_slide_background`: the first explicit colour of slide, layout, master.
pub(super) fn slide_background(ctx: &SlideCtx<'_>) -> String {
    for root in [ctx.slide_root, ctx.layout_root, ctx.master_root] {
        let Some(background) =
            child_ns(root, super::util::P, "cSld").and_then(|c| child_ns(c, super::util::P, "bg"))
        else {
            continue;
        };
        for (tag, attribute) in [("srgbClr", "val"), ("sysClr", "lastClr")] {
            if let Some(node) = descendants_ns(background, A, tag).next() {
                let color = css_color(node.attribute(attribute), "transparent");
                if color != "transparent" {
                    return color;
                }
            }
        }
        if let Some(scheme) = descendants_ns(background, A, "schemeClr").next() {
            return ctx
                .palette
                .get(scheme.attribute("val").unwrap_or(""))
                .cloned()
                .unwrap_or_else(|| "#ffffff".into());
        }
    }
    "#ffffff".into()
}

/// python-pptx `ST_Percentage` (`"75000"` or `"75%"`).
fn st_percentage(raw: &str) -> Option<f64> {
    if raw.contains('%') {
        return super::util::py_float(super::util::drop_last(raw)).map(|v| v / 100.0);
    }
    py_int(raw).map(|v| v as f64 / 100000.0)
}

/// v3 `_pptx_color(color_format, palette)` for a python-pptx `ColorFormat`
/// over the colour-choice element `color` (chart series colours). `None`
/// where v3 raised.
pub(super) fn color_format_css(color: Option<Nd<'_>>, palette: &Palette) -> Option<String> {
    let Some(node) = color else {
        return Some("transparent".into());
    };
    let base = match local(node) {
        "srgbClr" => {
            // `str(RGBColor)` is upper-case hex.
            let raw = node.attribute("val").unwrap_or("");
            let valid = raw.len() == 6 && raw.chars().all(|c| c.is_ascii_hexdigit());
            if valid {
                format!("#{}", raw.to_ascii_uppercase())
            } else {
                "transparent".into()
            }
        }
        "schemeClr" => {
            let key = node.attribute("val").unwrap_or("");
            const THEME: [&str; 16] = [
                "dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5",
                "accent6", "hlink", "folHlink", "bg1", "tx1", "bg2", "tx2",
            ];
            if !THEME.contains(&key) {
                // MSO_THEME_COLOR has no member for this value: python-pptx raised.
                return None;
            }
            palette
                .get(key)
                .cloned()
                .unwrap_or_else(|| "transparent".into())
        }
        _ => "transparent".into(),
    };
    let modulation = child(node, "lumMod");
    let offset = child(node, "lumOff");
    let brightness = if let Some(offset) = offset {
        offset.attribute("val").and_then(st_percentage)
    } else if let Some(modulation) = modulation {
        modulation
            .attribute("val")
            .and_then(st_percentage)
            .map(|v| v - 1.0)
    } else {
        Some(0.0)
    };
    Some(apply_brightness(&base, brightness.unwrap_or(0.0)))
}
