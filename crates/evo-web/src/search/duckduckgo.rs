//! DuckDuckGo's HTML results page (`https://html.duckduckgo.com/html/`).
//!
//! It has no official API: this reads the page meant for browsers without
//! JavaScript, with evo's own user agent, so it stops working when the page
//! changes or DuckDuckGo limits automated use. Requests are paced
//! ([`MIN_INTERVAL`]); after a block this backend pauses for [`COOLDOWN`]
//! and the chain moves on, instead of retrying.

use std::time::{Duration, Instant};

use reqwest::header::{CONTENT_TYPE, REFERER};
use scraper::{Html, Selector};
use url::Url;

use super::{allowed, blocked, clip, squash, Pause, Query, SearchResult};
use crate::fetch::{client, decode, describe, read_capped};

const ENDPOINT: &str = "https://html.duckduckgo.com/html/";
pub const MIN_INTERVAL: Duration = Duration::from_millis(1500);
pub const COOLDOWN: Duration = Duration::from_secs(90);

static PAUSE: Pause = Pause::new();

/// When the last request went out; held while a request is in flight.
fn last() -> &'static tokio::sync::Mutex<Option<Instant>> {
    static LAST: tokio::sync::Mutex<Option<Instant>> = tokio::sync::Mutex::const_new(None);
    &LAST
}

/// The text DuckDuckGo gets: the query plus `site:` / `-site:` operators.
pub fn query_text(q: &Query) -> String {
    let mut text = q.query.trim().to_string();
    let allowed = allowed(q);
    if allowed.len() == 1 {
        text.push_str(&format!(" site:{}", allowed[0]));
    } else if allowed.len() > 1 {
        let sites: Vec<String> = allowed.iter().map(|d| format!("site:{d}")).collect();
        text.push_str(&format!(" ({})", sites.join(" OR ")));
    }
    for d in blocked(q) {
        text.push_str(&format!(" -site:{d}"));
    }
    text
}

/// A result link points at DuckDuckGo's redirect (`/l/?uddg=<target>`): the target.
fn target_of(href: &str) -> Option<String> {
    let absolute = if href.starts_with("//") {
        format!("https:{href}")
    } else {
        href.to_string()
    };
    let url = Url::parse(&absolute).ok()?;
    if url
        .host_str()
        .is_some_and(|h| h.ends_with("duckduckgo.com"))
    {
        if url.path().starts_with("/y.js") {
            return None; // An ad.
        }
        return url
            .query_pairs()
            .find(|(k, _)| k == "uddg")
            .map(|(_, v)| v.into_owned());
    }
    Some(absolute)
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
        let Some(a) = block.select(&link).next() else {
            continue;
        };
        let Some(url) = a.value().attr("href").and_then(target_of) else {
            continue;
        };
        if out.iter().any(|r| r.url == url) {
            continue;
        }
        out.push(SearchResult {
            title: squash(a.text()),
            url,
            snippet: block
                .select(&snippet)
                .next()
                .map(|s| clip(&squash(s.text())))
                .unwrap_or_default(),
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

pub async fn search(q: &Query) -> Result<Vec<SearchResult>, String> {
    PAUSE.check("DuckDuckGo")?;
    let recency = match q.recency.as_deref() {
        Some("day") => "d",
        Some("week") => "w",
        Some("month") => "m",
        Some("year") => "y",
        _ => "",
    };
    let mut last = last().lock().await;
    // A search queued behind a blocked one should not send another request.
    PAUSE.check("DuckDuckGo")?;
    if let Some(at) = *last {
        let since = at.elapsed();
        if since < MIN_INTERVAL {
            tokio::time::sleep(MIN_INTERVAL - since).await;
        }
    }
    // Built in a block: the serializer is not `Send` and must not live across an await.
    let form = {
        let mut body = url::form_urlencoded::Serializer::new(String::new());
        body.append_pair("q", &query_text(q))
            .append_pair("b", "")
            .append_pair("kl", "wt-wt");
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
    *last = Some(Instant::now());
    let response = response.map_err(|e| format!("could not be reached: {}", describe(e)))?;
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
        PAUSE.start(COOLDOWN);
        return Err(format!(
            "limiting automated searches (HTTP {status}); paused for {}s",
            COOLDOWN.as_secs()
        ));
    }
    if !(200..300).contains(&status) {
        return Err(format!("answered HTTP {status}"));
    }
    Ok(parse_results(&html))
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
    fn domains_shape_the_query() {
        let q = Query {
            query: "ownership".into(),
            allowed_domains: vec!["https://doc.rust-lang.org/".into()],
            blocked_domains: vec!["www.pinterest.com".into()],
            ..Default::default()
        };
        assert_eq!(
            query_text(&q),
            "ownership site:doc.rust-lang.org -site:pinterest.com"
        );
    }

    #[test]
    fn blocks_are_recognised() {
        assert!(looks_blocked(202, ""));
        assert!(looks_blocked(200, "<div class=\"anomaly-modal\">"));
        assert!(!looks_blocked(200, PAGE));
    }
}
