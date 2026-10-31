//! Shared by `tests/parity.rs` and `examples/provider_parity.rs`: run one
//! parity case (`contract-tests/providers/cases.py`) through [`provider_for`]
//! and [`stream_with_retry_using`], reporting the event list in the format
//! `contract-tests/providers/python_driver.py` records.

#![allow(clippy::unwrap_used, clippy::expect_used, dead_code)]

use std::sync::{Arc, Mutex};

use evoflux_area_providers::factory::PROVIDERS;
use evoflux_area_providers::retry::{stream_with_retry_using, RetryItem, Sleeper, Target};
use evoflux_area_providers::{
    provider_for, ChatRequest, Message, ProviderError, ProviderEvent, ToolSpec,
};
use evoflux_core::config::Settings;
use futures_util::{FutureExt, StreamExt};
use serde_json::{json, Map, Value};

/// `SYNTHESIZED_ID`: `call_` and 24 lowercase hex digits.
fn is_synthesized(id: &str) -> bool {
    id.strip_prefix("call_").is_some_and(|hex| {
        hex.len() == 24
            && hex
                .chars()
                .all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c))
    })
}

fn error_event(error: &ProviderError) -> Value {
    let mut event = Map::new();
    event.insert("type".into(), json!("error"));
    event.insert("kind".into(), json!(error.kind()));
    match error {
        ProviderError::Authentication { .. }
        | ProviderError::ContextOverflow { .. }
        | ProviderError::Request { .. }
        | ProviderError::RateLimited => {
            event.insert("message".into(), json!(error.to_string()));
            if let Some(status) = error.status_code() {
                event.insert("status_code".into(), json!(status));
            }
        }
        ProviderError::Status { status, .. } => {
            event.insert("status_code".into(), json!(status));
        }
        _ => {}
    }
    Value::Object(event)
}

fn item_event(item: RetryItem) -> Value {
    match item {
        RetryItem::Event(ProviderEvent::TextDelta(text)) => json!({"type": "text", "text": text}),
        RetryItem::Event(ProviderEvent::ReasoningDelta(text)) => {
            json!({"type": "reasoning", "text": text})
        }
        RetryItem::Event(ProviderEvent::Usage(usage)) => {
            let mut event = serde_json::to_value(usage).unwrap();
            event
                .as_object_mut()
                .unwrap()
                .insert("type".into(), json!("usage"));
            event
        }
        RetryItem::Event(ProviderEvent::ToolCall {
            id,
            name,
            arguments,
        }) => json!({
            "type": "tool_call",
            "id": if is_synthesized(&id) { "<synthesized>".to_owned() } else { id },
            "name": name,
            "arguments": arguments,
        }),
        RetryItem::Event(ProviderEvent::Done { finish_reason }) => {
            json!({"type": "done", "finish_reason": finish_reason})
        }
        RetryItem::Restart => json!({"type": "restart"}),
        RetryItem::RateLimit {
            retry_after,
            attempt,
            max_attempts,
        } => json!({
            "type": "rate_limit", "retry_after": retry_after,
            "attempt": attempt, "max_attempts": max_attempts,
        }),
        RetryItem::Retry {
            model,
            attempt,
            max_attempts,
            delay_seconds,
            error_type,
            status_code,
            retry_after,
        } => json!({
            "type": "retry", "model": model, "attempt": attempt,
            "max_attempts": max_attempts, "delay_seconds": delay_seconds,
            "error_type": error_type, "status_code": status_code, "retry_after": retry_after,
        }),
        RetryItem::Exhausted {
            model,
            max_attempts,
            error_type,
            status_code,
        } => json!({
            "type": "exhausted", "model": model, "max_attempts": max_attempts,
            "error_type": error_type, "status_code": status_code,
        }),
        RetryItem::Fallback { primary, fallback } => {
            json!({"type": "fallback", "primary": primary, "fallback": fallback})
        }
    }
}

/// `vars` plus the case provider's key (`mock-key`) and `*_BASE_URL`.
pub fn settings_for(
    case: &Value,
    base_url: &str,
    mut vars: std::collections::HashMap<String, String>,
) -> Settings {
    let provider_id = case["model"].as_str().unwrap().split(':').next().unwrap();
    let config = PROVIDERS.iter().find(|p| p.id == provider_id).unwrap();
    vars.insert(config.env_var.to_owned(), "mock-key".to_owned());
    vars.insert(config.base_url_env_var.to_owned(), base_url.to_owned());
    let cwd = std::env::current_dir().unwrap();
    Settings::from_vars(&vars, Some(&cwd), &cwd).unwrap()
}

/// Run `case` against `settings` and return the event list.
pub async fn run_case(case: &Value, settings: &Settings) -> Vec<Value> {
    let model = case["model"].as_str().unwrap().to_owned();
    let provider = match provider_for(settings, &model) {
        Ok(provider) => provider,
        Err(error) => return vec![error_event(&error)],
    };
    let messages: Vec<Message> = serde_json::from_value(case["messages"].clone()).unwrap();
    let tools: Vec<ToolSpec> = serde_json::from_value(case["tools"].clone()).unwrap();
    let events = Arc::new(Mutex::new(Vec::new()));
    let sleeps = events.clone();
    let sleeper: Sleeper = Arc::new(move |delay| {
        sleeps
            .lock()
            .unwrap()
            .push(json!({"type": "sleep", "seconds": delay.as_secs_f64()}));
        async {}.boxed()
    });
    let request = ChatRequest {
        model: model.clone(),
        messages,
        tools,
        options: case["options"].clone(),
    };
    let target = Target {
        provider,
        label: model,
    };
    let mut stream = stream_with_retry_using(target, None, request, sleeper);
    while let Some(item) = stream.next().await {
        let event = match item {
            Ok(item) => item_event(item),
            Err(error) => error_event(&error),
        };
        events.lock().unwrap().push(event);
    }
    let out = events.lock().unwrap().clone();
    out
}

/// Numbers compared by value: Python writes `2` where Rust writes `2.0`.
pub fn numbers_as_f64(value: &Value) -> Value {
    match value {
        Value::Number(n) => json!(n.as_f64().unwrap()),
        Value::Array(items) => Value::Array(items.iter().map(numbers_as_f64).collect()),
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(k, v)| (k.clone(), numbers_as_f64(v)))
                .collect(),
        ),
        other => other.clone(),
    }
}
