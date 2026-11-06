//! A page's main content as Markdown: the article (or main region, or body)
//! without navigation, scripts, forms and other chrome; links made absolute.

use scraper::{Html, Selector};
use url::Url;

/// Tags dropped with their content.
const SKIP: &[&str] = &[
    "script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed", "nav",
    "header", "footer", "aside", "form", "button", "select", "input", "textarea", "img", "picture",
    "video", "audio", "source", "dialog", "menu",
];

/// Candidate roots, most specific first; the first with enough text wins.
const ROOTS: &[&str] = &[
    "article",
    "main",
    "[role=main]",
    "#main-content",
    "#content",
    "#main",
    ".markdown-body",
    ".content",
    "body",
];

fn text_len(element: &scraper::ElementRef<'_>) -> usize {
    element.text().map(|t| t.trim().len()).sum()
}

/// The page's title (`<title>`, else `og:title`, else the first `h1`).
pub fn title(doc: &Html) -> Option<String> {
    let pick = |css: &str, attr: Option<&str>| {
        let selector = Selector::parse(css).ok()?;
        let el = doc.select(&selector).next()?;
        let text = match attr {
            Some(a) => el.value().attr(a)?.to_string(),
            None => el.text().collect::<String>(),
        };
        let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
        (!text.is_empty()).then_some(text)
    };
    pick("title", None)
        .or_else(|| pick("meta[property='og:title']", Some("content")))
        .or_else(|| pick("h1", None))
}

/// `(title, markdown)` of an HTML page fetched from `base`.
pub fn html_to_markdown(html: &str, base: &Url) -> (Option<String>, String) {
    let doc = Html::parse_document(html);
    let title = title(&doc);
    let body_len = Selector::parse("body")
        .ok()
        .and_then(|s| doc.select(&s).next().map(|b| text_len(&b)))
        .unwrap_or(0);
    // The most specific root that holds a fair share of the page's text.
    let root_html = ROOTS
        .iter()
        .filter_map(|css| Selector::parse(css).ok())
        .find_map(|selector| {
            let best = doc.select(&selector).max_by_key(text_len)?;
            let len = text_len(&best);
            (len >= 200 && (len * 4 >= body_len || len >= 2000)).then(|| best.html())
        })
        .unwrap_or_else(|| html.to_string());
    let converter = htmd::HtmlToMarkdown::builder().skip_tags(SKIP.to_vec()).build();
    let markdown = converter.convert(&root_html).unwrap_or_default();
    (title, tidy(&absolutize(&markdown, base)))
}

/// `[text](/path)` → `[text](https://site/path)`.
fn absolutize(markdown: &str, base: &Url) -> String {
    let mut out = String::with_capacity(markdown.len());
    let mut rest = markdown;
    while let Some(at) = rest.find("](") {
        out.push_str(&rest[..at + 2]);
        rest = &rest[at + 2..];
        let end = rest.find([')', ' ']).unwrap_or(rest.len());
        let target = &rest[..end];
        let absolute = if target.is_empty()
            || target.starts_with('#')
            || target.contains("://")
            || target.starts_with("mailto:")
        {
            target.to_string()
        } else {
            base.join(target).map(|u| u.to_string()).unwrap_or_else(|_| target.to_string())
        };
        out.push_str(&absolute);
        rest = &rest[end..];
    }
    out.push_str(rest);
    out
}

/// Drop links with no text (`[](…)`, left by images and heading anchors).
fn drop_empty_links(line: &str) -> String {
    let mut out = String::with_capacity(line.len());
    let mut rest = line;
    while let Some(at) = rest.find("[](") {
        out.push_str(&rest[..at]);
        rest = &rest[at + 3..];
        rest = rest.find(')').map_or("", |end| &rest[end + 1..]);
    }
    out.push_str(rest);
    out
}

/// Trim trailing spaces, drop empty links, collapse runs of blank lines.
fn tidy(markdown: &str) -> String {
    let mut out = String::new();
    let mut blank = 0;
    for raw in markdown.lines() {
        let cleaned = drop_empty_links(raw);
        let line = cleaned.trim_end();
        if line.trim().is_empty() && !raw.trim().is_empty() {
            continue; // A line that held only empty links.
        }
        if line.is_empty() {
            blank += 1;
            if blank > 1 {
                continue;
            }
        } else {
            blank = 0;
        }
        out.push_str(line);
        out.push('\n');
    }
    out.trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_article_is_kept_and_the_chrome_dropped() {
        let filler = "Rust is a language empowering everyone to build reliable software. ".repeat(10);
        let html = format!(
            r#"<html><head><title>Rust Book</title><script>evil()</script></head><body>
            <nav><a href="/menu">Menu item</a></nav>
            <article><h1>Ownership</h1><p>{filler}</p><p>See <a href="ch04-02.html">references</a>.</p>
            <img src="x.png" alt="diagram"><form><input name=q></form></article>
            <footer>Copyright</footer></body></html>"#
        );
        let base = Url::parse("https://doc.rust-lang.org/book/ch04-01.html").unwrap();
        let (title, md) = html_to_markdown(&html, &base);
        assert_eq!(title.as_deref(), Some("Rust Book"));
        assert!(md.contains("# Ownership"), "{md}");
        assert!(md.contains("[references](https://doc.rust-lang.org/book/ch04-02.html)"), "{md}");
        assert!(!md.contains("Menu item"), "{md}");
        assert!(!md.contains("Copyright"), "{md}");
        assert!(!md.contains("evil"), "{md}");
    }
}
