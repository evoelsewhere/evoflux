//! Read a rendered preview back into pages and elements (v3 `inspection.py`).
//!
//! The renderer already labels its output for inspection: every page, slide, or
//! sheet carries `data-preview-item` with a human label, and every drawn element
//! carries `data-qa-label` plus its geometry as percentages of the page box.
//! This module is the reader for that contract, and it lives beside the writer on
//! purpose — the markup and the parse cannot drift into two different truths.
//!
//! Geometry arrives as percentages, so "does this element sit inside its page" is
//! a comparison against 0 and 100 rather than against any absolute size.

use std::collections::HashMap;
use std::sync::OnceLock;

use regex::Regex;

pub const PREVIEW_ITEM_ATTRIBUTE: &str = "data-preview-item";
pub const PREVIEW_LABEL_ATTRIBUTE: &str = "data-preview-label";
pub const ELEMENT_LABEL_ATTRIBUTE: &str = "data-qa-label";

pub const DEFAULT_MAX_ITEMS: usize = 200;
pub const DEFAULT_MAX_ELEMENTS_PER_ITEM: usize = 200;
pub const DEFAULT_MAX_TEXT_CHARS: usize = 400;

/// One labelled element drawn on a preview item.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PreviewElement {
    pub label: String,
    pub text: String,
    pub left: Option<f64>,
    pub top: Option<f64>,
    pub width: Option<f64>,
    pub height: Option<f64>,
}

impl PreviewElement {
    pub fn right(&self) -> Option<f64> {
        Some(self.left? + self.width?)
    }

    pub fn bottom(&self) -> Option<f64> {
        Some(self.top? + self.height?)
    }

    /// Whether any known edge falls outside the 0–100 % page box.
    pub fn out_of_bounds(&self) -> bool {
        self.left.is_some_and(|v| v < 0.0)
            || self.top.is_some_and(|v| v < 0.0)
            || self.right().is_some_and(|v| v > 100.0)
            || self.bottom().is_some_and(|v| v > 100.0)
    }
}

/// One page, slide or sheet.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PreviewItem {
    pub label: String,
    pub elements: Vec<PreviewElement>,
    pub elements_truncated: bool,
}

impl PreviewItem {
    /// The elements that leave the page box.
    pub fn out_of_bounds(&self) -> Vec<&PreviewElement> {
        self.elements.iter().filter(|e| e.out_of_bounds()).collect()
    }

    /// The non-empty element texts, one per line.
    pub fn text(&self) -> String {
        self.elements
            .iter()
            .filter(|e| !e.text.is_empty())
            .map(|e| e.text.as_str())
            .collect::<Vec<_>>()
            .join("\n")
    }
}

/// The whole document.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PreviewSummary {
    pub items: Vec<PreviewItem>,
    pub items_truncated: bool,
}

/// Parse rendered preview HTML with the default budgets.
pub fn summarize(html: &str) -> PreviewSummary {
    summarize_with(
        html,
        DEFAULT_MAX_ITEMS,
        DEFAULT_MAX_ELEMENTS_PER_ITEM,
        DEFAULT_MAX_TEXT_CHARS,
    )
}

/// Parse rendered preview HTML within explicit budgets.
pub fn summarize_with(
    html: &str,
    max_items: usize,
    max_elements: usize,
    max_text_chars: usize,
) -> PreviewSummary {
    let mut reader = Reader {
        max_items,
        max_elements,
        max_text_chars,
        summary: PreviewSummary::default(),
        item: None,
        item_depth: 0,
        element: None,
        element_depth: 0,
        chunks: String::new(),
    };
    tokenize(html, &mut reader);
    reader.finish()
}

