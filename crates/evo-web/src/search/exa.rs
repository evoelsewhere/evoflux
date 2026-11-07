//! Exa's hosted MCP server (`https://mcp.exa.ai/mcp`), tool `web_search_exa`.
//!
//! Exa offers it to agents without a key, with a usage limit it does not
//! publish. One stateless JSON-RPC `tools/call` per search; the answer comes
//! as JSON or as server-sent events, its text a list of
//! `Title: / URL: / Published: / Author: / Highlights:` entries. After HTTP
//! 429 this backend pauses for [`COOLDOWN`].

use std::time::Duration;

use reqwest::header::{ACCEPT, CONTENT_TYPE};
use serde_json::{json, Value};
use url::Url;

use super::{allowed, blocked, clip, Pause, Query, SearchResult};
use crate::fetch::{client, decode, describe, read_capped};

const ENDPOINT: &str = "https://mcp.exa.ai/mcp";
const TOOL: &str = "web_search_exa";
pub const COOLDOWN: Duration = Duration::from_secs(60);

static PAUSE: Pause = Pause::new();

/// What the search is for, in words: Exa ranks by it. Domain limits and the
/// period go here, since the tool takes no filters.
pub fn objective(q: &Query) -> String {
    let mut text = format!("Pages that answer: {}.", q.query.trim());
    let allowed = allowed(q);
    if !allowed.is_empty() {
        text.push_str(&format!(" Only pages from {}.", allowed.join(", ")));
    }
    let blocked = blocked(q);
    if !blocked.is_empty() {
        text.push_str(&format!(" Exclude pages from {}.", blocked.join(", ")));
    }
    if let Some(period) = q.recency.as_deref().filter(|p| ["day", "week", "month", "year"].contains(p)) {
        text.push_str(&format!(" Only pages published in the past {period}."));
    }
    text
}

/// The JSON-RPC message in a reply: the whole body, or the last `data:` event.
fn message(body: &str) -> Option<Value> {
    let trimmed = body.trim_start();
    if trimmed.starts_with('{') {
        return serde_json::from_str(trimmed).ok();
    }
    body.lines()
        .rev()
        .filter_map(|l| l.strip_prefix("data:"))
        .filter_map(|d| serde_json::from_str::<Value>(d.trim()).ok())
        .find(|v| v.get("result").is_some() || v.get("error").is_some())
}

/// The tool's text, or what went wrong.
fn tool_text(msg: &Value) -> Result<String, String> {
    if let Some(error) = msg.get("error") {
        let text = error.get("message").and_then(Value::as_str).unwrap_or("unknown error");
        return Err(format!("answered with an error: {text}"));
    }
    let result = msg.get("result").ok_or("answered without a result")?;
    let text: String = result
        .get("content")
        .and_then(Value::as_array)
        .map(|c| c.iter().filter_map(|b| b.get("text").and_then(Value::as_str)).collect::<Vec<_>>().join("\n"))
        .unwrap_or_default();
    if result.get("isError").and_then(Value::as_bool) == Some(true) {
        return Err(format!("answered with an error: {}", clip(text.trim())));
    }
    Ok(text)
}

/// The entries in the tool's text. An entry starts at a `Title:` line
/// followed by a `URL:` line, so text inside a page cannot start one.
pub fn parse_results(text: &str) -> Vec<SearchResult> {
    let lines: Vec<&str> = text.lines().collect();
    let starts: Vec<usize> = (0..lines.len())
        .filter(|&i| lines[i].starts_with("Title:") && lines.get(i + 1).is_some_and(|n| n.starts_with("URL:")))
        .collect();
    let mut out: Vec<SearchResult> = Vec::new();
    for (n, &start) in starts.iter().enumerate() {
        let end = starts.get(n + 1).copied().unwrap_or(lines.len());
        let entry = &lines[start..end];
        let field = |name: &str| {
            entry
                .iter()
                .find_map(|l| l.strip_prefix(name))
                .map(|v| v.trim().to_string())
                .filter(|v| !v.is_empty() && v != "N/A")
        };
        let Some(url) = field("URL:").filter(|u| Url::parse(u).is_ok_and(|p| matches!(p.scheme(), "http" | "https")))
        else {
            continue;
        };
        if out.iter().any(|r| r.url == url) {
            continue;
        }
        let body: Vec<&str> = match entry.iter().position(|l| l.starts_with("Highlights:") || l.starts_with("Text:")) {
            Some(at) => {
                let first = entry[at].split_once(':').map(|(_, rest)| rest).unwrap_or("");
                std::iter::once(first).chain(entry[at + 1..].iter().copied()).collect()
            }
            None => Vec::new(),
        };
        let mut body = body.join("\n").trim().to_string();
        if let Some(cut) = body.strip_suffix("---") {
            body = cut.trim_end().to_string();
        }
        let published = field("Published:").map(|p| p.chars().take(10).collect::<String>());
        let snippet = match published {
            Some(date) if !body.is_empty() => format!("Published {date}. {body}"),
            Some(date) => format!("Published {date}."),
            None => body,
        };
        out.push(SearchResult {
            title: field("Title:").unwrap_or_else(|| url.clone()),
            url,
            snippet: clip(&snippet),
        });
    }
    out
}

