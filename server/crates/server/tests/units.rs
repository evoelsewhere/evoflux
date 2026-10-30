#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

mod common;

use axum::{routing::get, Router};
use common::*;
use evoflux_core::auth::DesktopAuth;
use evoflux_gateway::{
    routing::RoutingTable,
    supervisor::{PythonConfig, PythonSupervisor},
};
use evoflux_server::serve;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};

#[tokio::test]
async fn shadow_override_on_mixed_unit_exits_startup() {
    let home = tempfile::tempdir().unwrap();
    let mut server = spawn_server(
        &home,
        &fake_upstream(),
        &[],
        &[("EVOFLUX_ROUTE_OVERRIDE", "edge-stateless=shadow")],
    );
    let status = tokio::time::timeout(Duration::from_secs(30), server.wait())
        .await
        .unwrap()
        .unwrap();
    let mut stderr = String::new();
    server
        .stderr
        .take()
        .unwrap()
        .read_to_string(&mut stderr)
        .await
        .unwrap();
    assert_eq!(status.code(), Some(1), "{stderr}");
    assert!(
        stderr.contains("routing table:")
            && stderr.contains("POST")
            && stderr.contains("/api/commands/"),
        "{stderr}"
    );
}

#[tokio::test]
async fn shadow_override_on_get_only_unit_starts() {
    let home = tempfile::tempdir().unwrap();
    let mut server = spawn_server(
        &home,
        &fake_upstream(),
        &[],
        &[("EVOFLUX_ROUTE_OVERRIDE", "observability=shadow")],
    );
    let mut line = String::new();
    let mut stdout = BufReader::new(server.stdout.take().unwrap());
    tokio::time::timeout(Duration::from_secs(60), stdout.read_line(&mut line))
        .await
        .unwrap()
        .unwrap();
    assert!(line.starts_with("EVOFLUX_HANDSHAKE "));
    stop(server).await;
}

#[tokio::test]
async fn python_env_lists_rust_units() {
    let home = tempfile::tempdir().unwrap();
    let mut server = spawn_server(
        &home,
        &fake_upstream(),
        &[],
        &[(
            "EVOFLUX_ROUTE_OVERRIDE",
            "observability=rust,edge-stateless=rust",
        )],
    );
    let mut line = String::new();
    let mut stdout = BufReader::new(server.stdout.take().unwrap());
    tokio::time::timeout(Duration::from_secs(60), stdout.read_line(&mut line))
        .await
        .unwrap()
        .unwrap();
    let handshake: serde_json::Value =
        serde_json::from_str(line.trim().strip_prefix("EVOFLUX_HANDSHAKE ").unwrap()).unwrap();
    let port = handshake["port"].as_u64().unwrap();
    let (status, body) = http_get(port, "/fake/env", &[]).await;
    assert_eq!(status, 200);
    let env: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(
        env["EVOFLUX_GATEWAY_URL"],
        format!("http://127.0.0.1:{port}")
    );
    let names = env["EVOFLUX_RUST_UNITS"]
        .as_str()
        .unwrap()
        .split(',')
        .collect::<Vec<_>>();
    assert_eq!(names.len(), 2);
    assert!(names.contains(&"edge-stateless") && names.contains(&"observability"));
    stop(server).await;
}

async fn test_router(owner: &str, state: &std::path::Path) -> (u64, Arc<PythonSupervisor>) {
    let table = RoutingTable::from_toml(
        &format!("[[unit]]\nname = 'test-unit'\nowner = '{owner}'\nroutes = ['/fake/env']\n"),
        None,
    )
    .unwrap();
    let entry = fake_upstream();
    let sup = Arc::new(
        PythonSupervisor::start(PythonConfig {
            python_bin: python(),
            site_packages: entry.parent().unwrap().to_path_buf(),
            cli_entry: entry,
            desktop_token: None,
            gateway_secret: "secret".into(),
            remote_proxy_secret: "remote".into(),
            gateway_port: 1,
            disabled_services: vec![],
            env_passthrough: vec![],
            startup_timeout: Duration::from_secs(30),
        })
        .await
        .unwrap(),
    );
    let units = Router::new().route("/fake/env", get(|| async { "rust body" }));
    let router = serve::router_with_units(
        Arc::new(table),
        Arc::clone(&sup),
        DesktopAuth::new(None, "remote".into()),
        units,
        state.to_path_buf(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
    (u64::from(port), sup)
}

#[tokio::test]
async fn rust_owned_unit_dispatches_to_units_router() {
    let home = tempfile::tempdir().unwrap();
    let (port, sup) = test_router("rust", home.path()).await;
    let (status, body) = http_get(port, "/fake/env", &[]).await;
    assert_eq!((status, body.as_str()), (200, "rust body"));
    sup.shutdown().await;
}

#[tokio::test]
async fn shadow_unit_writes_jsonl_through_serve() {
    let home = tempfile::tempdir().unwrap();
    let (port, sup) = test_router("shadow", home.path()).await;
    let (status, body) = http_get(port, "/fake/env", &[]).await;
    assert_eq!(status, 200);
    assert!(body.contains("EVOFLUX_GATEWAY_SECRET"));
    let file = home.path().join("shadow/test-unit.jsonl");
    let text = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Ok(text) = tokio::fs::read_to_string(&file).await {
                if !text.is_empty() {
                    break text;
                }
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(text.lines().count(), 1);
    sup.shutdown().await;
}