/// `property: <n>%` in an inline style (v3 `_percent`).
fn percent(style: &str, property: &str) -> Option<f64> {
    const PROPERTIES: [&str; 4] = ["left", "top", "width", "height"];
    static NUMBER: OnceLock<Regex> = OnceLock::new();
    static DECLARATIONS: OnceLock<Vec<Regex>> = OnceLock::new();
    let number = NUMBER.get_or_init(|| Regex::new(r"(-?\d+(?:\.\d+)?)\s*%").expect("valid regex"));
    let declarations = DECLARATIONS.get_or_init(|| {
        PROPERTIES
            .iter()
            .map(|p| Regex::new(&format!(r"(?:^|;)\s*{p}\s*:\s*([^;]+)")).expect("valid regex"))
            .collect()
    });
    let index = PROPERTIES.iter().position(|p| *p == property)?;
    let value = declarations[index].captures(style)?.get(1)?.as_str();
    number.captures(value)?.get(1)?.as_str().parse().ok()
}

struct OpenElement {
    label: String,
    left: Option<f64>,
    top: Option<f64>,
    width: Option<f64>,
    height: Option<f64>,
}

struct Reader {
    max_items: usize,
    max_elements: usize,
    max_text_chars: usize,
    summary: PreviewSummary,
    item: Option<PreviewItem>,
    item_depth: usize,
    element: Option<OpenElement>,
    element_depth: usize,
    chunks: String,
}

impl Reader {
    fn start_tag(&mut self, attributes: &HashMap<String, String>) {
        if self.item.is_some() {
            self.item_depth += 1;
        }
        if self.element.is_some() {
            self.element_depth += 1;
        }

        if attributes.contains_key(PREVIEW_ITEM_ATTRIBUTE) {
            self.close_item();
            if self.summary.items.len() >= self.max_items {
                self.summary.items_truncated = true;
                return;
            }
            let label = attributes
                .get(PREVIEW_LABEL_ATTRIBUTE)
                .map(|l| l.trim())
                .unwrap_or_default();
            self.item = Some(PreviewItem {
                label: if label.is_empty() {
                    format!("Item {}", self.summary.items.len() + 1)
                } else {
                    label.to_string()
                },
                ..Default::default()
            });
            self.item_depth = 0;
            return;
        }

        if let Some(label) = attributes.get(ELEMENT_LABEL_ATTRIBUTE) {
            if self.element.is_some() {
                return;
            }
            if let Some(item) = self.item.as_mut() {
                if item.elements.len() >= self.max_elements {
                    item.elements_truncated = true;
                    return;
                }
            }
            let style = attributes
                .get("style")
                .map(String::as_str)
                .unwrap_or_default();
            self.element = Some(OpenElement {
                label: label.trim().to_string(),
                left: percent(style, "left"),
                top: percent(style, "top"),
                width: percent(style, "width"),
                height: percent(style, "height"),
            });
            self.element_depth = 0;
            self.chunks.clear();
        }
    }

    fn end_tag(&mut self) {
        if self.element.is_some() {
            if self.element_depth == 0 {
                self.close_element();
            } else {
                self.element_depth -= 1;
            }
        }
        if self.item.is_some() {
            if self.item_depth == 0 {
                self.close_item();
            } else {
                self.item_depth -= 1;
            }
        }
    }

    fn data(&mut self, text: &str) {
        if self.element.is_some() {
            self.chunks.push_str(text);
        }
    }

    fn close_element(&mut self) {
        let Some(element) = self.element.take() else {
            return;
        };
        let mut text = self.chunks.split_whitespace().collect::<Vec<_>>().join(" ");
        if text.chars().count() > self.max_text_chars {
            let cut: String = text.chars().take(self.max_text_chars).collect();
            text = format!("{}…", cut.trim_end());
        }
        self.chunks.clear();
        if let Some(item) = self.item.as_mut() {
            if !item.elements_truncated {
                item.elements.push(PreviewElement {
                    label: element.label,
                    text,
                    left: element.left,
                    top: element.top,
                    width: element.width,
                    height: element.height,
                });
            }
        }
    }

    fn close_item(&mut self) {
        self.close_element();
        if let Some(item) = self.item.take() {
            self.summary.items.push(item);
        }
    }

    fn finish(mut self) -> PreviewSummary {
        self.close_item();
        self.summary
    }
}

