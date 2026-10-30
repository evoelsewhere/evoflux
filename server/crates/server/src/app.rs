//! The server's HTTP surface: the gateway's own routes, the routing-table
//! proxy, panic isolation, and the auth that Rust-owned routes get.
//!
//! Python stays the auth authority for the routes it serves. Rust-owned
//! routes run behind [`DesktopAuth`], which does not port Python's
//! single-device lock claim for tailnet requests or the WebSocket check, so
//! trusted tailnet requests are refused on Rust routes until those are ported.

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
use evoflux_core::{telemetry, ApiError};
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
/// tailnet refusal as every other Rust route.
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
    let units = rust_routes(units, auth.clone());
    // Layers only wrap routes added before them, so the proxy fallback below
    // stays outside the Rust auth: Python authenticates its own routes.
    let own = rust_routes(
        Router::new()
            .route(GATEWAY_METRICS_PATH, get(gateway_metrics))
            .route(GATEWAY_PING_PATH, get(gateway_ping)),
        auth,
    );
    catch_panics(own.fallback_service(proxy::router_with(table, sup, units, options)))
}

/// Design §6.1 gate 2: a panicking handler answers Python's 500 body and the
/// server keeps serving.
pub fn catch_panics(router: Router) -> Router {
    router.layer(CatchPanicLayer::custom(panic_response))
}

/// Desktop auth, then the tailnet refusal, in front of Rust-owned routes.
pub fn rust_routes(router: Router, auth: DesktopAuth) -> Router {
    router
        .layer(middleware::from_fn(refuse_tailnet))
        .layer(auth.layer())
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

async fn refuse_tailnet(req: Request, next: Next) -> Response {
    if req.extensions().get::<RemoteLogin>().is_some() {
        tracing::warn!(
            path = req.uri().path(),
            "remote_request_refused_on_rust_route"
        );
        return ApiError::new(
            StatusCode::FORBIDDEN,
            "Remote access is not available for this route yet.",
        )
        .with_code("remote_route_unavailable")
        .into_response();
    }
    next.run(req).await
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
