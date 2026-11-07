//! PDF pages for the native path (v3 `service.py` `_render_pdf_document`).
//!
//! v3 rasterized every page with pdfium and embedded the PNGs. v4 shows PDFs
//! with pdf.js in the viewer, so the native HTML only carries one labelled,
//! empty page per PDF page: the agent's `document_preview` reads the page count
//! and labels from it. The page count comes from the document's page tree
//! (`/Root` → `/Pages` → `/Count`), read without a PDF library: objects are
//! scanned in file order (later definitions win, as incremental updates
//! intend), and compressed object streams (`/Type /ObjStm`, Flate) are
//! inflated within a budget. When no page tree can be found, the `/Type /Page`
//! objects are counted instead.

use std::collections::HashMap;
use std::io::Read;
use std::sync::OnceLock;

use regex::bytes::Regex;

use super::html::{escape, page};
use super::PreviewError;

/// The most pages a preview lists (v3 `MAX_PDF_PREVIEW_PAGES`).
pub const MAX_PDF_PREVIEW_PAGES: usize = 80;
/// Inflated object streams stop here (all of them together).
const MAX_INFLATED_BYTES: u64 = 64 * 1024 * 1024;
/// Only the start of an object is read for its dictionary.
const MAX_DICTIONARY_BYTES: usize = 64 * 1024;

const CSS: &str = "
    *{box-sizing:border-box}body{margin:0;padding:28px;background:#e5e7eb;
    color:#242424;font-family:Arial,sans-serif}.pdf-page-wrap{position:relative;
    width:min(960px,94vw);margin:0 auto 28px}.pdf-page-surface{position:relative;
    container-type:inline-size;background:#fff;box-shadow:0 2px 14px #0003;
    aspect-ratio:8.5/11}.pdf-page-number{
    position:absolute;right:calc(100% + 9px);top:0;color:#616161;font-size:12px}
    .pdf-preview-limit{max-width:720px;margin:20px auto;padding:14px 18px;border-radius:8px;
    background:#fff4ce;color:#5c2e00;box-shadow:0 1px 4px #0002}
    ";

/// Render the page list of the PDF in `bytes`.
pub fn render(bytes: &[u8], title: &str) -> Result<String, PreviewError> {
    let total_pages = page_count(bytes)?;
    let shown = total_pages.min(MAX_PDF_PREVIEW_PAGES);
    let mut rendered = String::new();
    for number in 1..=shown {
        let label = escape(&format!("Page {number}"));
        rendered.push_str(&format!(
            "<article class=\"pdf-page-wrap\" data-preview-item data-preview-label=\"{label}\" \
data-page-index=\"{}\"><span class=\"pdf-page-number\">{number}</span>\
<div class=\"pdf-page-surface\"></div></article>",
            number - 1
        ));
    }
    if shown < total_pages {
        rendered.push_str(&format!(
            "<p class=\"pdf-preview-limit\" role=\"status\">Preview shows {shown} of {total_pages} \
pages. Download the document to inspect the remaining pages.</p>"
        ));
    }
    Ok(page(
        title,
        &format!("<main data-preview-renderer=\"pdf\">{rendered}</main>"),
        CSS,
    ))
}

/// The number of pages of the PDF in `bytes`.
pub fn page_count(bytes: &[u8]) -> Result<usize, PreviewError> {
    let objects = Objects::scan(bytes);
    if let Some(count) = objects.root_page_count(bytes) {
        return Ok(count);
    }
    let pages = objects.count_page_objects();
    if pages > 0 {
        return Ok(pages);
    }
    Err(PreviewError::failed(
        "Could not render this document: the PDF page tree could not be read.",
    ))
}

fn regex(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).expect("valid regex"))
}

fn object_header() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    regex(&CELL, r"(?-u)(\d+)\s+\d+\s+obj\b")
}

fn reference(key: &str) -> Regex {
    Regex::new(&format!(r"(?-u)/{key}\s+(\d+)\s+\d+\s+R\b")).expect("valid regex")
}

/// Every object's dictionary text by object number (latest definition wins).
struct Objects {
    by_number: HashMap<u64, Vec<u8>>,
}

