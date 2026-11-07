//! An OOXML package (a zip of XML parts) read into memory, with relationship
//! resolution. Shared by the DOCX, PPTX and XLSX renderers.
//!
//! Part names are stored without a leading `/` (`ppt/slides/slide1.xml`).
//! [`super::security::preflight`] has already bounded the archive.

use std::collections::BTreeMap;
use std::io::{Cursor, Read};

use super::PreviewError;

/// One relationship of a part (`_rels/*.rels`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Relationship {
    pub id: String,
    /// The full relationship type URI.
    pub rel_type: String,
    /// The target part name (resolved, no leading `/`), or the raw URI when
    /// [`Relationship::external`].
    pub target: String,
    pub external: bool,
}

impl Relationship {
    /// The last segment of the type URI (`slideLayout`, `image`, `chart`, …).
    pub fn kind(&self) -> &str {
        self.rel_type.rsplit('/').next().unwrap_or(&self.rel_type)
    }
}

/// The parts of an OOXML package.
#[derive(Debug, Clone, Default)]
pub struct Package {
    parts: BTreeMap<String, Vec<u8>>,
}

impl Package {
    /// Read every part of the zip in `bytes`.
    pub fn open(bytes: &[u8]) -> Result<Self, PreviewError> {
        let mut archive = zip::ZipArchive::new(Cursor::new(bytes))
            .map_err(|e| PreviewError::failed(format!("Could not read this document: {e}")))?;
        let mut parts = BTreeMap::new();
        for index in 0..archive.len() {
            let mut entry = archive
                .by_index(index)
                .map_err(|e| PreviewError::failed(format!("Could not read this document: {e}")))?;
            if entry.is_dir() {
                continue;
            }
            let name = entry.name().trim_start_matches('/').to_string();
            let mut data = Vec::with_capacity(entry.size() as usize);
            entry
                .read_to_end(&mut data)
                .map_err(|e| PreviewError::failed(format!("Could not read this document: {e}")))?;
            parts.insert(name, data);
        }
        Ok(Self { parts })
    }

    /// Build a package from parts (tests, sanitized copies).
    pub fn from_parts(parts: impl IntoIterator<Item = (String, Vec<u8>)>) -> Self {
        Self {
            parts: parts
                .into_iter()
                .map(|(n, d)| (n.trim_start_matches('/').to_string(), d))
                .collect(),
        }
    }

    /// Every part name, sorted.
    pub fn names(&self) -> impl Iterator<Item = &str> {
        self.parts.keys().map(String::as_str)
    }

    pub fn has(&self, name: &str) -> bool {
        self.parts.contains_key(name.trim_start_matches('/'))
    }

    /// A part's bytes.
    pub fn bytes(&self, name: &str) -> Option<&[u8]> {
        self.parts.get(name.trim_start_matches('/')).map(Vec::as_slice)
    }

    /// A part as UTF-8 text (a leading BOM removed). Invalid UTF-8 is replaced.
    pub fn text(&self, name: &str) -> Option<String> {
        let bytes = self.bytes(name)?;
        let bytes = bytes.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(bytes);
        Some(String::from_utf8_lossy(bytes).into_owned())
    }

    /// The parts as an owned map (to write a modified copy).
    pub fn into_parts(self) -> BTreeMap<String, Vec<u8>> {
        self.parts
    }

    /// The relationships of `part` (from `<dir>/_rels/<file>.rels`), targets
    /// resolved against the part's folder. `""` reads the package rels.
    pub fn rels(&self, part: &str) -> Vec<Relationship> {
        let part = part.trim_start_matches('/');
        let (dir, file) = match part.rfind('/') {
            Some(i) => (&part[..i], &part[i + 1..]),
            None => ("", part),
        };
        let rels_name = if part.is_empty() {
            "_rels/.rels".to_string()
        } else if dir.is_empty() {
            format!("_rels/{file}.rels")
        } else {
            format!("{dir}/_rels/{file}.rels")
        };
        let Some(text) = self.text(&rels_name) else {
            return Vec::new();
        };
        let Ok(doc) = super::html::parse_xml(&text) else {
            return Vec::new();
        };
        doc.root_element()
            .children()
            .filter(|n| n.is_element() && n.tag_name().name() == "Relationship")
            .filter_map(|n| {
                let id = n.attribute("Id")?.to_string();
                let rel_type = n.attribute("Type").unwrap_or_default().to_string();
                let raw = n.attribute("Target").unwrap_or_default();
                let external = n
                    .attribute("TargetMode")
                    .is_some_and(|m| m.eq_ignore_ascii_case("External"));
                let target = if external {
                    raw.to_string()
                } else {
                    resolve(dir, raw)
                };
                Some(Relationship {
                    id,
                    rel_type,
                    target,
                    external,
                })
            })
            .collect()
    }

