//! Web search through DuckDuckGo's HTML results page
//! (`https://html.duckduckgo.com/html/`).
//!
//! It has no official API: this reads the page meant for browsers without
//! JavaScript, so it can stop working when the page changes or when
//! DuckDuckGo limits automated use. Requests are paced
//! ([`MIN_INTERVAL`]); after a block, searches pause for [`COOLDOWN`] and say
//! so instead of retrying. Results are cached for [`CACHE_FOR`].

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use reqwest::header::{CONTENT_TYPE, REFERER};
use scraper::{Html, Selector};
use serde::Serialize;
use url::Url;

use crate::fetch::{client, decode, describe, read_capped};

const ENDPOINT: &str = "https://html.duckduckgo.com/html/";
pub const MIN_INTERVAL: Duration = Duration::from_millis(1500);
pub const COOLDOWN: Duration = Duration::from_secs(90);
pub const CACHE_FOR: Duration = Duration::from_secs(10 * 60);
pub const MAX_RESULTS: usize = 20;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SearchResult {
    pub title: String,
    pub url: String,
    pub snippet: String,
}

#[derive(Debug, Clone, Default)]
pub struct Query {
    pub query: String,
    pub max_results: usize,
    pub allowed_domains: Vec<String>,
    pub blocked_domains: Vec<String>,
    /// `day`, `week`, `month` or `year`.
    pub recency: Option<String>,
}

struct Pace {
    last: Option<Instant>,
    blocked_until: Option<Instant>,
}

fn pace() -> &'static tokio::sync::Mutex<Pace> {
    static PACE: OnceLock<tokio::sync::Mutex<Pace>> = OnceLock::new();
    PACE.get_or_init(|| tokio::sync::Mutex::new(Pace { last: None, blocked_until: None }))
}

fn cache() -> &'static Mutex<HashMap<String, (Instant, Vec<SearchResult>)>> {
    static CACHE: OnceLock<Mutex<HashMap<String, (Instant, Vec<SearchResult>)>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn clean_domain(d: &str) -> String {
    d.trim()
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .trim_start_matches("www.")
        .trim_end_matches('/')
        .to_ascii_lowercase()
}

/// Whether `url`'s host is `domain` or under it.
fn on_domain(url: &str, domain: &str) -> bool {
    let Ok(parsed) = Url::parse(url) else { return false };
    let host = parsed.host_str().unwrap_or("").trim_start_matches("www.").to_ascii_lowercase();
    let (dom, path) = match domain.split_once('/') {
        Some((d, p)) => (d, Some(p)),
        None => (domain, None),
    };
    (host == dom || host.ends_with(&format!(".{dom}")))
        && path.is_none_or(|p| parsed.path().trim_start_matches('/').starts_with(p))
}

/// The text DuckDuckGo gets: the query plus `site:` / `-site:` operators.
pub fn query_text(q: &Query) -> String {
    let mut text = q.query.trim().to_string();
    let allowed: Vec<String> = q.allowed_domains.iter().map(|d| clean_domain(d)).filter(|d| !d.is_empty()).collect();
    if allowed.len() == 1 {
        text.push_str(&format!(" site:{}", allowed[0]));
    } else if allowed.len() > 1 {
        let sites: Vec<String> = allowed.iter().map(|d| format!("site:{d}")).collect();
        text.push_str(&format!(" ({})", sites.join(" OR ")));
    }
    for d in &q.blocked_domains {
        let d = clean_domain(d);
        if !d.is_empty() {
            text.push_str(&format!(" -site:{d}"));
        }
    }
    text
}

/// A result link points at DuckDuckGo's redirect (`/l/?uddg=<target>`): the target.
fn target_of(href: &str) -> Option<String> {
    let absolute = if href.starts_with("//") { format!("https:{href}") } else { href.to_string() };
    let url = Url::parse(&absolute).ok()?;
    if url.host_str().is_some_and(|h| h.ends_with("duckduckgo.com")) {
        if url.path().starts_with("/y.js") {
            return None; // An ad.
        }
        return url.query_pairs().find(|(k, _)| k == "uddg").map(|(_, v)| v.into_owned());
    }
    Some(absolute)
}

