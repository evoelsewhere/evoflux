//! The deck read from raw XML with python-pptx's semantics where v3 depended
//! on them: slide → layout → master → theme, the shape factories, placeholder
//! matching and the position inheritance of placeholders (`_InheritsDimensions`).

use std::collections::HashMap;

use roxmltree::Document;

use super::super::Package;
use super::util::{child, child_ns, elements, local, py_int, Nd, Skip, A, P, R};

/// All parsed XML parts of the deck.
pub(super) struct Deck<'a> {
    pub pkg: &'a Package,
    pub docs: &'a HashMap<String, Document<'a>>,
    /// Parts re-read with the SmartArt drawing namespace renamed to
    /// PresentationML (v3 `_smartart_group`).
    pub smart: &'a HashMap<String, Document<'a>>,
    /// python-pptx partnames (`/ppt/...`), slides renamed `slideN.xml` in deck
    /// order like `Presentation.slides` does.
    pub partnames: HashMap<String, String>,
}

impl<'a> Deck<'a> {
    pub fn root(&self, part: &str) -> Option<Nd<'a>> {
        self.docs.get(part).map(Document::root_element)
    }

    /// The part a relationship of `part` points at (internal targets only).
    pub fn related(&self, part: &str, rid: &str) -> Option<String> {
        self.pkg
            .rel(part, rid)
            .filter(|r| !r.external)
            .map(|r| r.target)
    }

    pub fn related_of_kind(&self, part: &str, kind: &str) -> Option<String> {
        self.pkg
            .rels(part)
            .into_iter()
            .find(|r| r.kind() == kind && !r.external)
            .map(|r| r.target)
    }

    /// The interned part name (lives as long as the deck).
    pub fn key(&self, part: &str) -> Option<&str> {
        self.partnames.get_key_value(part).map(|(k, _)| k.as_str())
    }

    pub fn partname(&self, part: &str) -> String {
        self.partnames
            .get(part)
            .cloned()
            .unwrap_or_else(|| format!("/{part}"))
    }
}

/// Everything v3 derived from `slide` while rendering it.
pub(super) struct SlideCtx<'a> {
    pub deck: &'a Deck<'a>,
    pub slide_part: &'a str,
    pub layout_part: &'a str,
    pub master_part: &'a str,
    pub slide_root: Nd<'a>,
    pub layout_root: Nd<'a>,
    pub master_root: Nd<'a>,
    pub theme: Option<Nd<'a>>,
    pub palette: HashMap<String, String>,
    pub fonts: HashMap<String, String>,
    pub slide_width: i64,
    pub slide_height: i64,
}

/// How python-pptx constructed a shape, which decides whether a missing
/// position is inherited.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Origin {
    /// A direct member of the slide's shape tree (`SlideShapeFactory`).
    SlideTop,
    /// A layout placeholder found by idx (`LayoutPlaceholder`).
    LayoutPlaceholder,
    /// Everything else (`BaseShapeFactory`, master placeholders).
    Plain,
}

#[derive(Clone, Copy)]
pub(super) struct Shape<'a> {
    pub node: Nd<'a>,
    /// The part the shape lives in (relationships, partname).
    pub part: &'a str,
    pub origin: Origin,
}

/// `PP_PLACEHOLDER` member names by XML value.
pub(super) fn placeholder_type_name(xml: &str) -> Option<&'static str> {
    Some(match xml {
        "clipArt" => "BITMAP",
        "body" => "BODY",
        "ctrTitle" => "CENTER_TITLE",
        "chart" => "CHART",
        "dt" => "DATE",
        "ftr" => "FOOTER",
        "hdr" => "HEADER",
        "media" => "MEDIA_CLIP",
        "obj" => "OBJECT",
        "dgm" => "ORG_CHART",
        "pic" => "PICTURE",
        "sldImg" => "SLIDE_IMAGE",
        "sldNum" => "SLIDE_NUMBER",
        "subTitle" => "SUBTITLE",
        "tbl" => "TABLE",
        "title" => "TITLE",
        _ => return None,
    })
}

const SHAPE_TAGS: [&str; 6] = ["sp", "grpSp", "graphicFrame", "cxnSp", "pic", "contentPart"];

