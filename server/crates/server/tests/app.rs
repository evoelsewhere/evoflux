//! The Rust side of the server: panic isolation, the token it enforces on
//! Rust-owned routes, and the refusal of tailnet traffic on those routes.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

mod common;

use axum::routing::get;
use axum::Router;
use common::http_get;
use evoflux_core::auth::DesktopAuth;
use evoflux_gateway::routing::RoutingTable;
use evoflux_gateway::supervisor::{PythonConfig, PythonSupervisor};
use evoflux_server::access_key::{expected_token, AccessKeyError};
use evoflux_server::app;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

async fn serve(router: Router) -> u64 {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
    u64::from(port)
}

fn ping_routes() -> Router {
    Router::new().route("/api/ping", get(|| async { "pong" }))
}

async fn boom() -> &'static str {
    panic!("handler exploded")
}

#[tokio::test(flavor = "multi_thread")]
async fn handler_panic_returns_500_and_server_survives() {
    // Built through `app::router_with_units`, so dropping the layer there fails this test.
    let table = RoutingTable::from_toml(
        r#"
[[unit]]
name = "test-rust"
owner = "rust"
routes = ["/boom", "/ok"]
services = []

[[unit]]
name = "web"
owner = "python"
routes = ["/**"]
services = []
"#,
        None,
    )
    .unwrap();
    let units = Router::new()
        .route("/boom", get(boom))
        .route("/ok", get(|| async { "ok" }));
    let entry = common::fake_upstream();
    let sup = Arc::new(
        PythonSupervisor::start(PythonConfig {
            python_bin: common::python(),
            site_packages: entry.parent().unwrap().to_path_buf(),
            cli_entry: entry,
            desktop_token: None,
            gateway_secret: "test-gateway-secret".to_owned(),
            remote_proxy_secret: "test-remote-secret".to_owned(),
            gateway_port: 1,
            disabled_services: vec![],
            env_passthrough: vec![],
            startup_timeout: Duration::from_secs(30),
        })
        .await
        .unwrap(),
    );
    let auth = DesktopAuth::new(None, "test-remote-secret".to_owned());
    let port = serve(app::router_with_units(
        Arc::new(table),
        Arc::clone(&sup),
        auth,
        units,
    ))
    .await;
    let (status, body) = http_get(port, "/boom", &[]).await;
    assert_eq!(status, 500);
    assert_eq!(body, r#"{"detail":"Internal Server Error"}"#);
    let (status, body) = http_get(port, "/ok", &[]).await;
    assert_eq!((status, body.as_str()), (200, "ok"));
    sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn rust_routes_require_the_token() {
    let auth = DesktopAuth::new(Some("k".to_owned()), "remote-secret".to_owned());
    let port = serve(app::rust_routes(ping_routes(), auth)).await;
    assert_eq!(http_get(port, "/api/ping", &[]).await.0, 401);
    let (status, body) = http_get(port, "/api/ping", &[("Authorization", "Bearer k")]).await;
    assert_eq!((status, body.as_str()), (200, "pong"));
}

#[tokio::test(flavor = "multi_thread")]
async fn rust_routes_refuse_tailnet_requests() {
    let auth = DesktopAuth::new(Some("k".to_owned()), "remote-secret".to_owned())
        .with_embedded_proxy_required(true);
    let port = serve(app::rust_routes(ping_routes(), auth)).await;
    // A trusted tailnet request: Python would claim the single-device lock
    // first, which Rust does not do yet, so Rust refuses to serve it.
    let trusted = [
        ("Tailscale-User-Login", "user@example.com"),
        ("X-EvoFlux-Remote-Proxy", "tsnet"),
        ("X-EvoFlux-Remote-Token", "remote-secret"),
        ("Authorization", "Bearer k"),
    ];
    let (status, body) = http_get(port, "/api/ping", &trusted).await;
    assert_eq!(status, 403, "{body}");
    let json: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(json["code"], "remote_route_unavailable");
    // An untrusted one is still rejected by the auth layer, as in Python.
    let untrusted = [
        ("Tailscale-User-Login", "user@example.com"),
        ("X-EvoFlux-Remote-Proxy", "tsnet"),
        ("X-EvoFlux-Remote-Token", "wrong"),
    ];
    assert_eq!(http_get(port, "/api/ping", &untrusted).await.0, 401);
}

fn token_with(env: &[(&str, &str)], yaml: Option<&str>) -> Result<Option<String>, AccessKeyError> {
    let dir = tempfile::tempdir().unwrap();
    if let Some(yaml) = yaml {
        std::fs::write(dir.path().join("settings.yaml"), yaml).unwrap();
    }
    let vars: HashMap<String, String> = env
        .iter()
        .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
        .collect();
    expected_token(|name| vars.get(name).cloned(), dir.path())
}

#[test]
fn token_precedence_matches_python() {
    let yaml = Some("server:\n  access_key: from-yaml\n");
    let both = [
        ("EVOFLUX_DESKTOP_TOKEN", "desktop"),
        ("EVOFLUX_ACCESS_KEY", "access"),
    ];
    assert_eq!(token_with(&both, yaml).unwrap().as_deref(), Some("desktop"));
    let access = [
        ("EVOFLUX_DESKTOP_TOKEN", ""),
        ("EVOFLUX_ACCESS_KEY", "access"),
    ];
    assert_eq!(
        token_with(&access, yaml).unwrap().as_deref(),
        Some("access")
    );
    assert_eq!(token_with(&[], yaml).unwrap().as_deref(), Some("from-yaml"));
}

#[test]
fn token_absent_when_nothing_is_configured() {
    assert_eq!(token_with(&[], None).unwrap(), None);
    assert_eq!(token_with(&[], Some("")).unwrap(), None);
    assert_eq!(token_with(&[], Some("theme: dark\n")).unwrap(), None);
    assert_eq!(
        token_with(&[], Some("server:\n  port: 4082\n")).unwrap(),
        None
    );
    assert_eq!(
        token_with(&[], Some("server:\n  access_key: null\n")).unwrap(),
        None
    );
    assert_eq!(
        token_with(&[], Some("server:\n  access_key: ''\n")).unwrap(),
        None
    );
}

#[test]
fn unusable_access_key_refuses_to_start() {
    for yaml in [
        "server: [access_key\n",
        "- not\n- a mapping\n",
        "server: just-a-string\n",
        "server:\n  access_key: 12345\n",
        "server:\n  access_key: [a, b]\n",
    ] {
        match token_with(&[], Some(yaml)) {
            Err(error) => assert!(error.to_string().contains("settings.yaml"), "{error}"),
            Ok(token) => panic!("{yaml:?} gave {token:?}"),
        }
    }
}

#[test]
fn environment_token_skips_settings_yaml() {
    // Python never reaches settings.yaml when the environment has a token.
    let env = [("EVOFLUX_DESKTOP_TOKEN", "desktop")];
    assert_eq!(
        token_with(&env, Some("server: [broken\n"))
            .unwrap()
            .as_deref(),
        Some("desktop")
    );
}

#[test]
fn settings_path_is_the_config_dir() {
    assert_eq!(
        evoflux_server::access_key::settings_path(Path::new("cfg")),
        Path::new("cfg").join("settings.yaml")
    );
}