pub async fn search(q: &Query, want: usize) -> Result<Vec<SearchResult>, String> {
    PAUSE.check("Exa")?;
    let request = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": TOOL,
            "arguments": { "query": q.query.trim(), "numResults": want, "objective": objective(q) }
        }
    });
    let response = client()
        .post(ENDPOINT)
        .header(CONTENT_TYPE, "application/json")
        .header(ACCEPT, "application/json, text/event-stream")
        .body(request.to_string())
        .send()
        .await
        .map_err(|e| format!("could not be reached: {}", describe(e)))?;
    let status = response.status().as_u16();
    if status == 429 {
        PAUSE.start(COOLDOWN);
        return Err(format!("its free limit was reached (HTTP 429); paused for {}s", COOLDOWN.as_secs()));
    }
    let content_type = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let (bytes, _) = read_capped(response).await?;
    if !(200..300).contains(&status) {
        return Err(format!("answered HTTP {status}"));
    }
    let body = decode(&bytes, &content_type);
    let msg = message(&body).ok_or("answered with something that is not a search result")?;
    let text = tool_text(&msg)?;
    if text.to_ascii_lowercase().contains("rate limit") && !text.contains("\nURL:") {
        PAUSE.start(COOLDOWN);
        return Err(format!("its free limit was reached; paused for {}s", COOLDOWN.as_secs()));
    }
    Ok(parse_results(&text))
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEXT: &str = "Title: USD gold price in the last year - Live charts
URL: https://www.goldavenue.com/en/gold-price/usd/1-year
Published: N/A
Author: N/A
Highlights:
In this chart, you can see the historical gold price.

---

Title: Why Gold Is Down Nearly 30% From Its Peak
URL: https://www.businessinsider.com/gold-price-crash-2026-11
Published: 2026-11-03T17:54:43.000Z
Author: Jennifer Sor
Highlights:
Gold is barreling toward its worst year in over a decade.

---
Title: not an entry, no URL line after it

| 1 day | 1 year |
| --- | --- |
| +0.49% | +6.29% |";

    #[test]
    fn entries_are_parsed() {
        let results = parse_results(TEXT);
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].title, "USD gold price in the last year - Live charts");
        assert_eq!(results[0].url, "https://www.goldavenue.com/en/gold-price/usd/1-year");
        assert_eq!(results[0].snippet, "In this chart, you can see the historical gold price.");
        assert!(results[1].snippet.starts_with("Published 2026-11-03. Gold is barreling"));
        assert!(results[1].snippet.ends_with("| +0.49% | +6.29% |"));
    }

    #[test]
    fn replies_are_read_as_json_or_events() {
        let event = "event: message\ndata: {\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"Title: A\\nURL: https://a.example/\"}]},\"jsonrpc\":\"2.0\",\"id\":1}\n\n";
        let text = tool_text(&message(event).unwrap()).unwrap();
        assert_eq!(parse_results(&text)[0].url, "https://a.example/");
        let plain = "{\"jsonrpc\":\"2.0\",\"id\":1,\"error\":{\"code\":-32602,\"message\":\"bad arguments\"}}";
        assert!(tool_text(&message(plain).unwrap()).unwrap_err().contains("bad arguments"));
        let failed = json!({"result": {"isError": true, "content": [{"type": "text", "text": "boom"}]}});
        assert!(tool_text(&failed).unwrap_err().contains("boom"));
    }

    #[test]
    fn the_objective_carries_the_limits() {
        let q = Query {
            query: "gold price".into(),
            allowed_domains: vec!["reuters.com".into()],
            blocked_domains: vec!["www.pinterest.com".into()],
            recency: Some("month".into()),
            ..Default::default()
        };
        assert_eq!(
            objective(&q),
            "Pages that answer: gold price. Only pages from reuters.com. Exclude pages from pinterest.com. \
             Only pages published in the past month."
        );
    }
}