/// `<p:ph>` of a shape element (`./*[1]/p:nvPr/p:ph`).
pub(super) fn ph(node: Nd<'_>) -> Option<Nd<'_>> {
    let nv = elements(node).next()?;
    let nv_pr = child_ns(nv, P, "nvPr")?;
    child_ns(nv_pr, P, "ph")
}

/// `ph_idx` (default 0); `Err` where python-pptx raised.
pub(super) fn ph_idx(ph: Nd<'_>) -> Result<i64, Skip> {
    match ph.attribute("idx") {
        None => Ok(0),
        Some(raw) => py_int(raw).filter(|v| *v >= 0).ok_or(Skip),
    }
}

/// `ph_type` member name (default `OBJECT`); `Err` for an unknown value.
pub(super) fn ph_type(ph: Nd<'_>) -> Result<&'static str, Skip> {
    match ph.attribute("type") {
        None => Ok("OBJECT"),
        Some(raw) => placeholder_type_name(raw).ok_or(Skip),
    }
}

/// The non-visual properties of a shape (`cNvPr`).
pub(super) fn c_nv_pr(node: Nd<'_>) -> Option<Nd<'_>> {
    child(elements(node).next()?, "cNvPr")
}

impl<'a> Shape<'a> {
    pub fn tag(&self) -> &'a str {
        local(self.node)
    }

    pub fn ph(&self) -> Option<Nd<'a>> {
        ph(self.node)
    }

    pub fn is_placeholder(&self) -> bool {
        self.ph().is_some()
    }

    /// `str(shape.shape_id)`.
    pub fn shape_id(&self) -> Result<String, Skip> {
        // Fix over v3 (raised, lost the shape): a missing id is empty, an
        // unreadable one is kept as written.
        let raw = c_nv_pr(self.node)
            .and_then(|n| n.attribute("id"))
            .unwrap_or("");
        if let Some(value) = py_int(raw) {
            return Ok(value.to_string());
        }
        // Python's int has no upper bound: keep an over-long decimal id.
        let digits = raw.trim();
        if !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit()) {
            let stripped = digits.trim_start_matches('0');
            return Ok(if stripped.is_empty() { "0" } else { stripped }.to_string());
        }
        Ok(digits.to_string())
    }

    pub fn name(&self) -> &'a str {
        c_nv_pr(self.node)
            .and_then(|n| n.attribute("name"))
            .unwrap_or("")
    }

    /// The element's own `a:xfrm` (`shape._element.xfrm`).
    pub fn xfrm(&self) -> Option<Nd<'a>> {
        match self.tag() {
            "grpSp" => child_ns(child_ns(self.node, P, "grpSpPr")?, A, "xfrm"),
            "graphicFrame" => child_ns(self.node, P, "xfrm"),
            _ => child_ns(child_ns(self.node, P, "spPr")?, A, "xfrm"),
        }
    }

    /// `shape.rotation` (degrees, 0..360).
    pub fn rotation(&self) -> f64 {
        self.xfrm()
            .and_then(|x| x.attribute("rot"))
            .and_then(py_int)
            .map(|rot| (rot as f64 / 60000.0).rem_euclid(360.0))
            .unwrap_or(0.0)
    }

    fn direct_dim(&self, dim: Dim) -> Option<i64> {
        let xfrm = self.xfrm()?;
        let (element, attribute) = match dim {
            Dim::Left => ("off", "x"),
            Dim::Top => ("off", "y"),
            Dim::Width => ("ext", "cx"),
            Dim::Height => ("ext", "cy"),
        };
        child_ns(xfrm, A, element)?
            .attribute(attribute)
            .and_then(py_int)
    }

    /// `shape.left` / `top` / `width` / `height`, inherited like python-pptx.
    ///
    /// Fix over v3: where python-pptx raised while looking for the inherited
    /// value (a layout placeholder type it has no master mapping for, e.g. a
    /// header; a non-autoshape placeholder on the master; an unreadable
    /// `idx`/`type`), v3 lost the whole shape. Here the value is simply not
    /// inherited (`None`).
    pub fn dim(&self, ctx: &SlideCtx<'a>, dim: Dim) -> Result<Option<i64>, Skip> {
        if let Some(value) = self.direct_dim(dim) {
            return Ok(Some(value));
        }
        let Some(ph) = self.ph() else {
            return Ok(None);
        };
        match (self.origin, self.tag()) {
            (Origin::SlideTop, "sp" | "pic") => {
                let Ok(idx) = ph_idx(ph) else {
                    return Ok(None);
                };
                match layout_placeholder_by_idx(ctx, idx) {
                    Some(base) => base.dim(ctx, dim),
                    None => Ok(None),
                }
            }
            (Origin::LayoutPlaceholder, "sp") => {
                let base_type = match ph_type(ph).unwrap_or("") {
                    "BODY" | "CHART" | "BITMAP" | "ORG_CHART" | "MEDIA_CLIP" | "OBJECT"
                    | "PICTURE" | "SUBTITLE" | "TABLE" => "BODY",
                    "CENTER_TITLE" | "TITLE" => "TITLE",
                    "DATE" => "DATE",
                    "FOOTER" => "FOOTER",
                    "SLIDE_NUMBER" => "SLIDE_NUMBER",
                    _ => return Ok(None),
                };
                match master_placeholder_by_type(ctx, base_type) {
                    Some(base) => base.dim(ctx, dim),
                    None => Ok(None),
                }
            }
            _ => Ok(None),
        }
    }

    /// `int(shape.<dim> or 0)`.
    pub fn dim0(&self, ctx: &SlideCtx<'a>, dim: Dim) -> Result<i64, Skip> {
        Ok(self.dim(ctx, dim)?.unwrap_or(0))
    }

    /// The `p:txBody` (`shape.text_frame._txBody`); only autoshapes have one.
    pub fn tx_body(&self) -> Result<Option<Nd<'a>>, Skip> {
        if self.tag() != "sp" {
            return Err(Skip);
        }
        Ok(child(self.node, "txBody"))
    }
}

