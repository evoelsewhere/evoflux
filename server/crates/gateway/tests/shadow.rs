#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

mod common;

use axum::body::Body;
use axum::routing::get as route_get;
use common::*;
use evoflux_gateway::proxy::{self, GatewayOptions};
use evoflux_gateway::record::Recorder;
use evoflux_gateway::routing::{openapi_operations, RoutingError, RoutingTable};
use evoflux_gateway::shadow::{self, Shadow, ShadowOptions};
use http_body_util::BodyExt;
use serde_json::{json, Value};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

const SHADOW_TABLE: &str = r#"
[[unit]]
name = "fake"
owner = "shadow"
routes = ["/fake/env", "/fake/child", "/fake/headers", "/fake/counter"]
services = []

[[unit]]
name = "web"
owner = "python"
routes = ["/**"]
services = []
"#;

struct Served {
    addr: SocketAddr,
    sup: Arc<evoflux_gateway::supervisor::PythonSupervisor>,
    shadow: Arc<Shadow>,
    state: tempfile::TempDir,
}

async fn serve_shadow(rust_routes: axum::Router, twice: bool, record: Option<&Recorder>) -> Served {
    let state = tempfile::tempdir().unwrap();
    let table = RoutingTable::from_toml(SHADOW_TABLE, None).unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cfg = fake_config(addr.port(), table.disabled_python_services());
    let sup = Arc::new(
        evoflux_gateway::supervisor::PythonSupervisor::start(cfg)
            .await
            .unwrap(),
    );
    let shadow = Arc::new(Shadow::new(ShadowOptions {
        state_dir: state.path().to_path_buf(),
        python_twice: twice,
    }));
    let options = GatewayOptions {
        shadow: Some(Arc::clone(&shadow)),
        recorder: record.map(|r| Arc::new(Recorder::new(r.dir()))),
    };
    let app = proxy::router_with(Arc::new(table), Arc::clone(&sup), rust_routes, options);
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    Served {
        addr,
        sup,
        shadow,
        state,
    }
}

async fn wait_compared(shadow: &Shadow, count: u64) {
    eventually(
        Duration::from_secs(10),
        "shadow comparison finished",
        || {
            let done = shadow.compared() >= count;
            async move { done }
        },
    )
    .await;
}

fn diff_lines(state: &std::path::Path) -> Vec<Value> {
    let file = state.join("shadow/fake.jsonl");
    match std::fs::read_to_string(file) {
        Ok(text) => text
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect(),
        Err(_) => Vec::new(),
    }
}

/// What Python itself answers for `/fake/env`, asked directly.
async fn python_env(served: &Served) -> Value {
    let addr = served.sup.upstream().unwrap();
    let request = hyper::Request::get(format!("http://{addr}/fake/env"))
        .header("x-evoflux-gateway", SECRET)
        .body(Body::empty())
        .unwrap();
    let response = client().request(request).await.unwrap();
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    serde_json::from_slice(&body).unwrap()
}

