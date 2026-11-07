//! One shape to HTML (v3 `_render_pptx_shape`): groups and their coordinate
//! systems, connectors, pictures, tables, charts, SmartArt, embedded objects,
//! text shapes and vector shapes.

use base64::Engine as _;

use super::super::html::escape;
use super::chart::{chart_svg, chart_title};
use super::fill::{
    connector_svg, identity, preset_clip_css, preset_geometry_name, shape_box, surface_svg,
    text_container_attributes, Coords,
};
use super::model::{blip_rid, Dim, Origin, Shape, SlideCtx};
use super::text::{shape_text, text_frame_text};
use super::util::{
    child, descendant, descendants, elements, f, local, path, percent_of, py_float, py_int,
    py_strip, r_attr, Nd, P, R,
};

const URI_CHART: &str = "http://schemas.openxmlformats.org/drawingml/2006/chart";
const URI_TABLE: &str = "http://schemas.openxmlformats.org/drawingml/2006/table";
const SHAPE_ELEMENTS: [&str; 5] = ["sp", "pic", "grpSp", "graphicFrame", "cxnSp"];
const BROWSER_IMAGE_TYPES: [&str; 6] = [
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/svg+xml",
];

/// v3 `_shape_elements`: shape elements in z-order, `mc:AlternateContent`
/// resolved to its `Fallback` (else `Choice`) branch.
pub(super) fn shape_elements<'a>(element: Nd<'a>, out: &mut Vec<Nd<'a>>) {
    for item in elements(element) {
        let name = local(item);
        if SHAPE_ELEMENTS.contains(&name) {
            out.push(item);
        } else if name == "AlternateContent" {
            let mut fallback = None;
            let mut choice = None;
            for branch in elements(item) {
                match local(branch) {
                    "Fallback" => fallback = Some(branch),
                    "Choice" => choice = Some(branch),
                    _ => {}
                }
            }
            if let Some(branch) = fallback.or(choice) {
                shape_elements(branch, out);
            }
        }
    }
}

/// v3 `_tree_shapes` for a shape tree (or group) element.
pub(super) fn tree_shapes<'a>(tree: Nd<'a>, part: &'a str, origin: Origin) -> Vec<Shape<'a>> {
    let mut nodes = Vec::new();
    shape_elements(tree, &mut nodes);
    nodes
        .into_iter()
        .map(|node| Shape { node, part, origin })
        .collect()
}

/// v3 `_group_coordinate_system`.
fn group_coordinate_system(ctx: &SlideCtx<'_>, shape: &Shape<'_>) -> R<(i64, i64, i64, i64)> {
    let transform = child(shape.node, "grpSpPr").and_then(|p| child(p, "xfrm"));
    if let Some(transform) = transform {
        if let (Some(offset), Some(extent)) = (child(transform, "chOff"), child(transform, "chExt"))
        {
            let parsed = (
                py_int(offset.attribute("x").unwrap_or("0")),
                py_int(offset.attribute("y").unwrap_or("0")),
                py_int(extent.attribute("cx").unwrap_or("1")),
                py_int(extent.attribute("cy").unwrap_or("1")),
            );
            if let (Some(x), Some(y), Some(cx), Some(cy)) = parsed {
                return Ok((x, y, cx.max(1), cy.max(1)));
            }
        }
    }
    // Fix over v3 (raised, lost the group): a group without a size keeps its
    // children in slide coordinates.
    let width = shape.dim(ctx, Dim::Width)?.unwrap_or(ctx.slide_width);
    let height = shape.dim(ctx, Dim::Height)?.unwrap_or(ctx.slide_height);
    Ok((0, 0, width.max(1), height.max(1)))
}

fn group_html(
    identity: &str,
    coords: (i64, i64, i64, i64),
    box_style: &str,
    children: &str,
) -> String {
    let (left, top, width, height) = coords;
    format!(
        "<div class=\"shape shape-group\" {identity} data-coordinate-left=\"{left}\" data-coordinate-top=\"{top}\" data-coordinate-width=\"{width}\" data-coordinate-height=\"{height}\" style=\"{box_style}\">{children}</div>"
    )
}

