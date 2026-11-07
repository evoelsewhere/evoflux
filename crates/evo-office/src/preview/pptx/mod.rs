//! PPTX → HTML (v3 `service.py` `_render_pptx` and its helpers).
//!
//! v3 read decks through python-pptx; this port reads the same XML and keeps
//! python-pptx's semantics where the output depends on them:
//!
//! - slides follow `p:sldIdLst`; their partnames are renumbered
//!   `/ppt/slides/slideN.xml` in that order (python-pptx renames slide parts),
//!   which feeds the SVG ids derived from partnames;
//! - each slide composites its master's and layout's non-placeholder shapes
//!   under its own shapes; `mc:AlternateContent` shows its `Fallback`;
//! - a slide placeholder without its own position inherits the layout
//!   placeholder's (same `idx`), which inherits the master's (same type);
//! - text styles resolve through the shape, the matching layout and master
//!   placeholders and the master's `p:txStyles`;
//! - charts read python-pptx's view: chart type from the first plot, series
//!   in `c:order` order, cached values, the second value axis of a scatter;
//! - SmartArt renders the drawing PowerPoint cached in `ppt/diagrams/`.
//!
//! Every shape renders inside its own error boundary: a shape v3 would have
//! failed on is skipped, never the deck.
//!
//! Where v3 had a clear bug the port fixes it (each marked "Fix over v3" at
//! the code): list styles (`a:lstStyle`) apply; subtitles inherit the body
//! style; field text appears once; scatter data labels and automatic
//! (diamond) markers draw; placeholders whose inherited position or text
//! style python-pptx could not resolve are kept; charts with an unexpected
//! grouping, missing required children or non-finite values render; and
//! malformed shapes no longer fail the whole deck.

mod chart;
mod color;
mod fill;
mod model;
mod shapes;
mod skeleton;
mod table;
mod text;
mod util;

use std::borrow::Cow;
use std::collections::HashMap;

use roxmltree::Document;

use super::html::{escape, page, parse_xml};
use super::live::read_plan;
use super::{DeckPlan, Package, PreviewError};
use color::{slide_background, theme_fonts, theme_palette};
use fill::Coords;
use model::{ph, ph_idx, ph_type, placeholders, sp_tree, Deck, Origin, Shape, SlideCtx};
use shapes::{render_shape, tree_shapes};
use text::text_frame_text;
use util::{child_ns, elements, local, py_int, py_strip, r_attr, split_join, Nd, P};

const DIAGRAM_DRAWING_NS: &str = "http://schemas.microsoft.com/office/drawing/2008/diagram";
const PRESENTATION_NS: &str = "http://schemas.openxmlformats.org/presentationml/2006/main";

/// Decode an XML part like lxml would: UTF-8 (BOM stripped) or UTF-16 by BOM.
fn decode(bytes: &[u8]) -> Cow<'_, str> {
    if let Some(rest) = bytes.strip_prefix(b"\xEF\xBB\xBF") {
        return String::from_utf8_lossy(rest);
    }
    let utf16 = |rest: &[u8], little: bool| {
        let units: Vec<u16> = rest
            .chunks_exact(2)
            .map(|c| {
                if little {
                    u16::from_le_bytes([c[0], c[1]])
                } else {
                    u16::from_be_bytes([c[0], c[1]])
                }
            })
            .collect();
        Cow::Owned(String::from_utf16_lossy(&units))
    };
    if let Some(rest) = bytes.strip_prefix(b"\xFF\xFE") {
        return utf16(rest, true);
    }
    if let Some(rest) = bytes.strip_prefix(b"\xFE\xFF") {
        return utf16(rest, false);
    }
    String::from_utf8_lossy(bytes)
}

/// Drop the XML declaration of a re-encoded part (roxmltree rejects an
/// `encoding` that no longer matches).
fn strip_declaration(text: &str) -> &str {
    let trimmed = text.trim_start_matches('\u{feff}');
    if trimmed.starts_with("<?xml") {
        if let Some(end) = trimmed.find("?>") {
            return &trimmed[end + 2..];
        }
    }
    trimmed
}