#[derive(Clone, Copy, Debug)]
pub(super) enum Dim {
    Left,
    Top,
    Width,
    Height,
}

/// Direct shape-tree members carrying a `<p:ph>` (python-pptx `placeholders`).
pub(super) fn placeholders<'a>(tree_root: Nd<'a>) -> Vec<Nd<'a>> {
    let Some(tree) = sp_tree(tree_root) else {
        return Vec::new();
    };
    elements(tree)
        .filter(|e| e.tag_name().namespace() == Some(P) && SHAPE_TAGS.contains(&local(*e)))
        .filter(|e| ph(*e).is_some())
        .collect()
}

/// `<p:cSld><p:spTree>` of a slide, layout or master.
pub(super) fn sp_tree(root: Nd<'_>) -> Option<Nd<'_>> {
    child_ns(child_ns(root, P, "cSld")?, P, "spTree")
}

/// `layout.placeholders.get(idx=…)`.
fn layout_placeholder_by_idx<'a>(ctx: &SlideCtx<'a>, idx: i64) -> Option<Shape<'a>> {
    for node in placeholders(ctx.layout_root) {
        if ph(node).map(ph_idx) == Some(Ok(idx)) {
            let origin = if local(node) == "sp" {
                Origin::LayoutPlaceholder
            } else {
                Origin::Plain
            };
            return Some(Shape {
                node,
                part: ctx.layout_part,
                origin,
            });
        }
    }
    None
}

/// `master.placeholders.get(ph_type)`.
fn master_placeholder_by_type<'a>(ctx: &SlideCtx<'a>, wanted: &str) -> Option<Shape<'a>> {
    for node in placeholders(ctx.master_root) {
        // Only autoshape placeholders count (python-pptx `MasterPlaceholder`).
        if local(node) == "sp" && ph(node).map(ph_type) == Some(Ok(wanted)) {
            return Some(Shape {
                node,
                part: ctx.master_part,
                origin: Origin::Plain,
            });
        }
    }
    None
}

/// v3 `_matching_placeholder(container, shape)`: same idx, else the first of
/// the same type.
pub(super) fn matching_placeholder<'a>(
    container_root: Nd<'a>,
    container_part: &'a str,
    shape: &Shape<'_>,
    layout: bool,
) -> Option<Shape<'a>> {
    let ph = shape.ph()?;
    let index = ph_idx(ph).ok()?;
    let kind = ph_type(ph).ok()?;
    let mut same_type = None;
    for node in placeholders(container_root) {
        let Some(candidate) = self::ph(node) else {
            continue;
        };
        let Ok(candidate_idx) = ph_idx(candidate) else {
            continue;
        };
        let origin = if layout && local(node) == "sp" {
            Origin::LayoutPlaceholder
        } else {
            Origin::Plain
        };
        let found = Shape {
            node,
            part: container_part,
            origin,
        };
        if candidate_idx == index {
            return Some(found);
        }
        let Ok(candidate_type) = ph_type(candidate) else {
            continue;
        };
        if same_type.is_none() && candidate_type == kind {
            same_type = Some(found);
        }
    }
    same_type
}

/// The relationship id of a picture's image (`blip_rId`).
pub(super) fn blip_rid<'a>(pic: Nd<'a>) -> Option<&'a str> {
    let blip_fill = child(pic, "blipFill")?;
    let blip = child_ns(blip_fill, A, "blip")?;
    blip.attribute((R, "embed"))
}
