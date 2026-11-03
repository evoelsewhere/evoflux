//! Port of the request models in app/api/schemas/settings.py and
//! `OAuthCallbackBody` (app/api/routes/auth.py), as [`body::Field`] tables.
//! Every model forbids unknown keys.

// The section routes (P-008) use the settings models; the golden test pins
// them all now.
#![allow(dead_code)]

use crate::body::{Default as D, Field, Kind};

const fn field(name: &'static str, kind: Kind, default: D) -> Field {
    Field {
        name,
        kind,
        default: Some(default),
    }
}

const fn required(name: &'static str, kind: Kind) -> Field {
    Field {
        name,
        kind,
        default: None,
    }
}

const ASK_AUTO: &[&str] = &["ask", "auto"];

pub(crate) const TEAM_SPAWN: &[Field] = &[
    field("work", Kind::Literal(ASK_AUTO), D::Str("ask")),
    field("coding", Kind::Literal(ASK_AUTO), D::Str("ask")),
];

pub(crate) const FOLLOW_UP: &[Field] = &[field(
    "delivery",
    Kind::Literal(&["steer", "queue"]),
    D::Str("queue"),
)];

pub(crate) const BACKGROUND_TASKS: &[Field] = &[field("wake_idle", Kind::Bool, D::Bool(true))];

pub(crate) const RESPONSE_STYLE: &[Field] = &[field(
    "style",
    Kind::Literal(&["simple", "visual"]),
    D::Str("visual"),
)];

pub(crate) const SANDBOX: &[Field] = &[
    field("denied_patterns", Kind::ListStr, D::EmptyList),
    field(
        "worktree_location",
        Kind::Literal(&["repository", "user_data"]),
        D::Str("repository"),
    ),
    field("inherit_shell_environment", Kind::Bool, D::Bool(false)),
    field("load_shell_profile", Kind::Bool, D::Bool(false)),
    field(
        "outbound_data_policy",
        Kind::Literal(&["block", "redact", "off"]),
        D::Str("off"),
    ),
    field(
        "outbound_pii_policy",
        Kind::Literal(&["off", "standard", "strict"]),
        D::Str("off"),
    ),
    field(
        "max_execution_seconds",
        Kind::Int(Some(5), Some(3600)),
        D::Int(600),
    ),
    field(
        "max_output_bytes",
        Kind::Int(Some(4096), Some(1_048_576)),
        D::Int(131_072),
    ),
];

const IGNORED_SETTING: &[Field] = &[required("field", Kind::Str), required("message", Kind::Str)];

pub(crate) const CONTEXT: &[Field] = &[
    field(
        "summary_trigger_tokens",
        Kind::OptInt(Some(20_000), Some(2_000_000)),
        D::Null,
    ),
    field(
        "summary_max_tokens",
        Kind::OptInt(Some(2_000), Some(120_000)),
        D::Null,
    ),
    field(
        "keep_recent_turns",
        Kind::OptInt(Some(0), Some(10)),
        D::Null,
    ),
    field(
        "tool_result_offload_chars",
        Kind::OptInt(Some(2_000), Some(500_000)),
        D::Null,
    ),
    field(
        "keep_recent_tool_batches",
        Kind::OptInt(Some(1), Some(12)),
        D::Null,
    ),
    field("defaults", Kind::DictInt, D::EmptyDict),
    field("coding_defaults", Kind::DictInt, D::EmptyDict),
    field(
        "ignored",
        Kind::ListModel("IgnoredSettingBody", IGNORED_SETTING),
        D::EmptyList,
    ),
    field("max_tokens", Kind::Int(Some(0), None), D::Int(0)),
    field(
        "context_ratio",
        Kind::Float(Some(0.0), Some(1.0)),
        D::Float(0.0),
    ),
];

/// The context fields a PUT writes; the rest are derived and only echoed.
pub(crate) const CONTEXT_OVERRIDES: [&str; 5] = [
    "summary_trigger_tokens",
    "summary_max_tokens",
    "keep_recent_turns",
    "tool_result_offload_chars",
    "keep_recent_tool_batches",
];

pub(crate) const VERSION_CONTROL: &[Field] = &[
    required(
        "network_timeout_seconds",
        Kind::Float(Some(10.0), Some(1800.0)),
    ),
    required("max_diff_bytes", Kind::Int(Some(64_000), Some(50_000_000))),
    required(
        "default_pull_strategy",
        Kind::Literal(&["ff_only", "merge", "rebase"]),
    ),
    required("prune_on_fetch", Kind::Bool),
    required("allow_force_push", Kind::Bool),
    required(
        "review_request_timeout_seconds",
        Kind::Float(Some(2.0), Some(300.0)),
    ),
    required("review_retry_attempts", Kind::Int(Some(0), Some(5))),
    required(
        "review_retry_backoff_seconds",
        Kind::Float(Some(0.0), Some(10.0)),
    ),
    required(
        "review_max_concurrent_repositories",
        Kind::Int(Some(1), Some(32)),
    ),
    required(
        "review_max_pages_per_repository",
        Kind::Int(Some(1), Some(20)),
    ),
    required("allow_review_mutations", Kind::Bool),
    required("allow_insecure_connections", Kind::Bool),
    required("require_successful_checks_before_merge", Kind::Bool),
];

pub(crate) const OAUTH_CALLBACK: &[Field] = &[required("code", Kind::Str)];

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
mod tests {
    use super::*;
    use crate::body::validate;
    use serde_json::{Map, Value};

    /// `tests/body_golden.json` comes from the real pydantic models
    /// (`tests/gen_body_golden.py`); every case must agree.
    #[test]
    fn every_model_matches_pydantic() {
        let golden: Map<String, Value> =
            serde_json::from_str(include_str!("../tests/body_golden.json")).unwrap();
        let models: [(&str, &[Field]); 8] = [
            ("team_spawn", TEAM_SPAWN),
            ("follow_up", FOLLOW_UP),
            ("background_tasks", BACKGROUND_TASKS),
            ("response_style", RESPONSE_STYLE),
            ("sandbox", SANDBOX),
            ("context", CONTEXT),
            ("version_control", VERSION_CONTROL),
            ("oauth_callback", OAUTH_CALLBACK),
        ];
        assert_eq!(golden.len(), models.len());
        let mut checked = 0;
        for (name, fields) in models {
            for case in golden[name].as_array().unwrap() {
                let input = case["input"].as_object().unwrap();
                let found = match validate(fields, input, &[Value::from("body")]) {
                    Ok(value) => serde_json::json!({ "ok": value }),
                    Err(errors) => serde_json::json!({ "errors": errors }),
                };
                let mut expected = case.as_object().unwrap().clone();
                expected.remove("input");
                assert_eq!(found, Value::Object(expected), "{name}: {input:?}");
                checked += 1;
            }
        }
        assert!(checked > 180, "{checked}");
    }
}