    /// The relationship `id` of `part`.
    pub fn rel(&self, part: &str, id: &str) -> Option<Relationship> {
        self.rels(part).into_iter().find(|r| r.id == id)
    }

    /// The first relationship of `part` whose type ends with `/kind`.
    pub fn rel_of_kind(&self, part: &str, kind: &str) -> Option<Relationship> {
        self.rels(part).into_iter().find(|r| r.kind() == kind)
    }

    /// The content type of `part` from `[Content_Types].xml` (override, then
    /// default by extension).
    pub fn content_type(&self, part: &str) -> Option<String> {
        let part = part.trim_start_matches('/');
        let text = self.text("[Content_Types].xml")?;
        let doc = super::html::parse_xml(&text).ok()?;
        let wanted = format!("/{part}");
        let mut by_extension = None;
        let ext = part.rsplit('.').next().unwrap_or_default().to_ascii_lowercase();
        for node in doc.root_element().children().filter(|n| n.is_element()) {
            match node.tag_name().name() {
                "Override" if node.attribute("PartName").is_some_and(|p| p.eq_ignore_ascii_case(&wanted)) => {
                    return node.attribute("ContentType").map(str::to_string);
                }
                "Default" if node.attribute("Extension").is_some_and(|e| e.eq_ignore_ascii_case(&ext)) => {
                    by_extension = node.attribute("ContentType").map(str::to_string);
                }
                _ => {}
            }
        }
        by_extension
    }
}

/// Resolve a relationship `target` against the folder `base_dir` of its source
/// part (no leading `/` in either; `..` and `.` collapsed). An absolute target
/// (`/ppt/media/x.png`) is taken from the package root.
pub fn resolve(base_dir: &str, target: &str) -> String {
    let target = target.split('#').next().unwrap_or(target);
    let mut segments: Vec<&str> = if target.starts_with('/') {
        Vec::new()
    } else {
        base_dir.split('/').filter(|s| !s.is_empty()).collect()
    };
    for segment in target.split('/') {
        match segment {
            "" | "." => {}
            ".." => {
                segments.pop();
            }
            other => segments.push(other),
        }
    }
    segments.join("/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_relative_and_absolute_targets() {
        assert_eq!(resolve("ppt/slides", "../slideLayouts/slideLayout1.xml"), "ppt/slideLayouts/slideLayout1.xml");
        assert_eq!(resolve("ppt/slides", "/ppt/media/image1.png"), "ppt/media/image1.png");
        assert_eq!(resolve("", "word/document.xml"), "word/document.xml");
        assert_eq!(resolve("xl", "./worksheets/sheet1.xml"), "xl/worksheets/sheet1.xml");
    }

    #[test]
    fn reads_relationships_and_content_types() {
        let pkg = Package::from_parts([
            (
                "[Content_Types].xml".to_string(),
                br#"<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/slides/slide1.xml" ContentType="slide+xml"/></Types>"#.to_vec(),
            ),
            (
                "ppt/slides/_rels/slide1.xml.rels".to_string(),
                br#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://x/relationships/slideLayout" Target="../slideLayouts/slideLayout2.xml"/><Relationship Id="rId2" Type="http://x/relationships/hyperlink" Target="https://e.com" TargetMode="External"/></Relationships>"#.to_vec(),
            ),
        ]);
        let rels = pkg.rels("ppt/slides/slide1.xml");
        assert_eq!(rels[0].target, "ppt/slideLayouts/slideLayout2.xml");
        assert_eq!(rels[0].kind(), "slideLayout");
        assert!(rels[1].external);
        assert_eq!(pkg.content_type("ppt/slides/slide1.xml").as_deref(), Some("slide+xml"));
        assert_eq!(pkg.content_type("x/y.xml").as_deref(), Some("application/xml"));
    }
}
