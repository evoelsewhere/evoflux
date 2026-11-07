//! Small helpers every renderer shares: the page wrapper, escaping, colours and
//! fonts (v3 `service.py` `_page`, `_css_color`, `_css_font_family`), and XML
//! parsing without DTDs.

use super::DOCUMENT_PREVIEW_CSP;

/// Parse XML for reading. DTDs are refused (no entity expansion).
pub fn parse_xml(text: &str) -> Result<roxmltree::Document<'_>, roxmltree::Error> {
    roxmltree::Document::parse_with_options(
        text,
        roxmltree::ParsingOptions {
            allow_dtd: false,
            ..Default::default()
        },
    )
}

/// Escape text content (`&`, `<`, `>`, and quotes — like Python `html.escape`).
pub fn escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for ch in text.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            other => out.push(other),
        }
    }
    out
}

/// The whole document (v3 `_page`): CSP and no-referrer metas, title, inline CSS.
pub fn page(title: &str, body: &str, css: &str) -> String {
    format!(
        "<!doctype html><html><head><meta charset=\"utf-8\">\
<meta http-equiv=\"Content-Security-Policy\" content=\"{}\">\
<meta name=\"referrer\" content=\"no-referrer\">\
<title>{}</title><style>{css}</style></head><body>{body}</body></html>",
        escape(DOCUMENT_PREVIEW_CSP),
        escape(title),
    )
}

/// An OpenXML colour (`RRGGBB` or `AARRGGBB`) as CSS `#rrggbb`, else `default`
/// (v3 `_css_color`).
pub fn css_color(raw: Option<&str>, default: &str) -> String {
    let Some(text) = raw.filter(|t| t.is_ascii()) else {
        return default.to_string();
    };
    let text = if text.len() == 8 { &text[2..] } else { text };
    if text.len() == 6 && text.chars().all(|c| c.is_ascii_hexdigit()) {
        format!("#{text}")
    } else {
        default.to_string()
    }
}

/// A CSS `font-family` value for an Office font name, attribute-escaped
/// (v3 `_css_font_family`).
pub fn css_font_family(name: &str) -> String {
    let family = name.replace('\\', "\\\\").replace('"', "\\\"");
    let fallback = if family.eq_ignore_ascii_case("aptos display") {
        "\"Helvetica Neue\",Arial,sans-serif"
    } else {
        "Arial,sans-serif"
    };
    escape(&format!("\"{family}\",{fallback}"))
}

/// Format a float like Python's `f"{value:.Nf}"` with trailing zeros kept.
pub fn fixed(value: f64, digits: usize) -> String {
    format!("{value:.digits$}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn colours_and_fonts_match_v3() {
        assert_eq!(css_color(Some("FF112233"), "x"), "#112233");
        assert_eq!(css_color(Some("aabbcc"), "x"), "#aabbcc");
        assert_eq!(css_color(Some("theme"), "transparent"), "transparent");
        assert_eq!(css_color(None, "inherit"), "inherit");
        assert_eq!(
            css_font_family("Calibri"),
            "&quot;Calibri&quot;,Arial,sans-serif"
        );
        assert!(css_font_family("Aptos Display").contains("Helvetica Neue"));
    }

    #[test]
    fn page_carries_the_csp() {
        let html = page("a<b", "<p>x</p>", "p{}");
        assert!(html.contains("script-src &#x27;none&#x27;"));
        assert!(html.contains("<title>a&lt;b</title>"));
    }

    #[test]
    fn dtds_are_refused() {
        assert!(parse_xml("<!DOCTYPE x [<!ENTITY a \"b\">]><x>&a;</x>").is_err());
    }
}
