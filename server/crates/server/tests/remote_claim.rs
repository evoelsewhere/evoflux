#![allow(clippy::unwrap_used, clippy::expect_used)]
mod common;
use axum::{routing::get, Router};
use evoflux_core::{
    auth::DesktopAuth,
    db::{Db, DbOptions},
};
use evoflux_server::app;
use std::sync::Arc;

async fn server(router: Router) -> u64 {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
    u64::from(port)
}
fn headers() -> [(&'static str, &'static str); 2] {
    [
        ("Tailscale-User-Login", "alice"),
        ("X-EvoFlux-Device-Label", "phone"),
    ]
}
#[tokio::test]
async fn remote_health_never_claims_or_writes() {
    let dir = tempfile::tempdir().unwrap();
    let db = Arc::new(Db::open(&dir.path().join("db"), DbOptions::default()).unwrap());
    let routes = Router::new()
        .route("/api/health/live", get(|| async { "ok" }))
        .route("/api/health/ready", get(|| async { "ok" }));
    let port = server(app::rust_routes_with_db(
        routes,
        DesktopAuth::new(None, "secret".into()),
        Some(db.clone()),
    ))
    .await;
    assert_eq!(
        common::http_get(port, "/api/health/live", &headers())
            .await
            .0,
        200
    );
    assert_eq!(
        common::http_get(port, "/api/health/ready", &headers())
            .await
            .0,
        200
    );
    // Python's identity check still runs first: an untrusted login is 401.
    let untrusted = [
        ("Tailscale-User-Login", "alice"),
        ("X-EvoFlux-Remote-Proxy", "tsnet"),
        ("X-EvoFlux-Remote-Token", "bad"),
    ];
    assert_eq!(
        common::http_get(port, "/api/health/live", &untrusted)
            .await
            .0,
        401
    );
    assert_eq!(db.metric("EVOFLUX_db_pool_wait_seconds_count", &[]), 0.0);
}
#[tokio::test]
async fn remote_rust_route_claims() {
    let dir = tempfile::tempdir().unwrap();
    let db = Arc::new(Db::open(&dir.path().join("db"), DbOptions::default()).unwrap());
    db.write(|tx| { tx.execute_batch("CREATE TABLE remote_use_sessions (id TEXT PRIMARY KEY NOT NULL, user_login TEXT NOT NULL, device_label TEXT, claimed_at DATETIME NOT NULL, last_seen_at DATETIME NOT NULL, released_at DATETIME, idle_expires_at DATETIME NOT NULL)")?; Ok(()) }).await.unwrap();
    let routes = Router::new().route("/api/ping", get(|| async { "ok" }));
    let port = server(app::rust_routes_with_db(
        routes,
        DesktopAuth::new(None, "secret".into()),
        Some(db.clone()),
    ))
    .await;
    assert_eq!(common::http_get(port, "/api/ping", &headers()).await.0, 200);
    let count: i64 = db
        .read(|c| Ok(c.query_row("SELECT count(*) FROM remote_use_sessions", [], |r| r.get(0))?))
        .await
        .unwrap();
    assert_eq!(count, 1);
}
#[tokio::test]
async fn remote_websocket_upgrade_is_refused() {
    let routes = Router::new().route("/api/health/live", get(|| async { "ok" }));
    let port = server(app::rust_routes_with_db(
        routes,
        DesktopAuth::new(None, "secret".into()),
        None,
    ))
    .await;
    let headers = [("Tailscale-User-Login", "alice"), ("Upgrade", "websocket")];
    let (status, body) = common::http_get(port, "/api/health/live", &headers).await;
    assert_eq!(status, 403);
    assert!(body.contains("remote_route_unavailable"));
    let headers = [
        ("Tailscale-User-Login", "\u{e1}l\u{ee}ce"),
        ("Upgrade", "websocket"),
    ];
    assert_eq!(
        common::http_get(port, "/api/health/live", &headers).await.0,
        403
    );
}
#[tokio::test]
async fn distinct_non_ascii_device_labels_conflict() {
    let dir = tempfile::tempdir().unwrap();
    let db = Arc::new(Db::open(&dir.path().join("db"), DbOptions::default()).unwrap());
    db.write(|tx| { tx.execute_batch("CREATE TABLE remote_use_sessions (id TEXT PRIMARY KEY NOT NULL, user_login TEXT NOT NULL, device_label TEXT, claimed_at DATETIME NOT NULL, last_seen_at DATETIME NOT NULL, released_at DATETIME, idle_expires_at DATETIME NOT NULL)")?; Ok(()) }).await.unwrap();
    let port = server(app::rust_routes_with_db(
        Router::new().route("/api/ping", get(|| async { "ok" })),
        DesktopAuth::new(None, "secret".into()),
        Some(db),
    ))
    .await;
    assert_eq!(
        common::http_get(
            port,
            "/api/ping",
            &[
                ("Tailscale-User-Login", "alice"),
                ("X-EvoFlux-Device-Label", "téléphone")
            ]
        )
        .await
        .0,
        200
    );
    assert_eq!(
        common::http_get(
            port,
            "/api/ping",
            &[
                ("Tailscale-User-Login", "alice"),
                ("X-EvoFlux-Device-Label", "télévision")
            ]
        )
        .await
        .0,
        409
    );
}
#[tokio::test]
async fn remote_websocket_upgrade_token_list_is_refused() {
    let routes = Router::new().route("/api/ping", get(|| async { "ok" }));
    let port = server(app::rust_routes_with_db(
        routes,
        DesktopAuth::new(None, "secret".into()),
        None,
    ))
    .await;
    let headers = [
        ("Tailscale-User-Login", "alice"),
        ("Upgrade", "websocket, other"),
    ];
    assert_eq!(common::http_get(port, "/api/ping", &headers).await.0, 403);
}