/// HTML elements that never have an end tag. v3's reader (Python's
/// `HTMLParser`) counted them as open, so the first `<br>` or `<img>` inside an
/// element kept it open and swallowed every later element of the page; they
/// open and close at once here.
const VOID_ELEMENTS: [&str; 14] = [
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
    "track", "wbr",
];
/// Elements whose content is raw text (Python `HTMLParser.CDATA_CONTENT_ELEMENTS`).
const RAW_TEXT_ELEMENTS: [&str; 2] = ["script", "style"];

/// A small HTML tokenizer with Python `HTMLParser` semantics (lower-cased names,
/// attribute values unescaped, character references decoded in text).
fn tokenize(html: &str, reader: &mut Reader) {
    let bytes = html.as_bytes();
    let mut pos = 0;
    let mut text_start = 0;
    while pos < bytes.len() {
        if bytes[pos] != b'<' {
            pos += 1;
            continue;
        }
        let next = bytes.get(pos + 1).copied();
        let flush = |reader: &mut Reader, end: usize| {
            if end > text_start {
                reader.data(&unescape(&html[text_start..end]));
            }
        };
        match next {
            Some(b'!') if html[pos..].starts_with("<!--") => {
                flush(reader, pos);
                pos = html[pos + 4..]
                    .find("-->")
                    .map_or(bytes.len(), |i| pos + 4 + i + 3);
                text_start = pos;
            }
            Some(b'!') | Some(b'?') => {
                flush(reader, pos);
                pos = html[pos..].find('>').map_or(bytes.len(), |i| pos + i + 1);
                text_start = pos;
            }
            Some(b'/') if bytes.get(pos + 2).is_some_and(u8::is_ascii_alphabetic) => {
                flush(reader, pos);
                pos = html[pos..].find('>').map_or(bytes.len(), |i| pos + i + 1);
                text_start = pos;
                reader.end_tag();
            }
            Some(c) if c.is_ascii_alphabetic() => {
                flush(reader, pos);
                let (name, attributes, self_closing, end) = parse_start_tag(html, pos + 1);
                pos = end;
                text_start = pos;
                reader.start_tag(&attributes);
                if self_closing || VOID_ELEMENTS.contains(&name.as_str()) {
                    reader.end_tag();
                } else if RAW_TEXT_ELEMENTS.contains(&name.as_str()) {
                    let close = format!("</{name}");
                    let lower = html[pos..].to_ascii_lowercase();
                    let content_end = lower.find(&close).map_or(bytes.len(), |i| pos + i);
                    if content_end > pos {
                        reader.data(&html[pos..content_end]);
                    }
                    pos = content_end;
                    text_start = pos;
                }
            }
            _ => pos += 1,
        }
    }
    if text_start < bytes.len() {
        reader.data(&unescape(&html[text_start..]));
    }
}

/// Parse a start tag whose name begins at `start`; returns the lower-cased
/// name, the attributes (last duplicate wins, value-less ones empty), whether
/// it ended with `/>`, and the offset after `>`.
fn parse_start_tag(html: &str, start: usize) -> (String, HashMap<String, String>, bool, usize) {
    let bytes = html.as_bytes();
    let mut pos = start;
    while pos < bytes.len()
        && !bytes[pos].is_ascii_whitespace()
        && bytes[pos] != b'>'
        && bytes[pos] != b'/'
    {
        pos += 1;
    }
    let name = html[start..pos].to_ascii_lowercase();
    let mut attributes = HashMap::new();
    let mut self_closing = false;
    loop {
        while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
            pos += 1;
        }
        if pos >= bytes.len() {
            return (name, attributes, self_closing, pos);
        }
        match bytes[pos] {
            b'>' => return (name, attributes, self_closing, pos + 1),
            b'/' => {
                self_closing = bytes.get(pos + 1) == Some(&b'>');
                pos += 1;
                continue;
            }
            _ => {}
        }
        self_closing = false;
        let name_start = pos;
        while pos < bytes.len()
            && !bytes[pos].is_ascii_whitespace()
            && !matches!(bytes[pos], b'=' | b'>' | b'/')
        {
            pos += 1;
        }
        if pos == name_start {
            pos += 1;
            continue;
        }
        let attribute = html[name_start..pos].to_ascii_lowercase();
        let mut look = pos;
        while look < bytes.len() && bytes[look].is_ascii_whitespace() {
            look += 1;
        }
        let mut value = String::new();
        if bytes.get(look) == Some(&b'=') {
            pos = look + 1;
            while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
                pos += 1;
            }
            match bytes.get(pos) {
                Some(&quote @ (b'"' | b'\'')) => {
                    let value_start = pos + 1;
                    let value_end = html[value_start..]
                        .find(char::from(quote))
                        .map_or(bytes.len(), |i| value_start + i);
                    value = unescape(&html[value_start..value_end]);
                    pos = (value_end + 1).min(bytes.len());
                }
                _ => {
                    let value_start = pos;
                    while pos < bytes.len()
                        && !bytes[pos].is_ascii_whitespace()
                        && bytes[pos] != b'>'
                    {
                        pos += 1;
                    }
                    value = unescape(&html[value_start..pos]);
                }
            }
        }
        attributes.insert(attribute, value);
    }
}