impl Objects {
    fn scan(bytes: &[u8]) -> Self {
        static STREAM: OnceLock<Regex> = OnceLock::new();
        static OBJSTM: OnceLock<Regex> = OnceLock::new();
        let stream_keyword = regex(&STREAM, r"(?-u)\bstream(\r\n|\n|\r)?");
        let objstm = regex(&OBJSTM, r"(?-u)/Type\s*/ObjStm\b");
        let mut by_number = HashMap::new();
        let mut inflated_budget = MAX_INFLATED_BYTES;
        let mut pos = 0;
        while let Some(found) = object_header().captures_at(bytes, pos) {
            let whole = found.get(0).expect("match");
            let number = parse_u64(&found[1]);
            let body_start = whole.end();
            let window_end = bytes.len().min(body_start + MAX_DICTIONARY_BYTES);
            let window = &bytes[body_start..window_end];
            let endobj = find(window, b"endobj");
            let stream = stream_keyword
                .find(window)
                .filter(|m| endobj.is_none_or(|e| m.start() < e));
            let dictionary_end = stream.map(|m| m.start()).or(endobj).unwrap_or(window.len());
            let dictionary = window[..dictionary_end].to_vec();
            pos = match stream {
                Some(keyword) => {
                    let data_start = body_start + keyword.end();
                    let data_end = find(&bytes[data_start..], b"endstream")
                        .map_or(bytes.len(), |i| data_start + i);
                    if objstm.is_match(&dictionary) {
                        for (n, text) in object_stream(
                            &dictionary,
                            &bytes[data_start..data_end],
                            &mut inflated_budget,
                        ) {
                            by_number.insert(n, text);
                        }
                    }
                    data_end
                }
                None => body_start + endobj.unwrap_or(dictionary_end),
            };
            if let Some(n) = number {
                by_number.insert(n, dictionary);
            }
            pos = pos.max(body_start);
        }
        Self { by_number }
    }

    fn get(&self, number: u64) -> Option<&[u8]> {
        self.by_number.get(&number).map(Vec::as_slice)
    }

    /// `/Count` of the page tree the catalog names.
    fn root_page_count(&self, bytes: &[u8]) -> Option<usize> {
        static CATALOG: OnceLock<Regex> = OnceLock::new();
        let catalog_type = regex(&CATALOG, r"(?-u)/Type\s*/Catalog\b");
        let root = reference("Root");
        let mut catalogs: Vec<u64> = root
            .captures_iter(bytes)
            .filter_map(|c| parse_u64(&c[1]))
            .collect();
        catalogs.reverse();
        let mut typed: Vec<u64> = self
            .by_number
            .iter()
            .filter(|(_, text)| catalog_type.is_match(text))
            .map(|(n, _)| *n)
            .collect();
        typed.sort_unstable();
        catalogs.extend(typed);
        let pages = reference("Pages");
        catalogs.into_iter().find_map(|catalog| {
            let text = self.get(catalog)?;
            let tree = parse_u64(&pages.captures(text)?[1])?;
            self.count_of(tree)
        })
    }

    fn count_of(&self, tree: u64) -> Option<usize> {
        static COUNT: OnceLock<Regex> = OnceLock::new();
        let count = regex(&COUNT, r"(?-u)/Count\s+(\d+)(?:\s+\d+\s+R\b)?");
        let text = self.get(tree)?;
        let found = count.captures(text)?;
        let whole = found.get(0)?.as_bytes();
        let value = parse_u64(&found[1])?;
        let value = if whole.ends_with(b"R") {
            // An indirect count: the referenced object holds the number.
            let target = self.get(value)?;
            let digits: Vec<u8> = target
                .iter()
                .copied()
                .skip_while(|b| !b.is_ascii_digit())
                .take_while(u8::is_ascii_digit)
                .collect();
            parse_u64(&digits)?
        } else {
            value
        };
        usize::try_from(value).ok()
    }

    fn count_page_objects(&self) -> usize {
        static PAGE: OnceLock<Regex> = OnceLock::new();
        let page_type = regex(&PAGE, r"(?-u)/Type\s*/Page(?:[^A-Za-z0-9]|$)");
        self.by_number
            .values()
            .filter(|text| page_type.is_match(text))
            .count()
    }
}

