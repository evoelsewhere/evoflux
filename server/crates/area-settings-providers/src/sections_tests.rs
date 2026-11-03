//! Route-level ports of tests/api/test_settings_routes.py and sandbox_config tests.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

use axum::http::Method;
use serde_json::{json, Value};

use crate::test_support::{call, call_text};

static NEXT: AtomicU64 = AtomicU64::new(0);

async fn setup() -> (axum::Router, PathBuf) {
    let path = std::env::temp_dir().join(format!(
        "evoflux-p008-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    tokio::fs::create_dir_all(&path).await.unwrap();
    (crate::router(path.clone()), path)
}

async fn put(app: &axum::Router, name: &str, body: &Value) -> Value {
    let bytes = serde_json::to_vec(body).unwrap();
    let (status, _, found) = call(
        app,
        Method::PUT,
        &format!("/api/settings/{name}"),
        Some(("application/json", &bytes)),
    )
    .await;
    assert_eq!(status.as_u16(), 200, "{name}: {found}");
    found
}

const NAMES: [&str; 7] = [
    "sandbox",
    "context",
    "version-control",
    "team-spawn",
    "follow-up",
    "background-tasks",
    "response-style",
];

#[tokio::test]
async fn all_routes_defaults_methods_redirects_and_validation() {
    let (app, dir) = setup().await;
    for name in NAMES {
        let uri = format!("/api/settings/{name}");
        let (status, headers, value) = call(&app, Method::GET, &uri, None).await;
        assert_eq!(status.as_u16(), 200, "{name}");
        assert_eq!(headers["content-type"], "application/json");
        assert!(value.is_object());
        for method in [
            Method::HEAD,
            Method::POST,
            Method::PATCH,
            Method::DELETE,
            Method::OPTIONS,
        ] {
            let (status, headers, body) = call(&app, method.clone(), &uri, None).await;
            assert_eq!(status.as_u16(), 405, "{name} {method}");
            assert_eq!(headers["allow"], "GET");
            if method != Method::HEAD {
                assert_eq!(body, json!({"detail":"Method Not Allowed"}));
            }
        }
        let (status, headers, _) = call(&app, Method::PUT, &format!("{uri}/?q=1"), None).await;
        assert_eq!(status.as_u16(), 307);
        assert_eq!(headers["location"], format!("http://test{uri}?q=1"));
        let (status, _, value) = call(
            &app,
            Method::PUT,
            &uri,
            Some(("application/json", br#"{"unknown":1}"#)),
        )
        .await;
        assert_eq!(status.as_u16(), 422);
        assert!(value["detail"]
            .as_array()
            .unwrap()
            .iter()
            .any(|e| e["type"] == "extra_forbidden"));
    }
    assert!(!tokio::fs::try_exists(dir.join("sandbox.yaml"))
        .await
        .unwrap());
    assert!(!tokio::fs::try_exists(dir.join("settings.yaml"))
        .await
        .unwrap());
    tokio::fs::remove_dir_all(dir).await.unwrap();
}

#[tokio::test]
async fn every_section_round_trips_and_rewrites_unknown_keys() {
    let (app, dir) = setup().await;
    tokio::fs::write(dir.join("settings.yaml"), "# comment\nfuture_key: 1\n")
        .await
        .unwrap();
    let cases = [
        ("team-spawn", json!({"work":"auto","coding":"auto"})),
        ("follow-up", json!({"delivery":"steer"})),
        ("background-tasks", json!({"wake_idle":false})),
        ("response-style", json!({"style":"simple"})),
    ];
    for (name, value) in cases {
        assert_eq!(put(&app, name, &value).await, value);
        assert_eq!(
            call(&app, Method::GET, &format!("/api/settings/{name}"), None)
                .await
                .2,
            value
        );
    }
    assert_eq!(
        put(&app, "team-spawn", &json!({"work":"ask"})).await,
        json!({"work":"ask","coding":"ask"})
    );
    let (_, _, version) = call(&app, Method::GET, "/api/settings/version-control", None).await;
    let mut version = version;
    version["network_timeout_seconds"] = json!(60.0);
    version["review_retry_attempts"] = json!(5);
    assert_eq!(put(&app, "version-control", &version).await, version);
    let (_, _, text) = call_text(&app, Method::GET, "/api/settings/version-control", None).await;
    assert!(text.starts_with("{\"network_timeout_seconds\":60.0,\"max_diff_bytes\":"));
    version["review_retry_backoff_seconds"] = json!(1e-7);
    put(&app, "version-control", &version).await;
    let (_, _, text) = call_text(&app, Method::GET, "/api/settings/version-control", None).await;
    assert!(text.contains("\"review_retry_backoff_seconds\":1e-7,"));
    let text = tokio::fs::read_to_string(dir.join("settings.yaml"))
        .await
        .unwrap();
    assert!(!text.contains("future_key"));
    assert!(!text.contains("comment"));
    let loaded = evoflux_shared_settings::load(&dir.join("settings.yaml"))
        .await
        .unwrap();
    assert_eq!(loaded.follow_up.delivery, "steer");
    assert_eq!(loaded.code_reviews.retry_attempts, 5);
    tokio::fs::remove_dir_all(dir).await.unwrap();
}

#[tokio::test]
async fn context_defaults_ignored_fields_and_replacement() {
    let (app, dir) = setup().await;
    tokio::fs::write(dir.join("settings.yaml"), "context:\n  summary_trigger_tokens: 5\n  keep_recent_turns: 4\ngit:\n  network_timeout_seconds: 1\nfollow_up:\n  delivery: bogus\n").await.unwrap();
    let (_, _, body) = call(&app, Method::GET, "/api/settings/context", None).await;
    assert_eq!(body["summary_trigger_tokens"], Value::Null);
    assert_eq!(body["keep_recent_turns"], 4);
    assert_eq!(
        body["defaults"],
        json!({"summary_trigger_tokens":333842,"summary_max_tokens":30000,"keep_recent_turns":3,"tool_result_offload_chars":40000,"keep_recent_tool_batches":4})
    );
    assert_eq!(
        body["coding_defaults"],
        json!({"keep_recent_turns":2,"keep_recent_tool_batches":3})
    );
    assert_eq!(body["max_tokens"], 750000);
    assert_eq!(body["context_ratio"], 0.75);
    assert_eq!(
        body["ignored"],
        json!([{"field":"summary_trigger_tokens","message":"Input should be greater than or equal to 20000"}])
    );
    assert_eq!(
        call(&app, Method::GET, "/api/settings/follow-up", None)
            .await
            .2,
        json!({"delivery":"queue"})
    );
    let changed=put(&app,"context",&json!({"summary_max_tokens":"2000","keep_recent_turns":0,"defaults":{"x":1},"max_tokens":1,"coding_defaults":{"x":1},"context_ratio":0.1,"ignored":[{"field":"x","message":"y"}]})).await;
    assert_eq!(changed["summary_max_tokens"], 2000);
    assert_eq!(changed["keep_recent_turns"], 0);
    assert_eq!(changed["defaults"], body["defaults"]);
    assert_eq!(changed["ignored"], json!([]));
    assert_eq!(
        put(&app, "context", &json!({})).await["summary_max_tokens"],
        Value::Null
    );
    tokio::fs::remove_dir_all(dir).await.unwrap();
}

#[tokio::test]
async fn file_errors_and_validation_precedence() {
    let (app, dir) = setup().await;
    for content in ["a: [", "- 1\n", "just text"] {
        tokio::fs::write(dir.join("settings.yaml"), content)
            .await
            .unwrap();
        for name in &NAMES[1..] {
            let uri = format!("/api/settings/{name}");
            let (status, headers, text) = call_text(&app, Method::GET, &uri, None).await;
            if ["context", "version-control"].contains(name) {
                assert_eq!(status.as_u16(), 422);
                assert!(text.contains("settings.yaml"));
            } else {
                assert_eq!(status.as_u16(), 500);
                assert_eq!(text, "Internal Server Error");
                assert_eq!(headers["content-type"], "text/plain; charset=utf-8");
            }
            let (status, _, body) = call(
                &app,
                Method::PUT,
                &uri,
                Some(("application/json", br#"{"unknown":1}"#)),
            )
            .await;
            assert_eq!(status.as_u16(), 422);
            assert!(body["detail"].is_array());
        }
        let (status, _, body) = call(
            &app,
            Method::PUT,
            "/api/settings/follow-up",
            Some(("application/json", br#"{"delivery":"steer"}"#)),
        )
        .await;
        assert_eq!(status.as_u16(), 422);
        assert!(body["detail"].is_string());
        assert_eq!(
            tokio::fs::read_to_string(dir.join("settings.yaml"))
                .await
                .unwrap(),
            content
        );
    }
    tokio::fs::remove_dir_all(dir).await.unwrap();
}

#[tokio::test]
async fn sandbox_file_defaults_legacy_validation_cleaning_and_atomic_writes() {
    let (app, dir) = setup().await;
    let path = dir.join("sandbox.yaml");
    for content in [
        "",
        "false",
        "0",
        "''",
        "[]",
        "{}",
        "native_process_isolation: x\nallow_network: x\n",
    ] {
        tokio::fs::write(&path, content).await.unwrap();
        let (status, _, body) = call(&app, Method::GET, "/api/settings/sandbox", None).await;
        assert_eq!(status.as_u16(), 200, "{body}");
        assert_eq!(body["denied_patterns"], json!(["**/.env", "**/.env.*"]));
    }
    tokio::fs::write(&path, "denied_patterns: ['  ', ' a ', a, 'é']\n")
        .await
        .unwrap();
    assert_eq!(
        call(&app, Method::GET, "/api/settings/sandbox", None)
            .await
            .2["denied_patterns"],
        json!([" a ", "a", "é"])
    );
    let body=put(&app,"sandbox",&json!({"denied_patterns":[" a ","","\t","a","é"],"worktree_location":"user_data","inherit_shell_environment":"yes","load_shell_profile":true,"outbound_data_policy":"redact","outbound_pii_policy":"strict","max_execution_seconds":5,"max_output_bytes":4096})).await;
    assert_eq!(body["denied_patterns"], json!(["a", "a", "é"]));
    assert_eq!(body["inherit_shell_environment"], true);
    let text = tokio::fs::read_to_string(&path).await.unwrap();
    assert!(text.contains("\\xE9"));
    assert_eq!(
        call(&app, Method::GET, "/api/settings/sandbox", None)
            .await
            .2,
        body
    );
    assert_eq!(
        put(&app, "sandbox", &json!({})).await["denied_patterns"],
        json!([])
    );
    for content in [
        "a: [",
        "[1]",
        "1",
        "'not a mapping'",
        "max_execution_seconds: 1",
        "unknown: yes",
    ] {
        tokio::fs::write(&path, content).await.unwrap();
        let (status, _, body) = call(&app, Method::GET, "/api/settings/sandbox", None).await;
        assert_eq!(status.as_u16(), 422, "{body}");
        assert!(body["detail"].is_string());
        if content.starts_with("max_execution_seconds") || content.starts_with("unknown") {
            assert!(body["detail"]
                .as_str()
                .unwrap()
                .contains("SandboxFileConfig"));
        }
    }
    assert!(put(&app, "sandbox", &json!({})).await.is_object());
    let mut files = tokio::fs::read_dir(&dir).await.unwrap();
    while let Some(entry) = files.next_entry().await.unwrap() {
        assert!(!entry.file_name().to_string_lossy().ends_with(".tmp"));
    }
    tokio::fs::remove_dir_all(dir).await.unwrap();
}

#[tokio::test]
async fn sixteen_parallel_writers_preserve_all_sections_and_whole_sandbox_bodies() {
    let (app, dir) = setup().await;
    let mut tasks = Vec::new();
    for i in 0..16 {
        let app = app.clone();
        tasks.push(tokio::spawn(async move {
            let (name, body) = match i % 4 {
                0 => ("team-spawn", json!({"work":"auto","coding":"auto"})),
                1 => ("follow-up", json!({"delivery":"steer"})),
                2 => ("background-tasks", json!({"wake_idle":false})),
                _ => ("response-style", json!({"style":"simple"})),
            };
            put(&app, name, &body).await;
            put(
                &app,
                "sandbox",
                &json!({"denied_patterns":[format!("p{i}")],"max_execution_seconds":5+i}),
            )
            .await;
        }));
    }
    for task in tasks {
        task.await.unwrap();
    }
    let cfg = evoflux_shared_settings::load(&dir.join("settings.yaml"))
        .await
        .unwrap();
    assert_eq!(cfg.team_spawn.work, "auto");
    assert_eq!(cfg.follow_up.delivery, "steer");
    assert!(!cfg.background_tasks.wake_idle);
    assert_eq!(cfg.response_style.style, "simple");
    let body = call(&app, Method::GET, "/api/settings/sandbox", None)
        .await
        .2;
    assert_eq!(
        body["denied_patterns"],
        json!([format!(
            "p{}",
            body["max_execution_seconds"].as_i64().unwrap() - 5
        )])
    );
    tokio::fs::remove_dir_all(dir).await.unwrap();
}

#[tokio::test]
async fn filesystem_errors_are_plain_500_and_failed_sandbox_rename_cleans_the_temp() {
    let (app, dir) = setup().await;
    tokio::fs::create_dir(dir.join("settings.yaml"))
        .await
        .unwrap();
    for name in &NAMES[1..] {
        let (status, headers, text) =
            call_text(&app, Method::GET, &format!("/api/settings/{name}"), None).await;
        assert_eq!(status.as_u16(), 500, "{name}");
        assert_eq!(headers["content-type"], "text/plain; charset=utf-8");
        assert_eq!(text, "Internal Server Error");
    }
    let (status, _, text) = call_text(
        &app,
        Method::PUT,
        "/api/settings/follow-up",
        Some(("application/json", br#"{"delivery":"steer"}"#)),
    )
    .await;
    assert_eq!(status.as_u16(), 500);
    assert_eq!(text, "Internal Server Error");
    tokio::fs::create_dir(dir.join("sandbox.yaml"))
        .await
        .unwrap();
    for method in [Method::GET, Method::PUT] {
        let (status, _, text) = call_text(
            &app,
            method,
            "/api/settings/sandbox",
            Some(("application/json", b"{}")),
        )
        .await;
        assert_eq!(status.as_u16(), 500);
        assert_eq!(text, "Internal Server Error");
    }
    let mut entries = tokio::fs::read_dir(&dir).await.unwrap();
    while let Some(entry) = entries.next_entry().await.unwrap() {
        assert!(!entry.file_name().to_string_lossy().ends_with(".tmp"));
    }
    tokio::fs::remove_dir_all(dir).await.unwrap();
}

#[tokio::test]
async fn invalid_utf8_is_a_value_error_on_guarded_reads() {
    let (app, dir) = setup().await;
    tokio::fs::write(dir.join("settings.yaml"), [0xff, 0xfe])
        .await
        .unwrap();
    for name in ["context", "version-control"] {
        let (status, _, body) =
            call(&app, Method::GET, &format!("/api/settings/{name}"), None).await;
        assert_eq!(status.as_u16(), 422);
        assert!(body["detail"]
            .as_str()
            .unwrap()
            .starts_with("settings.yaml I/O error:"));
    }
    tokio::fs::remove_dir_all(dir).await.unwrap();
}
