//! Port of app/agent/hooks/title_generation.py and
//! app/services/title_service.py: on a session's first turn, once the main
//! stream has produced its first chunk, ask the same model for a short title
//! (a non-streamed Chat Completions call), save it, record its usage as the
//! `title` phase and publish `title_update`. Failures are logged and dropped.

use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime};

use axum::http::header::{AUTHORIZATION, CONTENT_TYPE};
use axum::http::{HeaderMap, HeaderName, HeaderValue};
use evoflux_area_providers::{factory, Usage};
use evoflux_core::config::Settings;
use serde_json::{json, Value};

use crate::store;
use crate::usage::{self, TurnUsage};
use crate::ChatState;

/// `TITLE_GENERATION_PROMPT`.
pub(crate) const TITLE_GENERATION_PROMPT: &str =
    "You are a title generator. You output ONLY a conversation title. Nothing else.

Generate a brief title that would help the user find this conversation later.

Your output must be:
- A single line
- <=50 characters
- No explanations

Rules:
- Use the same language as the user message you are summarizing.
- Title must be grammatically correct and read naturally.
- Focus on the main topic, question, or goal the user wants to accomplish.
- Keep exact proper nouns, numbers, names, and specific terms relevant to the topic.
- Never respond to the conversation; only generate a title for it.
";

/// `_MAX_CONTENT_CHARS` and `_TITLE_TIMEOUT`.
const MAX_CONTENT_CHARS: usize = 500;
const TITLE_TIMEOUT: Duration = Duration::from_secs(15);

/// `_clean_title`.
pub(crate) fn clean_title(raw: &str) -> String {
    let t = raw.trim().trim_matches(|c| c == '"' || c == '\'');
    t.trim_end_matches('.').trim().chars().take(255).collect()
}

