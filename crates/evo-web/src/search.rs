//! Web search without a key, through a chain of backends tried in order:
//! [`duckduckgo`] (its HTML results page), [`exa`] (Exa's hosted MCP server)
//! and [`wikipedia`] (the MediaWiki search API). The first backend with
//! results answers; one that fails or is paused is skipped, so a block on one
//! does not stop searching. Each backend paces itself and pauses after a
//! block instead of retrying. Results are cached for [`CACHE_FOR`].
//!
//! Design: `docs/features/web-search-and-fetch/sdd.md`.

pub mod duckduckgo;
pub mod exa;
pub mod wikipedia;

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::Serialize;
use url::Url;

pub const CACHE_FOR: Duration = Duration::from_secs(10 * 60);
pub const MAX_RESULTS: usize = 20;
/// Characters of a snippet kept.
pub const SNIPPET_MAX: usize = 3000;

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

/// What a search found, and which backend found it.
#[derive(Debug, Clone, PartialEq)]
pub struct Found {
    /// `DuckDuckGo`, `Exa` or `Wikipedia`.
    pub source: &'static str,
    pub results: Vec<SearchResult>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Backend {
    DuckDuckGo,
    Exa,
    Wikipedia,
}

impl Backend {
    const CHAIN: [Backend; 3] = [Backend::DuckDuckGo, Backend::Exa, Backend::Wikipedia];

    fn name(self) -> &'static str {
        match self {
            Backend::DuckDuckGo => "DuckDuckGo",
            Backend::Exa => "Exa",
            Backend::Wikipedia => "Wikipedia",
        }
    }

    /// Wikipedia can serve neither a period nor other sites.
    fn suits(self, q: &Query) -> bool {
        match self {
            Backend::Wikipedia => {
                q.recency.is_none()
                    && allowed(q).iter().all(|d| d == "wikipedia.org" || d.ends_with(".wikipedia.org"))
            }
            _ => true,
        }
    }

    async fn run(self, q: &Query, want: usize) -> Result<Vec<SearchResult>, String> {
        match self {
            Backend::DuckDuckGo => duckduckgo::search(q).await,
            Backend::Exa => exa::search(q, want).await,
            Backend::Wikipedia => wikipedia::search(&q.query, want).await,
        }
    }
}

/// A backend that pauses after a block: when it may be asked again.
pub(crate) struct Pause(Mutex<Option<Instant>>);

impl Pause {
    pub(crate) const fn new() -> Self {
        Pause(Mutex::new(None))
    }

    /// `Err` with the seconds left while paused.
    pub(crate) fn check(&self, name: &str) -> Result<(), String> {
        let mut until = self.0.lock().unwrap();
        match *until {
            Some(t) if Instant::now() < t => {
                let wait = t.saturating_duration_since(Instant::now()).as_secs().max(1);
                Err(format!("{name} is paused after limiting automated searches (about {wait}s left)"))
            }
            _ => {
                *until = None;
                Ok(())
            }
        }
    }

    pub(crate) fn start(&self, length: Duration) {
        *self.0.lock().unwrap() = Some(Instant::now() + length);
    }
}

fn cache() -> &'static Mutex<HashMap<String, (Instant, Found)>> {
    static CACHE: OnceLock<Mutex<HashMap<String, (Instant, Found)>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(crate) fn clean_domain(d: &str) -> String {
    d.trim()
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .trim_start_matches("www.")
        .trim_end_matches('/')
        .to_ascii_lowercase()
}

pub(crate) fn allowed(q: &Query) -> Vec<String> {
    q.allowed_domains.iter().map(|d| clean_domain(d)).filter(|d| !d.is_empty()).collect()
}