/// The objects of a compressed object stream (`/N` pairs of number and offset,
/// then the objects from `/First`).
fn object_stream(dictionary: &[u8], data: &[u8], budget: &mut u64) -> Vec<(u64, Vec<u8>)> {
    static N: OnceLock<Regex> = OnceLock::new();
    static FIRST: OnceLock<Regex> = OnceLock::new();
    static FLATE: OnceLock<Regex> = OnceLock::new();
    let n_key = regex(&N, r"(?-u)/N\s+(\d+)");
    let first_key = regex(&FIRST, r"(?-u)/First\s+(\d+)");
    let flate = regex(&FLATE, r"(?-u)/FlateDecode\b");
    let (Some(n), Some(first)) = (
        n_key.captures(dictionary).and_then(|c| parse_u64(&c[1])),
        first_key
            .captures(dictionary)
            .and_then(|c| parse_u64(&c[1])),
    ) else {
        return Vec::new();
    };
    if !flate.is_match(dictionary) || *budget == 0 {
        return Vec::new();
    }
    let mut inflated = Vec::new();
    let read = flate2::read::ZlibDecoder::new(data)
        .take(*budget)
        .read_to_end(&mut inflated);
    if read.is_err() && inflated.is_empty() {
        return Vec::new();
    }
    *budget = budget.saturating_sub(inflated.len() as u64);
    let Ok(first) = usize::try_from(first) else {
        return Vec::new();
    };
    if first > inflated.len() {
        return Vec::new();
    }
    let numbers: Vec<u64> = inflated[..first]
        .split(|b| b.is_ascii_whitespace())
        .filter(|t| !t.is_empty())
        .filter_map(parse_u64)
        .collect();
    let pairs: Vec<(u64, usize)> = numbers
        .chunks_exact(2)
        .take(usize::try_from(n).unwrap_or(0))
        .filter_map(|p| Some((p[0], usize::try_from(p[1]).ok()?)))
        .collect();
    let body = &inflated[first..];
    let mut objects = Vec::with_capacity(pairs.len());
    for (index, &(number, offset)) in pairs.iter().enumerate() {
        let end = pairs
            .get(index + 1)
            .map_or(body.len(), |&(_, next)| next)
            .min(body.len());
        if offset >= end {
            continue;
        }
        let text = &body[offset..end];
        objects.push((
            number,
            text[..text.len().min(MAX_DICTIONARY_BYTES)].to_vec(),
        ));
    }
    objects
}

fn parse_u64(digits: &[u8]) -> Option<u64> {
    std::str::from_utf8(digits).ok()?.parse().ok()
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn classic(pages: usize) -> Vec<u8> {
        let kids: Vec<String> = (0..pages).map(|i| format!("{} 0 R", 3 + i)).collect();
        let mut pdf = format!(
            "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [{}] /Count {pages} >>\nendobj\n",
            kids.join(" ")
        );
        for i in 0..pages {
            pdf.push_str(&format!(
                "{} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n",
                3 + i
            ));
        }
        pdf.push_str("trailer\n<< /Root 1 0 R >>\n%%EOF\n");
        pdf.into_bytes()
    }

    #[test]
    fn counts_a_classic_page_tree() {
        assert_eq!(page_count(&classic(3)).unwrap(), 3);
    }

    #[test]
    fn counts_pages_inside_object_streams() {
        let catalog = "<< /Type /Catalog /Pages 2 0 R >> ";
        let objects = format!("1 0 2 {} ", catalog.len());
        let raw = format!("{objects}{catalog}<< /Type /Pages /Kids [] /Count 7 >>");
        let mut encoder =
            flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
        encoder.write_all(raw.as_bytes()).unwrap();
        let data = encoder.finish().unwrap();
        let mut pdf = format!(
            "%PDF-1.5\n5 0 obj\n<< /Type /ObjStm /N 2 /First {} /Filter /FlateDecode /Length {} >>\nstream\n",
            objects.len(),
            data.len()
        )
        .into_bytes();
        pdf.extend_from_slice(&data);
        pdf.extend_from_slice(b"\nendstream\nendobj\n6 0 obj\n<< /Type /XRef /Root 1 0 R >>\nstream\nxx\nendstream\nendobj\n%%EOF");
        assert_eq!(page_count(&pdf).unwrap(), 7);
    }

    #[test]
    fn falls_back_to_page_objects_and_fails_on_garbage() {
        let pdf = b"%PDF-1.4\n4 0 obj << /Type /Page >> endobj\n5 0 obj << /Type /Page >> endobj\n6 0 obj << /Type /Pages >> endobj";
        assert_eq!(page_count(pdf).unwrap(), 2);
        assert!(matches!(
            page_count(b"%PDF-1.4 nothing"),
            Err(PreviewError::Failed(_))
        ));
    }

    #[test]
    fn caps_the_listed_pages() {
        let html = render(&classic(82), "big.pdf").unwrap();
        assert_eq!(
            html.matches("data-preview-item").count(),
            MAX_PDF_PREVIEW_PAGES
        );
        assert!(html.contains("Preview shows 80 of 82 pages."));
        assert!(html.contains("data-preview-label=\"Page 80\" data-page-index=\"79\""));
    }
}
