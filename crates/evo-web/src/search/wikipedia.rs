//! English Wikipedia's search API (`action=query&list=search`), the last
//! backend: it finds articles only, so it serves neither a period nor other
//! sites ([`super`] skips it then).

use reqwest::header::CONTENT_TYPE;
use scraper::Html;
use serde_json::Value;
use url::Url;

use super::{clip, squash, SearchResult};
use crate::fetch::{client, decode, describe, read_capped};

const ENDPOINT: &str = "https://en.wikipedia.org/w/api.php";

/// The article's address for a page title.
fn article_url(title: &str) -> String {
    let mut url = Url::parse("https://en.wikipedia.org/wiki/").unwrap();
    url.path_segments_mut()
        .unwrap()
        .pop_if_empty()
        .push(&title.replace(' ', "_"));
    url.into()
}

/// Results in the API's JSON (snippets come as HTML).
pub fn parse_results(json: &Value) -> Vec<SearchResult> {
    let Some(hits) = json.pointer("/query/search").and_then(Value::as_array) else {
        return Vec::new();
    };
    hits.iter()
        .filter_map(|hit| {
            let title = hit.get("title").and_then(Value::as_str)?.to_string();
            let snippet = hit.get("snippet").and_then(Value::as_str).unwrap_or("");
            let text = squash(Html::parse_fragment(snippet).root_element().text());
            Some(SearchResult {
                url: article_url(&title),
                title,
                snippet: clip(&text),
            })
        })
        .collect()
}

pub async fn search(query: &str, want: usize) -> Result<Vec<SearchResult>, String> {
    let mut url = Url::parse(ENDPOINT).unwrap();
    url.query_pairs_mut()
        .append_pair("action", "query")
        .append_pair("list", "search")
        .append_pair("srsearch", query.trim())
        .append_pair("srlimit", &want.to_string())
        .append_pair("srprop", "snippet")
        .append_pair("format", "json")
        .append_pair("formatversion", "2")
        .append_pair("utf8", "1");
    let response = client()
        .get(url)
        .send()
        .await
        .map_err(|e| format!("could not be reached: {}", describe(e)))?;
    let status = response.status().as_u16();
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
    let json: Value = serde_json::from_str(&decode(&bytes, &content_type))
        .map_err(|_| "answered with something that is not a search result".to_string())?;
    if let Some(info) = json.pointer("/error/info").and_then(Value::as_str) {
        return Err(format!("answered with an error: {info}"));
    }
    Ok(parse_results(&json))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn results_are_parsed() {
        let json: Value = serde_json::from_str(
            r#"{"query":{"search":[
                {"title":"Gold as an investment","snippet":"<span class=\"searchmatch\">Gold</span> is   bought &amp; sold"},
                {"title":"Price of gold (US$)","snippet":""}
            ]}}"#,
        )
        .unwrap();
        let results = parse_results(&json);
        assert_eq!(results.len(), 2);
        assert_eq!(
            results[0].url,
            "https://en.wikipedia.org/wiki/Gold_as_an_investment"
        );
        assert_eq!(results[0].snippet, "Gold is bought & sold");
        assert_eq!(
            results[1].url,
            "https://en.wikipedia.org/wiki/Price_of_gold_(US$)"
        );
        assert!(parse_results(&serde_json::json!({})).is_empty());
    }
}
