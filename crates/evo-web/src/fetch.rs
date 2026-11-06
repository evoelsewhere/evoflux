//! Fetch a public web page and turn it into Markdown (HTML) or text.
//!
//! http and https only; every address checked ([`crate::guard`]); at most
//! [`MAX_REDIRECTS`] redirects, each checked; [`TIMEOUT`]; bodies cut at
//! [`MAX_BYTES`]; no cookies, no proxy (a proxy would resolve names where the
//! guard cannot see them). Pages are kept for [`CACHE_FOR`].

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, ACCEPT_LANGUAGE, CONTENT_TYPE};
use url::Url;

use crate::guard::{check_url, PublicResolver};

pub const MAX_REDIRECTS: usize = 5;
pub const TIMEOUT: Duration = Duration::from_secs(20);
pub const MAX_BYTES: usize = 5 * 1024 * 1024;
pub const CACHE_FOR: Duration = Duration::from_secs(15 * 60);
const MAX_URL: usize = 2000;
pub const USER_AGENT: &str = concat!("evo/", env!("CARGO_PKG_VERSION"), " (+https://github.com/evoelsewhere/evo-harness)");

#[derive(Debug, Clone)]
pub struct Page {
    pub url: String,
    /// Where redirects ended.
    pub final_url: String,
    pub status: u16,
    pub content_type: String,
    pub title: Option<String>,
    /// Markdown for HTML; the text itself otherwise.
    pub content: String,
    /// The body was longer than [`MAX_BYTES`].
    pub cut: bool,
}

/// The shared client: guarded resolver, checked redirects, no cookies.
pub fn client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        let mut headers = HeaderMap::new();
        headers.insert(
            ACCEPT,
            HeaderValue::from_static("text/html,application/xhtml+xml,text/plain;q=0.9,application/json;q=0.8,*/*;q=0.5"),
        );
        headers.insert(ACCEPT_LANGUAGE, HeaderValue::from_static("en,*;q=0.5"));
        reqwest::Client::builder()
            .user_agent(USER_AGENT)
            .default_headers(headers)
            .dns_resolver(Arc::new(PublicResolver))
            .no_proxy()
            .timeout(TIMEOUT)
            .connect_timeout(Duration::from_secs(10))
            .redirect(reqwest::redirect::Policy::custom(|attempt| {
                if attempt.previous().len() >= MAX_REDIRECTS {
                    return attempt.error(format!("more than {MAX_REDIRECTS} redirects"));
                }
                match check_url(attempt.url()) {
                    Ok(()) => attempt.follow(),
                    Err(reason) => attempt.error(format!("redirected to a refused URL: {reason}")),
                }
            }))
            .build()
            .expect("the web client builds")
    })
}

/// Check and normalise a URL the model gave.
pub fn parse_url(raw: &str) -> Result<Url, String> {
    let raw = raw.trim();
    if raw.len() > MAX_URL {
        return Err(format!("the URL is longer than {MAX_URL} characters"));
    }
    let with_scheme = if raw.contains("://") { raw.to_string() } else { format!("https://{raw}") };
    let mut url = Url::parse(&with_scheme).map_err(|e| format!("not a URL: {e}"))?;
    url.set_fragment(None);
    check_url(&url)?;
    Ok(url)
}

/// Read the body, stopping at [`MAX_BYTES`].
pub async fn read_capped(mut response: reqwest::Response) -> Result<(Vec<u8>, bool), String> {
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(describe)? {
        let room = MAX_BYTES - body.len();
        if chunk.len() >= room {
            body.extend_from_slice(&chunk[..room]);
            return Ok((body, true));
        }
        body.extend_from_slice(&chunk);
    }
    Ok((body, false))
}

/// Text from `bytes`, by the header's charset, else a `<meta charset>`, else UTF-8.
pub fn decode(bytes: &[u8], content_type: &str) -> String {
    let label = content_type
        .split(';')
        .find_map(|p| p.trim().strip_prefix("charset=").map(|c| c.trim_matches('"').to_string()))
        .or_else(|| {
            let head = String::from_utf8_lossy(&bytes[..bytes.len().min(2048)]).to_ascii_lowercase();
            let at = head.find("charset=")?;
            let rest = head[at + 8..].trim_start_matches(['"', '\'']);
            let end = rest.find(|c: char| !(c.is_ascii_alphanumeric() || c == '-' || c == '_'))?;
            Some(rest[..end].to_string())
        });
    let encoding = label
        .and_then(|l| encoding_rs::Encoding::for_label(l.as_bytes()))
        .unwrap_or(encoding_rs::UTF_8);
    encoding.decode(bytes).0.into_owned()
}