fn render_children(
    ctx: &SlideCtx<'_>,
    children: &[Shape<'_>],
    layer: &str,
    system: (i64, i64, i64, i64),
) -> R<String> {
    let coords = Coords {
        left: system.0,
        top: system.1,
        width: Some(system.2),
        height: Some(system.3),
    };
    let mut html = String::new();
    for item in children {
        html.push_str(&render_shape(ctx, item, layer, coords)?);
    }
    Ok(html)
}

/// python-pptx `ST_Percentage` for crop values.
fn crop_value(raw: Option<&str>) -> f64 {
    let Some(raw) = raw else {
        return 0.0;
    };
    let value = if raw.contains('%') {
        py_float(super::util::drop_last(raw)).map(|v| v / 100.0)
    } else {
        py_int(raw).map(|v| v as f64 / 100000.0)
    };
    value.unwrap_or(0.0)
}

/// v3 `_picture_data_uri`.
fn picture_data_uri(ctx: &SlideCtx<'_>, shape: &Shape<'_>) -> Option<String> {
    let rid = blip_rid(shape.node)?;
    let target = ctx.deck.related(shape.part, rid)?;
    let bytes = ctx.deck.pkg.bytes(&target)?;
    let file = target.rsplit('/').next().unwrap_or(&target);
    let extension = match file.rfind('.') {
        Some(i) if i + 1 < file.len() => file[i + 1..].to_lowercase(),
        _ => "png".to_string(),
    };
    let mime = match extension.as_str() {
        "jpg" | "jpeg" => "image/jpeg".to_string(),
        "gif" => "image/gif".to_string(),
        "webp" => "image/webp".to_string(),
        "svg" => "image/svg+xml".to_string(),
        _ => ctx
            .deck
            .pkg
            .content_type(&target)
            .unwrap_or_else(|| "image/png".into()),
    };
    Some(format!(
        "data:{mime};base64,{}",
        base64::engine::general_purpose::STANDARD.encode(bytes)
    ))
}

/// v3 `_render_picture`.
fn render_picture(ctx: &SlideCtx<'_>, shape: &Shape<'_>, layer: &str, coords: Coords) -> R<String> {
    // Fix over v3 (raised): a picture without `p:blipFill` is a missing image.
    let source_rect = child(shape.node, "blipFill").and_then(|b| child(b, "srcRect"));
    let crop = |name: &str| crop_value(source_rect.and_then(|r| r.attribute(name)));
    let (left_crop, right_crop, top_crop, bottom_crop) =
        (crop("l"), crop("r"), crop("t"), crop("b"));
    let visible_width = (1.0 - left_crop - right_crop).max(0.0001);
    let visible_height = (1.0 - top_crop - bottom_crop).max(0.0001);
    let image_left = -left_crop / visible_width * 100.0;
    let image_top = -top_crop / visible_height * 100.0;
    let image_width = 100.0 / visible_width;
    let image_height = 100.0 / visible_height;
    let preset = preset_geometry_name(shape);
    let mut styles = vec![shape_box(ctx, shape, coords)?];
    if let Some(clip) = preset_clip_css(&preset) {
        styles.push(format!("clip-path:{clip}"));
    }
    let identity = identity(shape, layer)?;
    let crop_attributes = format!(
        "data-crop-left=\"{}\" data-crop-right=\"{}\" data-crop-top=\"{}\" data-crop-bottom=\"{}\" data-preset-geometry=\"{}\"",
        f(left_crop, 5),
        f(right_crop, 5),
        f(top_crop, 5),
        f(bottom_crop, 5),
        escape(&preset)
    );
    let image_style = format!(
        "left:{}%;top:{}%;width:{}%;height:{}%;object-fit:fill",
        f(image_left, 4),
        f(image_top, 4),
        f(image_width, 4),
        f(image_height, 4)
    );
    let alt = child(shape.node, "nvPicPr")
        .and_then(|nv| child(nv, "cNvPr"))
        .map(|c| {
            c.attribute("descr")
                .filter(|d| !d.is_empty())
                .or_else(|| c.attribute("title"))
                .unwrap_or("")
        })
        .unwrap_or("");
    let image = match picture_data_uri(ctx, shape) {
        Some(uri) => format!(
            "<img class=\"picture\" src=\"{uri}\" alt=\"{}\" style=\"{image_style}\" draggable=\"false\">",
            escape(alt)
        ),
        None => "<span class=\"picture-missing\" aria-hidden=\"true\"></span>".to_string(),
    };
    Ok(format!(
        "<div class=\"shape picture-frame\" {identity} {crop_attributes} style=\"{}\">{image}</div>",
        styles.join(";")
    ))
}

/// v3 `_part_data_uri`.
fn part_data_uri(ctx: &SlideCtx<'_>, part: &str) -> Option<String> {
    let content_type = ctx
        .deck
        .pkg
        .content_type(part)
        .unwrap_or_default()
        .to_lowercase();
    if !BROWSER_IMAGE_TYPES.contains(&content_type.as_str()) {
        return None;
    }
    let bytes = ctx.deck.pkg.bytes(part)?;
    Some(format!(
        "data:{content_type};base64,{}",
        base64::engine::general_purpose::STANDARD.encode(bytes)
    ))
}

/// v3 `_graphic_frame_fallback`: an OLE object's preview picture, else a
/// labelled placeholder.
fn graphic_frame_fallback(
    ctx: &SlideCtx<'_>,
    frame: &Shape<'_>,
    identity: &str,
    box_style: &str,
) -> String {
    let ole = descendant(frame.node, "oleObj");
    let prog_id = ole.and_then(|o| o.attribute("progId")).unwrap_or("");
    for blip in descendants(frame.node, "blip") {
        let Some(rid) = r_attr(blip, "embed").filter(|r| !r.is_empty()) else {
            continue;
        };
        let source = ctx
            .deck
            .related(frame.part, rid)
            .and_then(|target| part_data_uri(ctx, &target));
        if let Some(source) = source {
            let alt = if !prog_id.is_empty() {
                prog_id
            } else if !frame.name().is_empty() {
                frame.name()
            } else {
                "Embedded object"
            };
            return format!(
                "<div class=\"shape picture-frame embedded-object\" {identity} style=\"{box_style}\"><img class=\"picture\" alt=\"{}\" src=\"{source}\" style=\"left:0;top:0;width:100%;height:100%\"></div>",
                escape(alt)
            );
        }
    }
    let label = if ole.is_some() {
        "Embedded object"
    } else {
        "Unsupported object"
    };
    let detail = escape(if prog_id.is_empty() {
        frame.name()
    } else {
        prog_id
    });
    tracing::debug!(
        name = frame.name(),
        prog_id,
        "document_preview_pptx_object_placeholder"
    );
    let small = if detail.is_empty() {
        String::new()
    } else {
        format!("<small>{detail}</small>")
    };
    format!("<div class=\"shape object-placeholder\" {identity} style=\"{box_style}\"><span>{label}</span>{small}</div>")
}

/// v3 `_diagram_drawing_part`: the drawing PowerPoint cached for a SmartArt frame.
fn diagram_drawing_part(ctx: &SlideCtx<'_>, frame: &Shape<'_>) -> Option<String> {
    let relation_ids = descendant(frame.node, "relIds")?;
    let deck = ctx.deck;
    let mut drawing_rid = None;
    if let Some(data_rid) = r_attr(relation_ids, "dm").filter(|r| !r.is_empty()) {
        if let Some(root) = deck
            .related(frame.part, data_rid)
            .and_then(|target| deck.root(&target))
        {
            drawing_rid = descendant(root, "dataModelExt")
                .and_then(|e| e.attribute("relId"))
                .map(str::to_string);
        }
    }
    if let Some(rid) = drawing_rid.filter(|r| !r.is_empty()) {
        if let Some(target) = deck.related(frame.part, &rid) {
            return Some(target);
        }
    }
    let drawings: Vec<String> = deck
        .pkg
        .rels(frame.part)
        .into_iter()
        .filter(|r| r.rel_type.ends_with("/diagramDrawing") && !r.external)
        .map(|r| r.target)
        .collect();
    if drawings.len() == 1 {
        drawings.into_iter().next()
    } else {
        None
    }
}

/// v3 `_smartart_group`: the cached SmartArt drawing as a group whose child
/// coordinate space is the frame.
fn smartart_group(
    ctx: &SlideCtx<'_>,
    frame: &Shape<'_>,
    layer: &str,
    coords: Coords,
) -> R<Option<String>> {
    let Some(drawing) = diagram_drawing_part(ctx, frame) else {
        return Ok(None);
    };
    let Some(doc) = ctx.deck.smart.get(&drawing) else {
        return Ok(None);
    };
    let root = doc.root_element();
    let Some(tree) =
        elements(root).find(|e| local(*e) == "spTree" && e.tag_name().namespace() == Some(P))
    else {
        return Ok(None);
    };
    let members: Vec<Shape<'_>> = elements(tree)
        .filter(|e| matches!(local(*e), "sp" | "grpSp"))
        .map(|node| Shape {
            node,
            part: frame.part,
            origin: Origin::Plain,
        })
        .collect();
    if members.is_empty() {
        return Ok(None);
    }
    let left = frame.dim0(ctx, Dim::Left)?;
    let top = frame.dim0(ctx, Dim::Top)?;
    let width = frame.dim0(ctx, Dim::Width)?.max(1);
    let height = frame.dim0(ctx, Dim::Height)?.max(1);
    let shape_id = frame.shape_id()?;
    let name = escape(frame.name());
    let identity = format!(
        "data-shape-id=\"{shape_id}\" data-shape-name=\"{name}\" data-qa-label=\"{}\" data-source-layer=\"{layer}\"",
        if name.is_empty() { &shape_id } else { &name }
    );
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
    let box_style = format!(
        "left:{}%;top:{}%;width:{}%;height:{}%",
        f(percent_of(left.saturating_sub(coords.left), width_basis), 3),
        f(percent_of(top.saturating_sub(coords.top), height_basis), 3),
        f(percent_of(width, width_basis), 3),
        f(percent_of(height, height_basis), 3)
    );
    let system = (0, 0, width, height);
    let children = render_children(ctx, &members, layer, system)?;
    Ok(Some(group_html(&identity, system, &box_style, &children)))
}

/// `a:graphic/a:graphicData/@uri` of a graphic frame. Fix over v3 (raised,
/// lost the frame): a frame without one is an unsupported object.
fn graphic_data_uri<'a>(frame: &Shape<'a>) -> R<&'a str> {
    Ok(path(frame.node, &["graphic", "graphicData"])
        .and_then(|g| g.attribute("uri"))
        .unwrap_or(""))
}

