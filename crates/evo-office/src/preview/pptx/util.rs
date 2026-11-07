//! XML lookups and Python-compatible number formatting shared by the PPTX
//! renderer. v3 ran on lxml/ElementTree and Python's `format()`; the helpers
//! here reproduce the exact strings v3 produced.

use roxmltree::Node;

pub(super) type Nd<'a> = Node<'a, 'a>;

pub(super) const A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
pub(super) const P: &str = "http://schemas.openxmlformats.org/presentationml/2006/main";
pub(super) const C: &str = "http://schemas.openxmlformats.org/drawingml/2006/chart";
pub(super) const R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

/// A shape (or deck part) that cannot be rendered; v3 skipped it (try/except).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct Skip;

pub(super) type R<T> = Result<T, Skip>;

pub(super) fn local<'a>(node: Nd<'a>) -> &'a str {
    node.tag_name().name()
}

pub(super) fn elements<'a>(node: Nd<'a>) -> impl Iterator<Item = Nd<'a>> {
    node.children().filter(Node::is_element)
}

/// First element child with local name `name` (v3 `_xml_child`).
pub(super) fn child<'a>(node: Nd<'a>, name: &str) -> Option<Nd<'a>> {
    elements(node).find(|c| local(*c) == name)
}

/// First element child in namespace `ns` named `name` (lxml `find("{ns}name")`).
pub(super) fn child_ns<'a>(node: Nd<'a>, ns: &str, name: &str) -> Option<Nd<'a>> {
    elements(node).find(|c| c.tag_name().name() == name && c.tag_name().namespace() == Some(ns))
}

/// First element child (lxml `next(iter(element))`).
pub(super) fn first_child(node: Option<Nd<'_>>) -> Option<Nd<'_>> {
    node.and_then(|n| elements(n).next())
}

/// Descendants (not self) with local name `name`, in document order.
pub(super) fn descendants<'a>(node: Nd<'a>, name: &'a str) -> impl Iterator<Item = Nd<'a>> + 'a {
    node.descendants()
        .skip(1)
        .filter(move |d| d.is_element() && local(*d) == name)
}

pub(super) fn descendant<'a>(node: Nd<'a>, name: &'a str) -> Option<Nd<'a>> {
    descendants(node, name).next()
}

/// Descendants (not self) in namespace `ns` named `name`.
pub(super) fn descendants_ns<'a>(
    node: Nd<'a>,
    ns: &'a str,
    name: &'a str,
) -> impl Iterator<Item = Nd<'a>> + 'a {
    node.descendants().skip(1).filter(move |d| {
        d.is_element() && d.tag_name().name() == name && d.tag_name().namespace() == Some(ns)
    })
}

/// Walk a path of child names (local names).
pub(super) fn path<'a>(node: Nd<'a>, names: &[&str]) -> Option<Nd<'a>> {
    let mut current = node;
    for name in names {
        current = child(current, name)?;
    }
    Some(current)
}

/// The relationship attribute `r:<name>`.
pub(super) fn r_attr<'a>(node: Nd<'a>, name: &str) -> Option<&'a str> {
    node.attribute((R, name))
}

/// The element's own leading text (lxml `.text`).
pub(super) fn own_text<'a>(node: Nd<'a>) -> Option<&'a str> {
    node.first_child()
        .filter(Node::is_text)
        .and_then(|n| n.text())
}

/// Python `int(str)`.
pub(super) fn py_int(text: &str) -> Option<i64> {
    let trimmed = text.trim();
    if trimmed.contains('_') {
        let valid = !trimmed.starts_with('_') && !trimmed.ends_with('_') && !trimmed.contains("__");
        return if valid {
            trimmed.replace('_', "").parse().ok()
        } else {
            None
        };
    }
    trimmed.parse().ok()
}

/// Python `float(str)`.
pub(super) fn py_float(text: &str) -> Option<f64> {
    let trimmed = text.trim();
    if trimmed.contains('_') {
        return None;
    }
    trimmed.parse().ok()
}

/// lxml/python-pptx `XsdBoolean`-ish truthiness used by `_xml_bool`.
pub(super) fn xml_bool(value: Option<&str>) -> Option<bool> {
    value.map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "on" | "yes"))
}

/// python-pptx `XsdBoolean` (`"1"`/`"true"`).
pub(super) fn xsd_bool(value: Option<&str>) -> bool {
    matches!(value, Some("1") | Some("true"))
}