fn is_deck_xml(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    lower.starts_with("ppt/")
        && (lower.ends_with(".xml") || lower.ends_with(".rels"))
        && !lower.starts_with("ppt/embeddings/")
}

pub fn render(
    package: &Package,
    title: &str,
    live: Option<&DeckPlan>,
) -> Result<String, PreviewError> {
    // The XML text of every deck part, then each parsed once.
    let texts: HashMap<String, Cow<'_, str>> = package
        .names()
        .filter(|n| is_deck_xml(n) && n.to_ascii_lowercase().ends_with(".xml"))
        .filter_map(|n| package.bytes(n).map(|b| (n.to_string(), decode(b))))
        .collect();
    let smart_texts: HashMap<String, String> = texts
        .iter()
        .filter(|(_, text)| text.contains(DIAGRAM_DRAWING_NS))
        .map(|(name, text)| {
            (
                name.clone(),
                text.replace(DIAGRAM_DRAWING_NS, PRESENTATION_NS),
            )
        })
        .collect();
    let docs: HashMap<String, Document<'_>> = texts
        .iter()
        .filter_map(|(name, text)| {
            parse_xml(strip_declaration(text))
                .ok()
                .map(|d| (name.clone(), d))
        })
        .collect();
    let smart: HashMap<String, Document<'_>> = smart_texts
        .iter()
        .filter_map(|(name, text)| {
            parse_xml(strip_declaration(text))
                .ok()
                .map(|d| (name.clone(), d))
        })
        .collect();

    let presentation_part = package
        .rel_of_kind("", "officeDocument")
        .map(|r| r.target)
        .unwrap_or_else(|| "ppt/presentation.xml".to_string());
    let failed = |message: &str| PreviewError::failed(message.to_string());
    let presentation = docs
        .get(&presentation_part)
        .map(Document::root_element)
        .ok_or_else(|| failed("Could not read this presentation."))?;
    let size = child_ns(presentation, P, "sldSz");
    let dimension = |name: &str| {
        size.and_then(|s| s.attribute(name))
            .and_then(py_int)
            .unwrap_or(0)
    };
    let (slide_width, slide_height) = (dimension("cx"), dimension("cy"));
    if slide_width <= 0 || slide_height <= 0 {
        return Err(failed("Presentation has invalid slide dimensions"));
    }
    // A live render re-reads the plan: the deck is live until it says done.
    let plan = if live.is_some() {
        read_plan(package)
    } else {
        None
    };
    let is_live = plan.as_ref().is_some_and(|p| !p.done);

    let mut slide_parts = Vec::new();
    if let Some(list) = child_ns(presentation, P, "sldIdLst") {
        for entry in elements(list).filter(|e| local(*e) == "sldId") {
            let rid =
                r_attr(entry, "id").ok_or_else(|| failed("Could not read this presentation."))?;
            let target = package
                .rel(&presentation_part, rid)
                .filter(|r| !r.external)
                .map(|r| r.target)
                .ok_or_else(|| failed("Could not read this presentation."))?;
            slide_parts.push(target);
        }
    }
    let mut partnames: HashMap<String, String> = package
        .names()
        .map(|n| (n.to_string(), format!("/{n}")))
        .collect();
    for (index, part) in slide_parts.iter().enumerate() {
        partnames.insert(part.clone(), format!("/ppt/slides/slide{}.xml", index + 1));
    }
    let deck = Deck {
        pkg: package,
        docs: &docs,
        smart: &smart,
        partnames,
    };

    let status_attribute = if is_live {
        " data-slide-status=\"done\""
    } else {
        ""
    };
    let ratio = format!("{slide_width}/{slide_height}");
    let mut rendered = Vec::new();
    for (index, slide_part) in slide_parts.iter().enumerate() {
        let number = index + 1;
        let ctx = slide_context(&deck, slide_part, slide_width, slide_height)?;
        let shapes = render_slide_shapes(&ctx);
        let background = slide_background(&ctx);
        let slide_title = slide_preview_title(&ctx);
        let label = if slide_title.is_empty() {
            format!("Slide {number}")
        } else {
            format!("Slide {number} \u{2014} {slide_title}")
        };
        let notes = slide_notes_text(&ctx);
        let notes_metadata = if notes.is_empty() {
            String::new()
        } else {
            let escaped = escape(&notes);
            format!("<span class=\"slide-notes-metadata\" hidden aria-hidden=\"true\" data-preview-notes=\"{escaped}\">{escaped}</span>")
        };
        // The newest finished slide of a live deck lands with a short animation.
        let fresh = if is_live && number == slide_parts.len() {
            " data-slide-fresh"
        } else {
            ""
        };
        rendered.push(format!(
            "<article class=\"slide-wrap\" data-preview-item data-preview-label=\"{}\" data-preview-title=\"{}\"{status_attribute}{fresh}><div class=\"slide-number\">{number}</div><section class=\"slide\" style=\"aspect-ratio:{ratio};background:{background}\">{}</section>{notes_metadata}</article>",
            escape(&label),
            escape(&slide_title),
            shapes.concat()
        ));
    }
    if let (true, Some(plan)) = (is_live, plan.as_ref()) {
        let first = rendered.len();
        rendered.extend(skeleton::pending_slide_skeletons(plan, first, &ratio));
    }
    let mut css = skeleton::DECK_CSS.to_string();
    let mut body = rendered.concat();
    if is_live {
        css.push_str(skeleton::LIVE_SLIDE_CSS);
        body = format!("<main data-deck-live=\"true\">{body}</main>");
    }
    Ok(page(title, &body, &css))
}