pub(crate) fn blocked(q: &Query) -> Vec<String> {
    q.blocked_domains.iter().map(|d| clean_domain(d)).filter(|d| !d.is_empty()).collect()
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

/// Collapse whitespace.
pub(crate) fn squash(text: impl Iterator<Item = impl AsRef<str>>) -> String {
    text.map(|t| t.as_ref().to_string()).collect::<String>().split_whitespace().collect::<Vec<_>>().join(" ")
}

/// `text` cut at [`SNIPPET_MAX`] characters.
pub(crate) fn clip(text: &str) -> String {
    match text.char_indices().nth(SNIPPET_MAX) {
        Some((at, _)) => format!("{}…", text[..at].trim_end()),
        None => text.to_string(),
    }
}

/// Search the web. Errors say what happened in a sentence for the model.
pub async fn search(q: &Query) -> Result<Found, String> {
    if q.query.trim().is_empty() {
        return Err("the query is empty".into());
    }
    if duckduckgo::query_text(q).len() > 500 {
        return Err("the query is too long (500 characters at most)".into());
    }
    let max = q.max_results.clamp(1, MAX_RESULTS);
    // Domain limits are also applied to the results, so ask for more.
    let want = if q.allowed_domains.is_empty() && q.blocked_domains.is_empty() { max } else { MAX_RESULTS };
    let key = format!(
        "{}\u{1}{}\u{1}{}\u{1}{}\u{1}{want}",
        q.query.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase(),
        allowed(q).join(","),
        blocked(q).join(","),
        q.recency.as_deref().unwrap_or("")
    );
    if let Some((at, found)) = cache().lock().unwrap().get(&key) {
        if at.elapsed() < CACHE_FOR {
            return Ok(Found { source: found.source, results: filter(found.results.clone(), q, max) });
        }
    }
    let mut failures: Vec<String> = Vec::new();
    for backend in Backend::CHAIN {
        if !backend.suits(q) {
            continue;
        }
        match backend.run(q, want).await {
            Ok(results) => {
                let kept = filter(results.clone(), q, max);
                if kept.is_empty() {
                    continue;
                }
                let found = Found { source: backend.name(), results };
                let mut cache = cache().lock().unwrap();
                cache.retain(|_, (at, _)| at.elapsed() < CACHE_FOR);
                cache.insert(key, (Instant::now(), found));
                return Ok(Found { source: backend.name(), results: kept });
            }
            Err(e) => failures.push(format!("{}: {e}", backend.name())),
        }
    }
    let tried = Backend::CHAIN.iter().filter(|b| b.suits(q)).count();
    if failures.len() < tried {
        // At least one backend answered, with nothing.
        return Ok(Found { source: "", results: Vec::new() });
    }
    Err(format!(
        "every search backend failed ({}); try again later, or search in the browser tool",
        failures.join("; ")
    ))
}

fn filter(results: Vec<SearchResult>, q: &Query, max: usize) -> Vec<SearchResult> {
    let allowed = allowed(q);
    let blocked = blocked(q);
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

    fn result(url: &str) -> SearchResult {
        SearchResult { title: "t".into(), url: url.into(), snippet: String::new() }
    }

    #[test]
    fn domains_filter_the_results() {
        let q = Query {
            query: "ownership".into(),
            allowed_domains: vec!["https://doc.rust-lang.org/".into()],
            blocked_domains: vec!["www.pinterest.com".into()],
            ..Default::default()
        };
        let all = vec![result("https://doc.rust-lang.org/book/"), result("https://www.rust-lang.org/learn")];
        assert_eq!(filter(all, &q, 10).len(), 1);
        assert!(on_domain("https://blog.example.com/a", "example.com"));
        assert!(!on_domain("https://notexample.com/a", "example.com"));
        assert!(on_domain("https://example.com/docs/x", "example.com/docs"));
    }

    #[test]
    fn wikipedia_is_skipped_when_it_cannot_serve_the_query() {
        let plain = Query { query: "rust".into(), ..Default::default() };
        assert!(Backend::Wikipedia.suits(&plain));
        let recent = Query { recency: Some("week".into()), ..plain.clone() };
        assert!(!Backend::Wikipedia.suits(&recent));
        let docs = Query { allowed_domains: vec!["docs.rs".into()], ..plain.clone() };
        assert!(!Backend::Wikipedia.suits(&docs));
        let wiki = Query { allowed_domains: vec!["en.wikipedia.org".into()], ..plain };
        assert!(Backend::Wikipedia.suits(&wiki));
    }

    #[test]
    fn pauses_end() {
        let pause = Pause::new();
        assert!(pause.check("X").is_ok());
        pause.start(Duration::from_secs(60));
        assert!(pause.check("X").unwrap_err().contains("paused"));
        pause.start(Duration::ZERO);
        assert!(pause.check("X").is_ok());
    }

    #[test]
    fn snippets_are_clipped_on_a_character() {
        let long = "é".repeat(SNIPPET_MAX + 5);
        assert_eq!(clip(&long).chars().count(), SNIPPET_MAX + 1);
        assert_eq!(clip("short"), "short");
    }
}