fn squash(text: impl Iterator<Item = impl AsRef<str>>) -> String {
    text.map(|t| t.as_ref().to_string()).collect::<String>().split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Results on a DuckDuckGo HTML page (ads left out).
pub fn parse_results(html: &str) -> Vec<SearchResult> {
    let doc = Html::parse_document(html);
    let result = Selector::parse("div.result, div.web-result").unwrap();
    let link = Selector::parse("a.result__a").unwrap();
    let snippet = Selector::parse(".result__snippet").unwrap();
    let mut out: Vec<SearchResult> = Vec::new();
    for block in doc.select(&result) {
        let classes = block.value().attr("class").unwrap_or("");
        if classes.contains("result--ad") {
            continue;
        }
        let Some(a) = block.select(&link).next() else { continue };
        let Some(url) = a.value().attr("href").and_then(target_of) else { continue };
        if out.iter().any(|r| r.url == url) {
            continue;
        }
        out.push(SearchResult {
            title: squash(a.text()),
            url,
            snippet: block.select(&snippet).next().map(|s| squash(s.text())).unwrap_or_default(),
        });
    }
    out
}

/// DuckDuckGo answered with its "unusual traffic" check instead of results.
pub fn looks_blocked(status: u16, html: &str) -> bool {
    status == 202
        || status == 403
        || status == 429
        || html.contains("anomaly-modal")
        || html.contains("challenge-form")
        || html.contains("If this persists, please")
}

/// Search the web. Errors say what happened in a sentence for the model.
pub async fn search(q: &Query) -> Result<Vec<SearchResult>, String> {
    let text = query_text(q);
    if q.query.trim().is_empty() {
        return Err("the query is empty".into());
    }
    if text.len() > 500 {
        return Err("the query is too long (500 characters at most)".into());
    }
    let max = q.max_results.clamp(1, MAX_RESULTS);
    let recency = match q.recency.as_deref() {
        Some("day") => "d",
        Some("week") => "w",
        Some("month") => "m",
        Some("year") => "y",
        _ => "",
    };
    let key = format!("{text}\u{1}{recency}");
    if let Some((at, results)) = cache().lock().unwrap().get(&key) {
        if at.elapsed() < CACHE_FOR {
            return Ok(filter(results.clone(), q, max));
        }
    }
    let mut guard = pace().lock().await;
    if let Some(until) = guard.blocked_until {
        if Instant::now() < until {
            let wait = until.saturating_duration_since(Instant::now()).as_secs().max(1);
            return Err(format!(
                "DuckDuckGo is limiting automated searches; try again in about {wait}s, or search in the browser tool"
            ));
        }
        guard.blocked_until = None;
    }
    if let Some(last) = guard.last {
        let since = last.elapsed();
        if since < MIN_INTERVAL {
            tokio::time::sleep(MIN_INTERVAL - since).await;
        }
    }
    // Built in a block: the serializer is not `Send` and must not live across an await.
    let form = {
        let mut body = url::form_urlencoded::Serializer::new(String::new());
        body.append_pair("q", &text).append_pair("b", "").append_pair("kl", "wt-wt");
        if !recency.is_empty() {
            body.append_pair("df", recency);
        }
        body.finish()
    };
    let response = client()
        .post(ENDPOINT)
        .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
        .header(REFERER, "https://html.duckduckgo.com/")
        .body(form)
        .send()
        .await;
    guard.last = Some(Instant::now());
    let response = response.map_err(|e| format!("DuckDuckGo could not be reached: {}", describe(e)))?;
    let status = response.status().as_u16();
    let content_type = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let (bytes, _) = read_capped(response).await?;
    let html = decode(&bytes, &content_type);
    if looks_blocked(status, &html) {
        guard.blocked_until = Some(Instant::now() + COOLDOWN);
        return Err(format!(
            "DuckDuckGo is limiting automated searches (HTTP {status}); try again in about {}s, or search in the browser tool",
            COOLDOWN.as_secs()
        ));
    }
    if !(200..300).contains(&status) {
        return Err(format!("DuckDuckGo answered HTTP {status}"));
    }
    drop(guard);
    let results = parse_results(&html);
    let mut cache = cache().lock().unwrap();
    cache.retain(|_, (at, _)| at.elapsed() < CACHE_FOR);
    cache.insert(key, (Instant::now(), results.clone()));
    Ok(filter(results, q, max))
}

fn filter(results: Vec<SearchResult>, q: &Query, max: usize) -> Vec<SearchResult> {
    let allowed: Vec<String> = q.allowed_domains.iter().map(|d| clean_domain(d)).filter(|d| !d.is_empty()).collect();
    let blocked: Vec<String> = q.blocked_domains.iter().map(|d| clean_domain(d)).filter(|d| !d.is_empty()).collect();
    results
        .into_iter()
        .filter(|r| allowed.is_empty() || allowed.iter().any(|d| on_domain(&r.url, d)))
        .filter(|r| !blocked.iter().any(|d| on_domain(&r.url, d)))
        .take(max)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const PAGE: &str = r#"<html><body>
      <div class="result results_links results_links_deep result--ad">
        <a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x">Buy now</a>
      </div>
      <div class="result results_links results_links_deep web-result">
        <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdoc.rust-lang.org%2Fbook%2F&amp;rut=abc">The Rust <b>Programming</b> Language</a></h2>
        <a class="result__snippet" href="x">Learn <b>Rust</b>   the book.</a>
      </div>
      <div class="result results_links web-result">
        <a class="result__a" href="https://www.rust-lang.org/learn">Learn Rust</a>
        <div class="result__snippet">Get started.</div>
      </div>
    </body></html>"#;

    #[test]
    fn results_are_parsed_without_ads() {
        let results = parse_results(PAGE);
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].url, "https://doc.rust-lang.org/book/");
        assert_eq!(results[0].title, "The Rust Programming Language");
        assert_eq!(results[0].snippet, "Learn Rust the book.");
        assert_eq!(results[1].url, "https://www.rust-lang.org/learn");
    }

    #[test]
    fn domains_shape_the_query_and_the_results() {
        let q = Query {
            query: "ownership".into(),
            allowed_domains: vec!["https://doc.rust-lang.org/".into()],
            blocked_domains: vec!["www.pinterest.com".into()],
            ..Default::default()
        };
        assert_eq!(query_text(&q), "ownership site:doc.rust-lang.org -site:pinterest.com");
        let kept = filter(parse_results(PAGE), &q, 10);
        assert_eq!(kept.len(), 1);
        assert!(on_domain("https://blog.example.com/a", "example.com"));
        assert!(!on_domain("https://notexample.com/a", "example.com"));
        assert!(on_domain("https://example.com/docs/x", "example.com/docs"));
    }

    #[test]
    fn blocks_are_recognised() {
        assert!(looks_blocked(202, ""));
        assert!(looks_blocked(200, "<div class=\"anomaly-modal\">"));
        assert!(!looks_blocked(200, PAGE));
    }
}