#[tokio::test(flavor = "multi_thread")]
async fn shadow_diff_written_for_mismatch() {
    let rust = axum::Router::new().route(
        "/fake/env",
        route_get(|| async { axum::Json(json!({"different": true})) }),
    );
    let served = serve_shadow(rust, false, None).await;
    let body = get_json(&client(), format!("http://{}/fake/env", served.addr)).await;
    assert!(
        body.get("different").is_none(),
        "client must get Python's body"
    );
    wait_compared(&served.shadow, 1).await;
    let lines = diff_lines(served.state.path());
    assert_eq!(lines.len(), 1, "{lines:?}");
    assert_eq!(lines[0]["unit"], "fake");
    assert_eq!(lines[0]["path"], "/fake/env");
    assert_eq!(lines[0]["kind"], "mismatch");
    assert!(lines[0]["diffs"].as_array().is_some_and(|d| !d.is_empty()));
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn shadow_no_diff_for_equal_after_normalize() {
    // Rust answers with Python's own body, read once the gateway is up.
    let env = Arc::new(std::sync::Mutex::new(Value::Null));
    let shared = Arc::clone(&env);
    let rust = axum::Router::new().route(
        "/fake/env",
        route_get(move || {
            let body = shared.lock().unwrap().clone();
            async move { axum::Json(body) }
        }),
    );
    let served = serve_shadow(rust, false, None).await;
    *env.lock().unwrap() = python_env(&served).await;
    get_json(&client(), format!("http://{}/fake/env", served.addr)).await;
    wait_compared(&served.shadow, 1).await;
    assert!(diff_lines(served.state.path()).is_empty());
    served.sup.shutdown().await;
}

#[test]
fn normalize_matches_python_rules() {
    let value = json!({
        "b": "8f3c1a2e-0000-4000-8000-000000000001 and 8F3C1A2E-0000-4000-8000-000000000001",
        "a": "8f3c1a2e-0000-4000-8000-000000000002",
        "t": [
            "2026-10-31T09:15:30.123456", "2026-10-31 09:15:30Z", "2026-10-31T09:15:30+07:00",
            "2026-10-31T09:15:30.5Z", "2026-10-31", "x2026-10-31", "12026-10-31", "2026-10-31T09:15"
        ],
    });
    let out = shadow::normalize(&value);
    // Keys are visited in sorted order, so "a" is uuid 1.
    assert_eq!(out["a"], "<uuid:1>");
    assert_eq!(out["b"], "<uuid:2> and <uuid:2>");
    assert_eq!(
        out["t"],
        json!([
            "<ts:naive,frac>",
            "<ts:utc-z,space>",
            "<ts:offset>",
            "<ts:utc-z,frac>",
            "<ts:date>",
            "x<ts:date>",
            "12026-10-31",
            "<ts:date>T09:15"
        ])
    );
}

#[test]
fn diff_paths_and_noise() {
    let left = json!({"a": {"b": 1, "c": [1, 2]}, "only_left": 1});
    let right = json!({"a": {"b": 2, "c": [1, 3]}});
    let paths: Vec<String> = shadow::diff(&left, &right)
        .into_iter()
        .map(|d| d.path)
        .collect();
    assert_eq!(paths, ["$.a.b", "$.a.c[1]", "$.only_left"]);
    assert!(shadow::diff(&left, &left).is_empty());
}

#[test]
fn shadow_rejects_non_get_routes() {
    let openapi = r#"{"paths": {
        "/api/a": {"get": {}, "parameters": []},
        "/api/b/{id}": {"get": {}, "delete": {}},
        "/api/c": {"post": {}}
    }}"#;
    let operations = openapi_operations(openapi).unwrap();
    let table = |owner: &str, route: &str| {
        let toml = format!(
            "[[unit]]\nname = \"u\"\nowner = \"{owner}\"\nroutes = [\"{route}\"]\nservices = []\n"
        );
        RoutingTable::from_toml(&toml, None).unwrap()
    };
    // `/api/b/{id}` has DELETE: a shadow unit that owns it is rejected, even
    // though the route itself says nothing about methods.
    let err = table("shadow", "/api/b/**")
        .check_shadow_get_only(&operations)
        .unwrap_err();
    assert!(
        matches!(err, RoutingError::ShadowNonGetOperation { ref method, .. } if method == "DELETE"),
        "{err}"
    );
    assert!(table("shadow", "/api/c")
        .check_shadow_get_only(&operations)
        .is_err());
    // GET-only paths are fine, and non-shadow units may own anything.
    assert!(table("shadow", "/api/a")
        .check_shadow_get_only(&operations)
        .is_ok());
    assert!(table("python", "/api/b/**")
        .check_shadow_get_only(&operations)
        .is_ok());
    // The runtime override turns a python unit into a shadow one.
    let overridden = RoutingTable::from_toml(
        "[[unit]]\nname = \"u\"\nowner = \"python\"\nroutes = [\"/api/c\"]\nservices = []\n",
        Some("u=shadow"),
    )
    .unwrap();
    assert!(overridden.check_shadow_get_only(&operations).is_err());
}

#[test]
fn the_real_openapi_parses_with_get_and_post() {
    let path = repo_root().join("contract-tests/openapi/python-v3.1.1.json");
    let operations = openapi_operations(&std::fs::read_to_string(path).unwrap()).unwrap();
    assert!(operations.iter().any(|(_, m)| m == "GET"));
    assert!(operations.iter().any(|(_, m)| m == "POST"));
}

#[test]
fn python_twice_flag_parsing() {
    for on in ["1", "true", "TRUE", " yes ", "on"] {
        assert!(shadow::parse_flag(Some(on)), "{on}");
    }
    for off in ["", "0", "false", "no", "off", "2"] {
        assert!(!shadow::parse_flag(Some(off)), "{off}");
    }
    assert!(!shadow::parse_flag(None));
    // Each test runs in its own process under nextest, so the environment is ours.
    std::env::remove_var("EVOFLUX_SHADOW_PYTHON_TWICE");
    assert!(!ShadowOptions::from_env("x".into()).python_twice);
    std::env::set_var("EVOFLUX_SHADOW_PYTHON_TWICE", "1");
    assert!(ShadowOptions::from_env("x".into()).python_twice);
}