/// The request body of `provider.chat(messages, max_tokens=20,
/// temperature=0.2[, thinking_level="none"])` on a Chat Completions provider.
pub(crate) fn request_body(model: &str, user_text: &str, thinking_off: bool) -> Value {
    let text: String = user_text.chars().take(MAX_CONTENT_CHARS).collect();
    let mut body = json!({
        "model": model,
        "messages": [
            {"role": "system", "content": TITLE_GENERATION_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
        "max_completion_tokens": 20,
        "stream": false,
    });
    if thinking_off {
        if let Value::Object(map) = &mut body {
            map.insert("reasoning_effort".into(), json!("none"));
        }
    }
    body
}

/// Content and usage of a non-streamed reply.
pub(crate) fn parse_reply(reply: &Value) -> (String, Option<Usage>) {
    let content = reply
        .pointer("/choices/0/message/content")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let usage = reply.get("usage").map(|u| {
        let int = |key: &str| u.get(key).and_then(Value::as_i64).unwrap_or(0);
        Usage {
            prompt_tokens: int("prompt_tokens"),
            completion_tokens: int("completion_tokens"),
            total_tokens: int("total_tokens"),
            cached_tokens: u
                .pointer("/prompt_tokens_details/cached_tokens")
                .and_then(Value::as_i64)
                .filter(|v| *v > 0),
            thoughts_tokens: u
                .pointer("/completion_tokens_details/reasoning_tokens")
                .and_then(Value::as_i64)
                .filter(|v| *v > 0),
            ..Usage::default()
        }
    });
    (content, usage)
}

async fn call(
    http: &evoflux_net::Client,
    settings: &Settings,
    model: &str,
    user_text: &str,
    thinking_off: bool,
) -> Option<Value> {
    let resolved = factory::resolve(settings, model, SystemTime::now()).ok()?;
    let mut headers = HeaderMap::new();
    let mut auth = HeaderValue::from_str(&format!("Bearer {}", resolved.api_key)).ok()?;
    auth.set_sensitive(true);
    headers.insert(AUTHORIZATION, auth);
    headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    for (name, value) in resolved.config.headers {
        headers.insert(
            HeaderName::from_static(name),
            HeaderValue::from_static(value),
        );
    }
    let body = request_body(&resolved.model, user_text, thinking_off);
    let send = http
        .post(format!("{}/chat/completions", resolved.base_url))
        .headers(headers)
        .json(&body)
        .send();
    let response = tokio::time::timeout(TITLE_TIMEOUT, send).await.ok()?.ok()?;
    if !response.status().is_success() {
        return None;
    }
    tokio::time::timeout(TITLE_TIMEOUT, response.json::<Value>())
        .await
        .ok()?
        .ok()
}

/// Which session a title is for and what to send.
pub(crate) struct TitleJob {
    pub sid: String,
    pub sid_hex: String,
    pub agent: String,
    pub model: String,
    pub user_text: String,
}

/// `generate_and_save_title`.
pub(crate) async fn generate_and_save(
    state: Arc<ChatState>,
    settings: Settings,
    usage_tracker: Arc<Mutex<TurnUsage>>,
    job: TitleJob,
) {
    let TitleJob {
        sid,
        sid_hex,
        agent,
        model,
        user_text,
    } = job;
    let reply = match call(&state.http, &settings, &model, &user_text, true).await {
        Some(reply) => Some(reply),
        None => call(&state.http, &settings, &model, &user_text, false).await,
    };
    let Some(reply) = reply else {
        tracing::warn!(session_id = %sid, "title_generation_llm_error");
        return;
    };
    let (content, usage) = parse_reply(&reply);
    let snapshot = usage.and_then(|u| {
        let snapshot = usage_tracker
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .record(&u, "title", &model)?;
        state
            .store
            .push(&sid, "usage", &usage::turn_total_event(&snapshot, &agent));
        Some(snapshot)
    });
    let title = clean_title(&content);
    let Some(db) = state.db.clone() else {
        return;
    };
    let saved_title = title.clone();
    let now = store::now_db();
    let result = db
        .write(move |tx| {
            if let Some(snapshot) = &snapshot {
                store::stamp_latest_assistant(tx, &sid_hex, snapshot)?;
            }
            if saved_title.is_empty() {
                return Ok(false);
            }
            store::set_title(tx, &sid_hex, &saved_title, &now)
        })
        .await;
    match result {
        Ok(true) => state.store.push(
            &sid,
            "title_update",
            &json!({"type": "title_update", "title": title}),
        ),
        Ok(false) => {}
        Err(error) => tracing::warn!(%error, "title_generation_failed"),
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    #[test]
    fn clean_title_strips_quotes_dots_and_caps_length() {
        assert_eq!(clean_title("  \"Mock title.\"  "), "Mock title");
        assert_eq!(clean_title("'Plan...' "), "Plan");
        assert_eq!(clean_title(&"x".repeat(300)).len(), 255);
        assert_eq!(clean_title(""), "");
    }

    #[test]
    fn request_matches_the_python_side_request() {
        let long = "y".repeat(600);
        let body = request_body("mock-model", &long, true);
        assert_eq!(body["messages"][1]["content"].as_str().unwrap().len(), 500);
        assert_eq!(body["reasoning_effort"], "none");
        assert_eq!(body["stream"], false);
        assert_eq!(body["max_completion_tokens"], 20);
        assert!(request_body("m", "t", false)
            .get("reasoning_effort")
            .is_none());
        assert!(TITLE_GENERATION_PROMPT.ends_with("generate a title for it.\n"));
    }

    #[test]
    fn reply_parsing_details() {
        let reply = json!({"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3,
            "total_tokens": 9, "prompt_tokens_details": {"cached_tokens": 5},
            "completion_tokens_details": {"reasoning_tokens": 0}}});
        let (content, usage) = parse_reply(&reply);
        assert_eq!(content, "");
        let usage = usage.unwrap();
        assert_eq!(usage.total_tokens, 9);
        assert_eq!(usage.cached_tokens, Some(5));
        assert_eq!(usage.thoughts_tokens, None);
    }

    /// A Chat Completions stub that records bodies and answers `status`.
    async fn stub(status: u16) -> (String, Arc<Mutex<Vec<Value>>>) {
        use axum::routing::post;
        let seen = Arc::new(Mutex::new(Vec::new()));
        let record = seen.clone();
        let app = axum::Router::new().route(
            "/v1/chat/completions",
            post(move |axum::Json(body): axum::Json<Value>| {
                let record = record.clone();
                async move {
                    record.lock().unwrap().push(body);
                    (
                        axum::http::StatusCode::from_u16(status).unwrap(),
                        axum::Json(json!({"choices": [{"message": {"content": "\"Mock title.\""}}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})),
                    )
                }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move { axum::serve(listener, app).await });
        (format!("http://{addr}/v1"), seen)
    }

    fn settings_for(base: &str) -> Settings {
        let vars = std::collections::HashMap::from([
            ("ROUTER9_BASE_URL".to_owned(), base.to_owned()),
            ("ROUTER9_API_KEY".to_owned(), "k".to_owned()),
        ]);
        let dir = std::env::temp_dir();
        Settings::from_vars(&vars, Some(&dir), &dir).unwrap()
    }

    #[tokio::test]
    async fn call_posts_a_non_streamed_request() {
        let (base, seen) = stub(200).await;
        let http = evoflux_net::build_client().unwrap();
        let reply = call(
            &http,
            &settings_for(&base),
            "router9:mock-model",
            "hi",
            true,
        )
        .await
        .unwrap();
        assert_eq!(parse_reply(&reply).0, "\"Mock title.\"");
        let body = seen.lock().unwrap()[0].clone();
        assert_eq!(body["model"], "mock-model");
        assert_eq!(body["stream"], false);
        assert_eq!(body["reasoning_effort"], "none");

        let (failing, _) = stub(500).await;
        assert!(call(
            &http,
            &settings_for(&failing),
            "router9:mock-model",
            "hi",
            true
        )
        .await
        .is_none());
    }

    #[tokio::test]
    async fn generate_records_the_title_phase_and_retries_without_thinking() {
        let (base, seen) = stub(200).await;
        let dir = std::env::temp_dir();
        let state = Arc::new(ChatState {
            settings: Arc::new(Settings::from_vars(&Default::default(), Some(&dir), &dir).unwrap()),
            db: None,
            http: evoflux_net::build_client().unwrap(),
            store: Arc::new(crate::stream_store::StreamStore::default()),
            active: Mutex::new(Default::default()),
        });
        state.store.init_turn("s", false);
        let tracker = Arc::new(Mutex::new(TurnUsage::default()));
        let job = |text: &str| TitleJob {
            sid: "s".into(),
            sid_hex: "x".into(),
            agent: "evoflux".into(),
            model: "router9:mock-model".into(),
            user_text: text.into(),
        };
        generate_and_save(
            state.clone(),
            settings_for(&base),
            tracker.clone(),
            job("hi"),
        )
        .await;
        let snapshot = tracker.lock().unwrap().snapshot().unwrap();
        assert_eq!(snapshot["phases"]["title"]["calls"], 1);
        let (replay, _rx) = state.store.attach("s").unwrap();
        assert!(replay
            .iter()
            .any(|f| f.data.contains("\"turn_total\": true")));
        assert_eq!(seen.lock().unwrap().len(), 1);

        let (failing, failed) = stub(500).await;
        generate_and_save(state, settings_for(&failing), tracker.clone(), job("hi")).await;
        let bodies = failed.lock().unwrap().clone();
        assert_eq!(bodies.len(), 2);
        assert!(bodies[1].get("reasoning_effort").is_none());
        assert_eq!(tracker.lock().unwrap().snapshot().unwrap()["calls"], 1);
    }

    #[test]
    fn reply_parsing() {
        let reply = json!({"choices": [{"message": {"content": "Mock title"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
                      "prompt_tokens_details": {"cached_tokens": 0},
                      "completion_tokens_details": {"reasoning_tokens": 4}}});
        let (content, usage) = parse_reply(&reply);
        assert_eq!(content, "Mock title");
        let usage = usage.unwrap();
        assert_eq!((usage.prompt_tokens, usage.completion_tokens), (1, 2));
        assert_eq!(usage.cached_tokens, None);
        assert_eq!(usage.thoughts_tokens, Some(4));
        assert_eq!(parse_reply(&json!({})), (String::new(), None));
    }
}