/// slide → layout → master → theme, with the theme's palette and fonts.
fn slide_context<'a>(
    deck: &'a Deck<'a>,
    slide_part: &str,
    slide_width: i64,
    slide_height: i64,
) -> Result<SlideCtx<'a>, PreviewError> {
    let broken = || PreviewError::failed("Could not read this presentation.");
    let slide_part = deck.key(slide_part).ok_or_else(broken)?;
    let layout = deck
        .related_of_kind(slide_part, "slideLayout")
        .ok_or_else(broken)?;
    let layout_part = deck.key(&layout).ok_or_else(broken)?;
    let master = deck
        .related_of_kind(layout_part, "slideMaster")
        .ok_or_else(broken)?;
    let master_part = deck.key(&master).ok_or_else(broken)?;
    let theme = deck
        .pkg
        .rels(master_part)
        .into_iter()
        .find(|r| r.rel_type.ends_with("/theme"))
        .and_then(|r| deck.root(&r.target));
    Ok(SlideCtx {
        deck,
        slide_part,
        layout_part,
        master_part,
        slide_root: deck.root(slide_part).ok_or_else(broken)?,
        layout_root: deck.root(layout_part).ok_or_else(broken)?,
        master_root: deck.root(master_part).ok_or_else(broken)?,
        theme,
        palette: theme_palette(theme),
        fonts: theme_fonts(theme),
        slide_width,
        slide_height,
    })
}

/// v3 `_placeholder_key(shape) is None`.
fn not_placeholder(shape: &Shape<'_>) -> bool {
    match shape.ph() {
        None => true,
        Some(ph) => ph_idx(ph).is_err(),
    }
}