pub fn describe(error: reqwest::Error) -> String {
    let mut text = if error.is_timeout() {
        format!("timed out after {}s", TIMEOUT.as_secs())
    } else if error.is_connect() {
        "could not connect".to_string()
    } else if error.is_redirect() {
        "redirect refused".to_string()
    } else {
        "request failed".to_string()
    };
    // The innermost cause says the most ("does not resolve to a public address").
    let mut source: Option<&dyn std::error::Error> = std::error::Error::source(&error);
    let mut last = None;
    while let Some(s) = source {
        last = Some(s.to_string());
        source = s.source();
    }
    if let Some(cause) = last {
        text.push_str(": ");
        text.push_str(&cause);
    }
    text
}

fn cache() -> &'static Mutex<HashMap<String, (Instant, Page)>> {
    static CACHE: OnceLock<Mutex<HashMap<String, (Instant, Page)>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Fetch `raw` (cached for [`CACHE_FOR`]).
pub async fn fetch(raw: &str) -> Result<Page, String> {
    let url = parse_url(raw)?;
    let key = url.to_string();
    if let Some((at, page)) = cache().lock().unwrap().get(&key) {
        if at.elapsed() < CACHE_FOR {
            return Ok(page.clone());
        }
    }
    let response = client().get(url.clone()).send().await.map_err(describe)?;
    let status = response.status();
    let final_url = response.url().to_string();
    let content_type = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_ascii_lowercase();
    let (bytes, cut) = read_capped(response).await?;
    let mime = content_type.split(';').next().unwrap_or("").trim().to_string();
    let looks_html = mime.contains("html")
        || (mime.is_empty() && String::from_utf8_lossy(&bytes[..bytes.len().min(512)]).to_ascii_lowercase().contains("<html"));
    let (title, content) = if looks_html {
        let html = decode(&bytes, &content_type);
        let base = Url::parse(&final_url).unwrap_or(url.clone());
        crate::extract::html_to_markdown(&html, &base)
    } else if mime.starts_with("text/")
        || mime.contains("json")
        || mime.contains("xml")
        || mime.contains("javascript")
        || mime.contains("yaml")
        || mime.contains("toml")
        || mime.is_empty()
    {
        (None, decode(&bytes, &content_type))
    } else if mime == "application/pdf" {
        return Err("this is a PDF; web_fetch reads web pages and text. Open it in the browser, or download it and read the file".into());
    } else {
        return Err(format!("{mime} is not a page web_fetch can read; open it in the browser instead"));
    };
    if !status.is_success() {
        let snippet: String = content.chars().take(500).collect();
        return Err(format!("HTTP {} from {final_url}{}", status.as_u16(), if snippet.is_empty() { String::new() } else { format!(":\n{snippet}") }));
    }
    let page = Page {
        url: key.clone(),
        final_url,
        status: status.as_u16(),
        content_type: mime,
        title,
        content,
        cut,
    };
    let mut cache = cache().lock().unwrap();
    cache.retain(|_, (at, _)| at.elapsed() < CACHE_FOR);
    cache.insert(key, (Instant::now(), page.clone()));
    Ok(page)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urls_get_a_scheme_and_lose_fragments() {
        assert_eq!(parse_url("example.com/a#b").unwrap().as_str(), "https://example.com/a");
        assert!(parse_url("http://127.0.0.1:3000").is_err());
        assert!(parse_url(&format!("https://e.com/{}", "a".repeat(2100))).is_err());
    }

    #[test]
    fn charsets_are_honoured() {
        let latin1 = [b'c', b'a', b'f', 0xE9];
        assert_eq!(decode(&latin1, "text/html; charset=iso-8859-1"), "café");
        let meta = b"<meta charset=\"windows-1252\"><p>caf\xE9</p>";
        assert!(decode(meta, "text/html").contains("café"));
        assert_eq!(decode("xin chào".as_bytes(), "text/plain"), "xin chào");
    }

    #[tokio::test]
    async fn private_targets_fail_before_any_request() {
        assert!(fetch("http://localhost:9/").await.is_err());
        assert!(fetch("http://10.0.0.1/").await.is_err());
    }
}