#[test]
fn redact_path_decodes_query_keys() {
    use evoflux_gateway::record::redact_path;
    for key in [
        "_token",
        "%5Ftoken",
        "%5ftoken",
        "_%74oken",
        "%5F%74%6F%6B%65%6E",
    ] {
        let out = redact_path(&format!("/a?x=1&{key}=SECRET&y=2"));
        assert!(!out.contains("SECRET"), "{key}: {out}");
        assert!(out.contains("x=1") && out.contains("y=2"), "{out}");
    }
    assert_eq!(redact_path("/a?x=1"), "/a?x=1");
    assert_eq!(redact_path("/a?_token"), "/a?_token");
}

#[tokio::test(flavor = "multi_thread")]
async fn client_gets_python_response_even_if_rust_panics() {
    let rust = axum::Router::new().route(
        "/fake/env",
        route_get(|| async {
            panic!("rust handler exploded");
            #[allow(unreachable_code)]
            ""
        }),
    );
    let served = serve_shadow(rust, false, None).await;
    let body = get_json(&client(), format!("http://{}/fake/env", served.addr)).await;
    assert!(body.is_object());
    wait_compared(&served.shadow, 1).await;
    let lines = diff_lines(served.state.path());
    assert_eq!(lines.len(), 1, "{lines:?}");
    // axum answers 500 for a panicking handler only through a catch-panic layer;
    // either way the gateway reports it and the client was unaffected.
    assert!(
        lines[0]["kind"] == "rust_error" || lines[0]["kind"] == "mismatch",
        "{lines:?}"
    );
    // Python still answers afterwards.
    get_json(&client(), format!("http://{}/fake/env", served.addr)).await;
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn only_get_requests_are_shadowed() {
    let rust = axum::Router::new();
    let served = serve_shadow(rust, false, None).await;
    let request = hyper::Request::post(format!("http://{}/fake/env", served.addr))
        .body(Body::empty())
        .unwrap();
    let response = client().request(request).await.unwrap();
    assert_eq!(response.status(), 404); // Python's answer
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert_eq!(served.shadow.compared(), 0);
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn python_twice_reports_no_noise_for_stable_endpoint() {
    let rust = axum::Router::new().route(
        "/fake/env",
        route_get(|| async { axum::Json(json!({"different": true})) }),
    );
    let served = serve_shadow(rust, true, None).await;
    get_json(&client(), format!("http://{}/fake/env", served.addr)).await;
    wait_compared(&served.shadow, 1).await;
    let lines = diff_lines(served.state.path());
    assert_eq!(lines.len(), 1);
    // Python answers the same twice, so every difference is a real one.
    assert_eq!(lines[0]["noise"], json!([]));
    assert!(lines[0]["diffs"].as_array().is_some_and(|d| !d.is_empty()));
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn python_twice_reports_a_changing_endpoint_as_noise() {
    // Python's counter differs on every call and Rust's value differs from both.
    let rust = axum::Router::new().route(
        "/fake/counter",
        route_get(|| async { axum::Json(json!({"n": 1000})) }),
    );
    let served = serve_shadow(rust, true, None).await;
    get_json(&client(), format!("http://{}/fake/counter", served.addr)).await;
    wait_compared(&served.shadow, 1).await;
    let lines = diff_lines(served.state.path());
    assert_eq!(lines.len(), 1, "{lines:?}");
    assert_eq!(lines[0]["kind"], "noise", "{lines:?}");
    assert_eq!(lines[0]["noise"], json!(["$.body.n"]));
    assert_eq!(lines[0]["diffs"], json!([]));
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn without_python_twice_the_same_endpoint_is_a_plain_mismatch() {
    let rust = axum::Router::new().route(
        "/fake/counter",
        route_get(|| async { axum::Json(json!({"n": 1000})) }),
    );
    let served = serve_shadow(rust, false, None).await;
    get_json(&client(), format!("http://{}/fake/counter", served.addr)).await;
    wait_compared(&served.shadow, 1).await;
    let lines = diff_lines(served.state.path());
    assert_eq!(lines[0]["kind"], "mismatch", "{lines:?}");
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn slow_rust_handler_does_not_delay_the_client() {
    let rust = axum::Router::new().route(
        "/fake/env",
        route_get(|| async {
            tokio::time::sleep(Duration::from_secs(5)).await;
            axum::Json(json!({"slow": true}))
        }),
    );
    let served = serve_shadow(rust, false, None).await;
    let start = std::time::Instant::now();
    let body = get_json(&client(), format!("http://{}/fake/env", served.addr)).await;
    let took = start.elapsed();
    assert!(took < Duration::from_secs(1), "client waited {took:?}");
    assert!(body.get("slow").is_none());
    // The comparison still happens once Rust is done.
    wait_compared(&served.shadow, 1).await;
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn record_removes_secrets_and_stores_sse_as_events() {
    let dir = tempfile::tempdir().unwrap();
    let recorder = Recorder::new(dir.path());
    let served = serve_shadow(axum::Router::new(), false, Some(&recorder)).await;
    let base = format!("http://{}", served.addr);
    let request = hyper::Request::get(format!("{base}/fake/headers?_token=s3cr3t-token&x=1"))
        .header("authorization", "Bearer very-secret-bearer")
        .header("cookie", "session=very-secret-cookie")
        .body(Body::empty())
        .unwrap();
    client().request(request).await.unwrap();
    // The fake stream stays open after its second event; read both, then hang up.
    let response = client()
        .get(format!("{base}/fake/sse").parse().unwrap())
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let mut body = response.into_body();
    let mut seen = String::new();
    while !seen.contains("data: two") {
        let frame = body.frame().await.unwrap().unwrap();
        seen.push_str(&String::from_utf8_lossy(&frame.into_data().unwrap()));
    }
    drop(body);
    eventually(Duration::from_secs(10), "two recorded exchanges", || {
        let file = dir.path().join("traffic.jsonl");
        let lines = std::fs::read_to_string(file).map_or(0, |t| t.lines().count());
        async move { lines >= 2 }
    })
    .await;
    let text = std::fs::read_to_string(dir.path().join("traffic.jsonl")).unwrap();
    for secret in ["s3cr3t-token", "very-secret-bearer", "very-secret-cookie"] {
        assert!(!text.contains(secret), "{secret} was recorded:\n{text}");
    }
    let rows: Vec<Value> = text
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    let headers_row = rows
        .iter()
        .find(|r| r["path"].as_str().unwrap().starts_with("/fake/headers"))
        .unwrap();
    assert!(headers_row["path"]
        .as_str()
        .unwrap()
        .contains("_token=<removed>"));
    assert_eq!(headers_row["request_headers"]["authorization"], "<removed>");
    let sse_row = rows.iter().find(|r| r["path"] == "/fake/sse").unwrap();
    let events = sse_row["body"]["sse_events"].as_array().unwrap();
    assert!(events.len() >= 2, "{sse_row}");
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn recorder_captures_scrubbed_request_body_with_sequence() {
    let dir = tempfile::tempdir().unwrap();
    let recorder = Recorder::new(dir.path());
    let served = serve_shadow(axum::Router::new(), false, Some(&recorder)).await;
    let req = hyper::Request::post(format!("http://{}/fake/env", served.addr))
        .body(Body::from("contact alice@example.com"))
        .unwrap();
    let response = client().request(req).await.unwrap();
    response.into_body().collect().await.unwrap();
    let path = dir.path().join("traffic.jsonl");
    eventually(Duration::from_secs(10), "recording written", || {
        let exists = path.exists();
        async move { exists }
    })
    .await;
    let line = std::fs::read_to_string(path).unwrap();
    let row: Value = serde_json::from_str(&line).unwrap();
    assert_eq!(row["seq"], 0);
    assert_eq!(row["request_body"]["text"], "contact <email>");
    served.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn recorder_captures_empty_get_body() {
    let dir = tempfile::tempdir().unwrap();
    let recorder = Recorder::new(dir.path());
    let served = serve_shadow(axum::Router::new(), false, Some(&recorder)).await;
    get_json(&client(), format!("http://{}/fake/env", served.addr)).await;
    let path = dir.path().join("traffic.jsonl");
    eventually(Duration::from_secs(10), "recording written", || {
        let exists = path.exists();
        async move { exists }
    })
    .await;
    let line = std::fs::read_to_string(path).unwrap();
    let row: Value = serde_json::from_str(&line).unwrap();
    assert_eq!(row["request_body"]["text"], "");
    served.sup.shutdown().await;
}