/// v3 `_composite_slide_shapes`.
fn composite_slide_shapes<'a>(ctx: &SlideCtx<'a>) -> Vec<(&'static str, Shape<'a>)> {
    let mut result = Vec::new();
    // A layout's own autoshape placeholders are python-pptx
    // `LayoutPlaceholder`s (they inherit the master's position); those drawn
    // here are the ones whose `idx` does not read.
    for (layer, root, part, origin) in [
        ("master", ctx.master_root, ctx.master_part, Origin::Plain),
        (
            "layout",
            ctx.layout_root,
            ctx.layout_part,
            Origin::LayoutPlaceholder,
        ),
    ] {
        if let Some(tree) = sp_tree(root) {
            result.extend(
                tree_shapes(tree, part, origin)
                    .into_iter()
                    .filter(not_placeholder)
                    .map(|s| (layer, s)),
            );
        }
    }
    if let Some(tree) = sp_tree(ctx.slide_root) {
        result.extend(
            tree_shapes(tree, ctx.slide_part, Origin::SlideTop)
                .into_iter()
                .map(|s| ("slide", s)),
        );
    }
    result
}

/// v3 `_render_slide_shapes`: one failing shape is skipped.
fn render_slide_shapes(ctx: &SlideCtx<'_>) -> Vec<String> {
    let mut rendered = Vec::new();
    for (layer, shape) in composite_slide_shapes(ctx) {
        match render_shape(ctx, &shape, layer, Coords::default()) {
            Ok(html) => rendered.push(html),
            Err(_) => tracing::warn!(name = shape.name(), "document_preview_pptx_shape_skipped"),
        }
    }
    rendered
}

/// Direct members of the slide's shape tree (`slide.shapes`).
fn slide_shape_nodes<'a>(ctx: &SlideCtx<'a>) -> Vec<Nd<'a>> {
    const TAGS: [&str; 6] = ["sp", "grpSp", "graphicFrame", "cxnSp", "pic", "contentPart"];
    sp_tree(ctx.slide_root)
        .map(|tree| {
            elements(tree)
                .filter(|e| e.tag_name().namespace() == Some(P) && TAGS.contains(&local(*e)))
                .collect()
        })
        .unwrap_or_default()
}

/// v3 `_slide_preview_title`.
fn slide_preview_title(ctx: &SlideCtx<'_>) -> String {
    let nodes = slide_shape_nodes(ctx);
    let mut candidates: Vec<Nd<'_>> = Vec::new();
    // `slide.shapes.title`: the first placeholder with idx 0.
    for node in &nodes {
        let Some(ph) = ph(*node) else { continue };
        match ph_idx(ph) {
            Ok(0) => {
                candidates.push(*node);
                break;
            }
            Ok(_) => {}
            Err(_) => break,
        }
    }
    let shape_name = |node: Nd<'_>| {
        model::c_nv_pr(node)
            .and_then(|c| c.attribute("name"))
            .unwrap_or("")
            .to_lowercase()
    };
    for node in &nodes {
        if !candidates.contains(node) && shape_name(*node).contains("[role:title]") {
            candidates.push(*node);
        }
    }
    for node in &nodes {
        if !candidates.contains(node) {
            candidates.push(*node);
        }
    }
    for node in candidates {
        if local(node) != "sp" {
            continue;
        }
        let tx_body = elements(node).find(|e| local(*e) == "txBody");
        let title = split_join(&text_frame_text(tx_body));
        if !title.is_empty() {
            return title.chars().take(160).collect();
        }
    }
    String::new()
}

/// v3 `_slide_notes_text`.
fn slide_notes_text(ctx: &SlideCtx<'_>) -> String {
    let Some(notes) = ctx.deck.related_of_kind(ctx.slide_part, "notesSlide") else {
        return String::new();
    };
    let Some(root) = ctx.deck.root(&notes) else {
        return String::new();
    };
    for node in placeholders(root) {
        let Some(ph) = ph(node) else { continue };
        match ph_type(ph) {
            Ok("BODY") => {
                if local(node) != "sp" {
                    return String::new();
                }
                let tx_body = elements(node).find(|e| local(*e) == "txBody");
                return py_strip(&text_frame_text(tx_body)).to_string();
            }
            Ok(_) => {}
            Err(_) => return String::new(),
        }
    }
    String::new()
}