/// v3 `_render_pptx_shape`.
pub(super) fn render_shape(
    ctx: &SlideCtx<'_>,
    shape: &Shape<'_>,
    layer: &str,
    coords: Coords,
) -> R<String> {
    let tag = shape.tag();
    match tag {
        "grpSp" => {
            let box_style = shape_box(ctx, shape, coords)?;
            let system = group_coordinate_system(ctx, shape)?;
            let children = tree_shapes(shape.node, shape.part, Origin::Plain);
            let html = render_children(ctx, &children, layer, system)?;
            return Ok(group_html(
                &identity(shape, layer)?,
                system,
                &box_style,
                &html,
            ));
        }
        "cxnSp" => return connector_svg(ctx, shape, layer, coords),
        "pic" => return render_picture(ctx, shape, layer, coords),
        _ => {}
    }
    let uri = if tag == "graphicFrame" {
        Some(graphic_data_uri(shape)?)
    } else {
        None
    };
    if uri == Some(URI_TABLE) {
        return super::table::render_table(ctx, shape, layer, coords);
    }
    let box_style = shape_box(ctx, shape, coords)?;
    let identity = identity(shape, layer)?;
    let preset = preset_geometry_name(shape);
    let geometry = format!("data-preset-geometry=\"{}\"", escape(&preset));
    if uri == Some(URI_CHART) {
        // Fix over v3 (raised, lost the frame): a chart whose part is missing
        // or unreadable shows "Chart data unavailable".
        let space = path(shape.node, &["graphic", "graphicData", "chart"])
            .and_then(|c| r_attr(c, "id"))
            .and_then(|rid| ctx.deck.related(shape.part, rid))
            .and_then(|part| ctx.deck.root(&part));
        let Some(space) = space else {
            return Ok(format!(
                "<div class=\"shape chart\" {identity} style=\"{box_style}\"><div class=\"chart-empty\">Chart data unavailable</div></div>"
            ));
        };
        let title = chart_title(space);
        let title_html = if title.is_empty() {
            String::new()
        } else {
            format!("<strong class=\"chart-title\">{}</strong>", escape(&title))
        };
        let chart_aspect = match (shape.dim(ctx, Dim::Width)?, shape.dim(ctx, Dim::Height)?) {
            (Some(width), Some(height)) => width as f64 / (height as f64).max(1.0),
            _ => 2.0,
        };
        let svg = chart_svg(space, &ctx.palette, chart_aspect)?;
        return Ok(format!(
            "<div class=\"shape chart\" {identity} style=\"{box_style}\">{title_html}{svg}</div>"
        ));
    }
    if tag == "graphicFrame" {
        if let Some(group) = smartart_group(ctx, shape, layer, coords)? {
            return Ok(group);
        }
        return Ok(graphic_frame_fallback(ctx, shape, &identity, &box_style));
    }
    if tag == "sp" && !py_strip(&text_frame_text(shape.tx_body()?)).is_empty() {
        let surface = surface_svg(ctx, shape)?;
        let (container_styles, attributes) = text_container_attributes(ctx, shape, &preset)?;
        let mut styles = vec![box_style];
        styles.extend(container_styles);
        let name = shape.name();
        let native = if name.contains("[evo-html]") || name.contains("[evoflux-html]") {
            " html-native"
        } else {
            ""
        };
        let text = shape_text(ctx, shape)?;
        return Ok(format!(
            "<div class=\"shape text-shape{native}\" {identity} {geometry}{attributes} style=\"{}\">{surface}{text}</div>",
            styles.join(";")
        ));
    }
    let surface = surface_svg(ctx, shape)?;
    if surface.is_empty() {
        return Ok(String::new());
    }
    Ok(format!("<div class=\"shape vector-shape\" {identity} {geometry} style=\"{box_style};overflow:visible\">{surface}</div>"))
}