/// Decode character references (numeric, and the named ones a renderer or a
/// document title can carry).
fn unescape(text: &str) -> String {
    if !text.contains('&') {
        return text.to_string();
    }
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        rest = &rest[i..];
        let end = rest[1..]
            .find(|c: char| !(c.is_ascii_alphanumeric() || c == '#'))
            .map_or(rest.len(), |j| j + 1);
        let entity = &rest[1..end];
        let decoded = if let Some(number) = entity.strip_prefix('#') {
            let code = match number.strip_prefix(['x', 'X']) {
                Some(hex) => u32::from_str_radix(hex, 16).ok(),
                None => number.parse::<u32>().ok(),
            };
            code.map(|c| char::from_u32(c).unwrap_or('\u{fffd}'))
        } else {
            named_entity(entity)
        };
        match decoded {
            Some(ch) => {
                out.push(ch);
                let consumed = if rest[end..].starts_with(';') {
                    end + 1
                } else {
                    end
                };
                rest = &rest[consumed..];
            }
            None => {
                out.push('&');
                rest = &rest[1..];
            }
        }
    }
    out.push_str(rest);
    out
}

fn named_entity(name: &str) -> Option<char> {
    Some(match name {
        "amp" | "AMP" => '&',
        "lt" | "LT" => '<',
        "gt" | "GT" => '>',
        "quot" | "QUOT" => '"',
        "apos" => '\'',
        "nbsp" => '\u{a0}',
        "copy" => '©',
        "reg" => '®',
        "trade" => '™',
        "hellip" => '…',
        "mdash" => '—',
        "ndash" => '–',
        "bull" => '•',
        "middot" => '·',
        "lsquo" => '‘',
        "rsquo" => '’',
        "ldquo" => '“',
        "rdquo" => '”',
        "laquo" => '«',
        "raquo" => '»',
        "deg" => '°',
        "times" => '×',
        "divide" => '÷',
        "euro" => '€',
        "pound" => '£',
        "yen" => '¥',
        "cent" => '¢',
        "sect" => '§',
        "para" => '¶',
        "shy" => '\u{ad}',
        "ensp" => '\u{2002}',
        "emsp" => '\u{2003}',
        "thinsp" => '\u{2009}',
        "zwj" => '\u{200d}',
        "zwnj" => '\u{200c}',
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percent_reads_only_whole_properties() {
        assert_eq!(percent("left:6.0%;top:16%", "left"), Some(6.0));
        assert_eq!(percent("margin-left:5%;left:7%", "left"), Some(7.0));
        assert_eq!(percent("left:12px", "left"), None);
        assert_eq!(percent("top: -3.5 %", "top"), Some(-3.5));
    }

    #[test]
    fn unescapes_references() {
        assert_eq!(
            unescape("a &amp; b &lt;c&gt; &#x27;q&#39; &nbsp;&unknown;"),
            "a & b <c> 'q' \u{a0}&unknown;"
        );
    }
}
