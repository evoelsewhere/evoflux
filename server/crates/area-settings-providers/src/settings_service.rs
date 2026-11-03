//! Port of app/api/routes/settings.py's settings.yaml load/modify/response helpers
//! and the pure compaction cost model in app/agent/hooks/summarization.py.

use std::path::Path;

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use evoflux_core::ApiError;
use evoflux_shared_settings::{
    self as settings, IgnoredSetting, RuntimeSettings, Section, SettingsError,
};
use evoflux_shared_yaml::Value as Yaml;
use serde_json::{json, Map, Value};

use crate::models::CONTEXT_OVERRIDES;
use crate::sections::Result;

const REVIEW_FIELDS: [(&str, &str); 8] = [
    ("review_request_timeout_seconds", "request_timeout_seconds"),
    ("review_retry_attempts", "retry_attempts"),
    ("review_retry_backoff_seconds", "retry_backoff_seconds"),
    (
        "review_max_concurrent_repositories",
        "max_concurrent_repositories",
    ),
    (
        "review_max_pages_per_repository",
        "max_pages_per_repository",
    ),
    ("allow_review_mutations", "allow_mutations"),
    ("allow_insecure_connections", "allow_insecure_connections"),
    (
        "require_successful_checks_before_merge",
        "require_successful_checks_before_merge",
    ),
];

fn section_key(name: &str) -> String {
    name.replace('-', "_")
}

pub(crate) fn invalid(detail: impl Into<Value>) -> Response {
    ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, detail.into()).into_response()
}

pub(crate) fn internal() -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

fn settings_error(error: SettingsError) -> Response {
    match error {
        // Python catches ValueError on load, but OSError (including save failures)
        // reaches Starlette's plain-text 500 handler. Invalid UTF-8 is ValueError.
        SettingsError::Io(ref io) if io.kind() != std::io::ErrorKind::InvalidData => internal(),
        _ => invalid(error.to_string()),
    }
}

pub(crate) async fn get(dir: &Path, name: &str) -> Result<Value> {
    if name == "sandbox" {
        return crate::sandbox::load(&dir.join("sandbox.yaml")).await;
    }
    let (cfg, ignored) = settings::load_report(&settings::settings_path(dir))
        .await
        .map_err(|e| {
            if matches!(name, "context" | "version-control") {
                settings_error(e)
            } else {
                internal()
            }
        })?;
    Ok(response(&cfg, name, &ignored))
}

pub(crate) async fn put(dir: &Path, name: &str, body: Map<String, Value>) -> Result<Value> {
    if name == "sandbox" {
        return crate::sandbox::save(&dir.join("sandbox.yaml"), body).await;
    }
    let raw = if name == "version-control" {
        let mut git = body.clone();
        let mut reviews = Map::new();
        for (api, file) in REVIEW_FIELDS {
            if let Some(value) = git.remove(api) {
                reviews.insert(file.to_owned(), value);
            }
        }
        json!({"git":git,"code_reviews":reviews})
    } else {
        let body = if name == "context" {
            body.into_iter()
                .filter(|(key, _)| CONTEXT_OVERRIDES.contains(&key.as_str()))
                .collect()
        } else {
            body
        };
        let mut raw = Map::new();
        raw.insert(section_key(name), Value::Object(body));
        Value::Object(raw)
    };
    // The HTTP model already validated every field, including lax coercion.
    let replacement = RuntimeSettings::validate(&Yaml::from_json(&raw)).map_err(|_| internal())?;
    let cfg = settings::modify(&settings::settings_path(dir), |cfg| {
        match name {
            "context" => cfg.context = replacement.context,
            "version-control" => {
                cfg.git = replacement.git;
                cfg.code_reviews = replacement.code_reviews;
            }
            "team-spawn" => cfg.team_spawn = replacement.team_spawn,
            "follow-up" => cfg.follow_up = replacement.follow_up,
            "background-tasks" => cfg.background_tasks = replacement.background_tasks,
            "response-style" => cfg.response_style = replacement.response_style,
            _ => return Err(SettingsError::NotAMapping),
        }
        Ok(cfg.clone())
    })
    .await
    .map_err(settings_error)?;
    Ok(response(&cfg, name, &[]))
}

fn section_json(section: &impl Section) -> Value {
    Yaml::Map(section.dump()).to_json()
}

fn response(cfg: &RuntimeSettings, name: &str, ignored: &[IgnoredSetting]) -> Value {
    match name {
        "context" => {
            let dumped = section_json(&cfg.context);
            let mut out = Map::new();
            for key in CONTEXT_OVERRIDES {
                out.insert(
                    key.to_owned(),
                    dumped.get(key).cloned().unwrap_or(Value::Null),
                );
            }
            out.insert(
                "defaults".into(),
                json!({
                    "summary_trigger_tokens": cost_optimal_prompt_token_threshold(),
                    "summary_max_tokens":30000,"keep_recent_turns":3,
                    "tool_result_offload_chars":40000,"keep_recent_tool_batches":4
                }),
            );
            out.insert(
                "coding_defaults".into(),
                json!({"keep_recent_turns":2,"keep_recent_tool_batches":3}),
            );
            out.insert(
                "ignored".into(),
                Value::Array(
                    ignored
                        .iter()
                        .filter_map(|item| {
                            item.field
                                .strip_prefix("context.")
                                .map(|field| json!({"field":field,"message":item.message}))
                        })
                        .collect(),
                ),
            );
            out.insert("max_tokens".into(), json!(750000));
            out.insert("context_ratio".into(), json!(0.75));
            Value::Object(out)
        }
        "version-control" => {
            let mut out = section_json(&cfg.git)
                .as_object()
                .cloned()
                .unwrap_or_default();
            let reviews = section_json(&cfg.code_reviews);
            for (api, file) in REVIEW_FIELDS {
                out.insert(
                    api.to_owned(),
                    reviews.get(file).cloned().unwrap_or(Value::Null),
                );
            }
            Value::Object(out)
        }
        "team-spawn" => section_json(&cfg.team_spawn),
        "follow-up" => section_json(&cfg.follow_up),
        "background-tasks" => section_json(&cfg.background_tasks),
        "response-style" => section_json(&cfg.response_style),
        _ => Value::Null,
    }
}

fn cost_optimal_prompt_token_threshold() -> i64 {
    // Python compaction_cost_tokens: cache read + summary output + prefix rewrite.
    let cost = 0.1 * 300_000.0 + 5.0 * 30_000.0 + (1.25 - 0.1) * 45_000.0;
    (45_000.0 + (2.0_f64 * cost * 18_000.0 / 0.1).sqrt()) as i64
}
