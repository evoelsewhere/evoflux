//! The server's HTTP surface: the gateway's own routes, the routing-table
//! proxy, panic isolation, and the auth that Rust-owned routes get.
//!
//! Python stays the auth authority for the routes it serves. Rust-owned
//! routes run behind [`DesktopAuth`] and a remote session claim.
//! Remote WebSocket upgrades are refused until their auth is ported.

use std::any::Any;
use std::sync::Arc;

use axum::extract::Request;
use axum::http::header::CONTENT_TYPE;
use axum::http::StatusCode;
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use evoflux_core::auth::{DesktopAuth, RemoteLogin};
use evoflux_core::{
    db::Db,
    remote_claim::{self, ClaimError},
    telemetry, ApiError,
};
use evoflux_gateway::proxy;
use evoflux_gateway::proxy::GatewayOptions;
use evoflux_gateway::routing::RoutingTable;
use evoflux_gateway::supervisor::PythonSupervisor;
use tower_http::catch_panic::CatchPanicLayer;

/// The gateway's own metrics; `/metrics` stays Python's in Phase 0.
pub const GATEWAY_METRICS_PATH: &str = "/metrics/gateway";

/// An authenticated liveness check of the gateway itself. `/metrics/gateway`
/// is exempt from desktop auth like Python's `/metrics`, so this is the Rust
/// route that proves the token wiring.
pub const GATEWAY_PING_PATH: &str = "/api/gateway/ping";

/// The whole server: `/metrics/gateway`, then the routing table.
pub fn router(table: Arc<RoutingTable>, sup: Arc<PythonSupervisor>, auth: DesktopAuth) -> Router {
    // No unit is Rust-owned yet; cutovers add their routes here.
    router_with_units(table, sup, auth, Router::new())
}

/// [`router`] with the routes of Rust-owned units; they get the same auth and
/// remote claim as every other Rust route.
pub fn router_with_units(
    table: Arc<RoutingTable>,
    sup: Arc<PythonSupervisor>,
    auth: DesktopAuth,
    units: Router,
) -> Router {
    router_with_options(table, sup, auth, units, GatewayOptions::default())
}

pub fn router_with_options(
    table: Arc<RoutingTable>,
    sup: Arc<PythonSupervisor>,
    auth: DesktopAuth,
    units: Router,
    options: GatewayOptions,
) -> Router {
    router_with_options_and_db(table, sup, auth, units, options, None)
}

pub fn router_with_options_and_db(
    table: Arc<RoutingTable>,
    sup: Arc<PythonSupervisor>,
    auth: DesktopAuth,
    units: Router,
    options: GatewayOptions,
    db: Option<Arc<Db>>,
) -> Router {
    let units = rust_routes_with_db(units, auth.clone(), db.clone());
    // Layers only wrap routes added before them, so the proxy fallback below
    // stays outside the Rust auth: Python authenticates its own routes.
    let own = rust_routes_with_db(
        Router::new()
            .route(GATEWAY_METRICS_PATH, get(gateway_metrics))
            .route(GATEWAY_PING_PATH, get(gateway_ping)),
        auth,
        db,
    );
    catch_panics(own.fallback_service(proxy::router_with(table, sup, units, options)))
}

/// Design §6.1 gate 2: a panicking handler answers Python's 500 body and the
/// server keeps serving.
pub fn catch_panics(router: Router) -> Router {
    router.layer(CatchPanicLayer::custom(panic_response))
}

/// Desktop auth and remote claim in front of Rust-owned routes.
pub fn rust_routes(router: Router, auth: DesktopAuth) -> Router {
    rust_routes_with_db(router, auth, None)
}

fn panic_response(panic: Box<dyn Any + Send + 'static>) -> Response {
    let message = panic
        .downcast_ref::<String>()
        .map(String::as_str)
        .or_else(|| panic.downcast_ref::<&str>().copied())
        .unwrap_or("non-string panic payload");
    tracing::error!(panic = message, "handler_panicked");
    ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

async fn gateway_ping() -> &'static str {
    r#"{"status":"ok"}"#
}

async fn gateway_metrics() -> Response {
    (
        [(CONTENT_TYPE, "text/plain; version=0.0.4; charset=utf-8")],
        telemetry::render_prometheus(),
    )
        .into_response()
}

pub fn rust_routes_with_db(router: Router, auth: DesktopAuth, db: Option<Arc<Db>>) -> Router {
    router
        .layer(middleware::from_fn(move |req, next| {
            claim_remote(req, next, db.clone())
        }))
        .layer(auth.layer())
}

async fn claim_remote(req: Request, next: Next, db: Option<Arc<Db>>) -> Response {
    // DesktopAuth runs first and marks trusted tailnet requests.
    let is_remote = req.extensions().get::<RemoteLogin>().is_some();
    if is_remote
        && req
            .headers()
            .get("upgrade")
            .and_then(|v| v.to_str().ok())
            .is_some_and(|v| {
                v.split(',')
                    .any(|part| part.trim().eq_ignore_ascii_case("websocket"))
            })
    {
        return ApiError::new(
            StatusCode::FORBIDDEN,
            "Remote access is not available for this route yet.",
        )
        .with_code("remote_route_unavailable")
        .into_response();
    }
    if matches!(req.uri().path(), "/api/health/live" | "/api/health/ready") {
        return next.run(req).await;
    }
    let Some(login) = req.extensions().get::<RemoteLogin>() else {
        return next.run(req).await;
    };
    let Some(db) = db else {
        return ApiError::internal().into_response();
    };
    let label = req
        .headers()
        .get("x-evoflux-device-label")
        .or_else(|| req.headers().get("user-agent"))
        .map(|v| {
            v.as_bytes()
                .iter()
                .map(|&b| char::from(b))
                .collect::<String>()
        });
    match remote_claim::claim(&db, &login.0, label.as_deref()).await {
        Ok(()) => next.run(req).await,
        Err(ClaimError::Conflict(body)) => (StatusCode::CONFLICT, axum::Json(body)).into_response(),
        Err(ClaimError::Database(e)) => ApiError::from(e).into_response(),
        Err(ClaimError::InvalidLogin) => ApiError::internal().into_response(),
    }
}