/// Python `str.isspace` for one character.
pub(super) fn py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Python `" ".join(text.split())`.
pub(super) fn split_join(text: &str) -> String {
    text.split(py_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

/// Python `str.strip()`.
pub(super) fn py_strip(text: &str) -> &str {
    text.trim_matches(py_space)
}

/// Python `math.isclose(a, b, abs_tol=…)` with the default `rel_tol=1e-9`.
pub(super) fn isclose(a: f64, b: f64, abs_tol: f64) -> bool {
    if a == b {
        return true;
    }
    if a.is_infinite() || b.is_infinite() {
        return false;
    }
    let diff = (a - b).abs();
    diff <= 1e-9 * b.abs() || diff <= 1e-9 * a.abs() || diff <= abs_tol
}

/// Python `f"{value:.{digits}f}"`.
pub(super) fn f(value: f64, digits: usize) -> String {
    if value.is_nan() {
        return "nan".into();
    }
    if value.is_infinite() {
        return if value > 0.0 {
            "inf".into()
        } else {
            "-inf".into()
        };
    }
    format!("{value:.digits$}")
}

/// Python `f"{value:g}"`.
pub(super) fn g(value: f64) -> String {
    if value.is_nan() {
        return "nan".into();
    }
    if value.is_infinite() {
        return if value > 0.0 {
            "inf".into()
        } else {
            "-inf".into()
        };
    }
    if value == 0.0 {
        return if value.is_sign_negative() {
            "-0".into()
        } else {
            "0".into()
        };
    }
    let sci = format!("{value:.5e}");
    let (mantissa, exponent) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exponent: i32 = exponent.parse().unwrap_or(0);
    if (-4..6).contains(&exponent) {
        let digits = (5 - exponent) as usize;
        strip_zeros(&format!("{value:.digits$}"))
    } else {
        let mantissa = strip_zeros(mantissa);
        let sign = if exponent < 0 { '-' } else { '+' };
        format!("{mantissa}e{sign}{:02}", exponent.abs())
    }
}

fn strip_zeros(text: &str) -> String {
    if text.contains('.') {
        text.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        text.to_string()
    }
}

/// Python `f"{value:.0%}"`.
pub(super) fn pct0(value: f64) -> String {
    format!("{}%", f(value * 100.0, 0))
}

/// Python `repr(float)` (or `str(int)` when `integral` says the value was an int).
pub(super) fn repr(value: f64) -> String {
    if value.is_finite() && value.fract() == 0.0 && value.abs() < 1e16 {
        format!("{value:.1}")
    } else {
        format!("{value}")
    }
}

/// `str_value[:-1]` (drop the last character).
pub(super) fn drop_last(text: &str) -> &str {
    text.char_indices()
        .last()
        .map(|(i, _)| &text[..i])
        .unwrap_or("")
}

/// `100 * value / basis` with Python's exact integer product.
pub(super) fn percent_of(value: i64, basis: f64) -> f64 {
    (100i128 * value as i128) as f64 / basis
}

/// Upper bound on per-point loops over counts read from the file (python-pptx
/// iterated `range(ptCount)`; a hostile count must not exhaust memory).
pub(super) const MAX_POINTS: i64 = 100_000;

/// Python `round()` (half to even) to an integer.
pub(super) fn py_round(value: f64) -> i64 {
    value.round_ties_even() as i64
}

/// A length in EMU as a percentage of the slide width in container query
/// units (v3 `_text_length_cqw`).
pub(super) fn cqw(value: f64, slide_width: i64) -> String {
    format!("{:.4}cqw", value / slide_width.max(1) as f64 * 100.0)
}

/// A length in points as `cqw` (v3 `_point_cqw`).
pub(super) fn pt_cqw(points: f64, slide_width: i64) -> String {
    cqw(points * 12700.0, slide_width)
}

/// Hex SHA-1 of `text` (v3 used `hashlib.sha1` for SVG ids).
pub(super) fn sha1_hex(text: &str) -> String {
    let digest = sha1(text.as_bytes());
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

fn sha1(data: &[u8]) -> [u8; 20] {
    let mut h: [u32; 5] = [
        0x6745_2301,
        0xEFCD_AB89,
        0x98BA_DCFE,
        0x1032_5476,
        0xC3D2_E1F0,
    ];
    let mut message = data.to_vec();
    let bit_len = (data.len() as u64).wrapping_mul(8);
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&bit_len.to_be_bytes());
    for block in message.chunks(64) {
        let mut w = [0u32; 80];
        for (i, word) in block.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let [mut a, mut b, mut c, mut d, mut e] = h;
        for (i, word) in w.iter().enumerate() {
            let (fv, k) = match i {
                0..=19 => ((b & c) | (!b & d), 0x5A82_7999),
                20..=39 => (b ^ c ^ d, 0x6ED9_EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1B_BCDC),
                _ => (b ^ c ^ d, 0xCA62_C1D6),
            };
            let temp = a
                .rotate_left(5)
                .wrapping_add(fv)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(*word);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = temp;
        }
        for (slot, value) in h.iter_mut().zip([a, b, c, d, e]) {
            *slot = slot.wrapping_add(value);
        }
    }
    let mut out = [0u8; 20];
    for (i, word) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

/// Python 3.12+ `sum()` over floats (int start, Neumaier compensation).
pub(super) fn py_sum(values: impl IntoIterator<Item = f64>) -> f64 {
    let mut iter = values.into_iter();
    let Some(first) = iter.next() else {
        return 0.0;
    };
    let mut total = 0.0 + first;
    let mut compensation = 0.0;
    for x in iter {
        let t = total + x;
        if total.abs() >= x.abs() {
            compensation += (total - t) + x;
        } else {
            compensation += (x - t) + total;
        }
        total = t;
    }
    if compensation != 0.0 && compensation.is_finite() {
        total += compensation;
    }
    total
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats_like_python() {
        assert_eq!(g(5.0), "5");
        assert_eq!(g(-2.5), "-2.5");
        assert_eq!(g(0.30000000000000004), "0.3");
        assert_eq!(g(1234567.0), "1.23457e+06");
        assert_eq!(g(0.00001), "1e-05");
        assert_eq!(g(100000.0), "100000");
        assert_eq!(pct0(0.125), "12%");
        assert_eq!(repr(125.0), "125.0");
        assert_eq!(repr(112.5), "112.5");
        assert_eq!(f(-0.0001, 3), "-0.000");
        assert_eq!(py_round(2.5), 2);
        assert_eq!(split_join(" a\u{b}b\n c "), "a b c");
    }

    #[test]
    fn sha1_matches_reference() {
        assert_eq!(sha1_hex("abc"), "a9993e364706816aba3e25717850c26c9cd0d89d");
        assert_eq!(sha1_hex(""), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
    }
}
