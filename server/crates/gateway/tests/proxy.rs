#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

mod common;

use axum::body::Body;
use axum::routing::get as route_get;
use common::*;
use evoflux_gateway::routing::RoutingTable;
use http_body_util::BodyExt;
use std::time::{Duration, Instant};

const BACKEND_UNAVAILABLE: &[u8] =
    br#"{"detail":"Backend is restarting.","code":"backend_unavailable"}"#;

#[tokio::test(flavor = "multi_thread")]
async fn sse_events_not_buffered() {
    let gw = serve(python_only(), axum::Router::new()).await;
    let client = client();
    let start = Instant::now();
    let response = client
        .get(format!("http://{}/fake/sse", gw.addr).parse().unwrap())
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let mut body = response.into_body();
    let first = body.frame().await.unwrap().unwrap().into_data().unwrap();
    let first_at = start.elapsed();
    assert!(String::from_utf8_lossy(&first).contains("data: one"));
    assert!(
        first_at < Duration::from_millis(300),
        "first event after {first_at:?}"
    );
    let second = body.frame().await.unwrap().unwrap().into_data().unwrap();
    assert!(String::from_utf8_lossy(&second).contains("data: two"));
    assert!(start.elapsed() >= Duration::from_millis(900));
    gw.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn client_disconnect_reaches_upstream() {
    let gw = serve(python_only(), axum::Router::new()).await;
    let client = client();
    let response = client
        .get(format!("http://{}/fake/sse", gw.addr).parse().unwrap())
        .await
        .unwrap();
    let mut body = response.into_body();
    body.frame().await.unwrap().unwrap();
    drop(body);
    let status_url = format!("http://{}/fake/sse-status", gw.addr);
    let waited = eventually(
        Duration::from_secs(2),
        "upstream saw the disconnect",
        || {
            let client = client.clone();
            let url = status_url.clone();
            async move { !get_json(&client, url).await["disconnected_at"].is_null() }
        },
    )
    .await;
    assert!(waited < Duration::from_secs(2));
    gw.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn gateway_header_replaces_client_copy_and_auth_headers_pass() {
    let gw = serve(python_only(), axum::Router::new()).await;
    let request = hyper::Request::get(format!("http://{}/fake/headers", gw.addr))
        .header("x-evoflux-gateway", "forged")
        .header("authorization", "Bearer abc")
        .header("tailscale-user-login", "user@example.com")
        .header("x-evoflux-remote-proxy", "tsnet")
        .header("x-evoflux-remote-token", "remote-token")
        .header("x-evoflux-device-label", "phone")
        .header("connection", "keep-alive, x-hop")
        .header("x-hop", "drop-me")
        .body(Body::empty())
        .unwrap();
    let response = client().request(request).await.unwrap();
    assert_eq!(response.status(), 200);
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let headers: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(headers["x-evoflux-gateway"], SECRET);
    assert_eq!(headers["authorization"], "Bearer abc");
    assert_eq!(headers["tailscale-user-login"], "user@example.com");
    assert_eq!(headers["x-evoflux-remote-proxy"], "tsnet");
    assert_eq!(headers["x-evoflux-remote-token"], "remote-token");
    assert_eq!(headers["x-evoflux-device-label"], "phone");
    assert_eq!(headers["host"], gw.addr.to_string());
    assert!(
        headers.get("x-hop").is_none(),
        "hop-by-hop header forwarded"
    );
    assert!(headers.get("x-forwarded-for").is_none());
    gw.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn python_status_and_body_pass_through() {
    let gw = serve(python_only(), axum::Router::new()).await;
    let (status, body) = get(&client(), format!("http://{}/nope?x=1", gw.addr)).await;
    assert_eq!(status, 404);
    assert_eq!(body, br#"{"detail": "Not Found"}"#);
    gw.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn rust_owned_paths_go_to_rust_routes() {
    let table = RoutingTable::from_toml(
        r#"
[[unit]]
name = "web"
owner = "python"
routes = ["/**"]
services = []

[[unit]]
name = "ported"
owner = "rust"
routes = ["/fake/ported/**"]
services = ["otel_retention"]
"#,
        None,
    )
    .unwrap();
    let rust = axum::Router::new().route("/fake/ported/hello", route_get(|| async { "from rust" }));
    let gw = serve(table, rust).await;
    let client = client();
    let (status, body) = get(&client, format!("http://{}/fake/ported/hello", gw.addr)).await;
    assert_eq!((status, body.as_slice()), (200, b"from rust".as_slice()));
    let env = get_json(&client, format!("http://{}/fake/env", gw.addr)).await;
    assert_eq!(env["EVOFLUX_DISABLE_SERVICES"], "otel_retention");
    gw.sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn python_crash_returns_502_then_recovers() {
    let gw = serve(python_only(), axum::Router::new()).await;
    let client = client();
    let url = format!("http://{}/fake/headers", gw.addr);
    assert_eq!(get(&client, url.clone()).await.0, 200);
    let pid = gw.sup.subscribe().borrow().unwrap().pid;
    kill_pid(pid).await;
    let start = Instant::now();
    let (status, body) = get(&client, url.clone()).await;
    assert!(start.elapsed() < Duration::from_secs(1));
    assert_eq!(status, 502);
    assert_eq!(body, BACKEND_UNAVAILABLE);
    eventually(Duration::from_secs(15), "python restarted", || {
        let client = client.clone();
        let url = url.clone();
        async move { get(&client, url).await.0 == 200 }
    })
    .await;
    assert_ne!(gw.sup.subscribe().borrow().unwrap().pid, pid);
    gw.sup.shutdown().await;
    assert!(gw.sup.upstream().is_none());
    let (status, body) = get(&client, url).await;
    assert_eq!((status, body.as_slice()), (502, BACKEND_UNAVAILABLE));
}
