//! Port of app/api/routes/observability.py, app/services/observability_service.py
//! and app/core/otel_retention.py.
//!
//! Python aggregates the span JSONL with DuckDB; this crate reads the same files
//! directly (bounded, see `scan::Limits`) and reproduces each query in Rust.
//! `contract-tests/observability/` describes the behaviour.

#![forbid(unsafe_code)]
#![allow(clippy::result_large_err)]

mod clock;
mod params;
mod retention;
mod routes;
mod scan;
mod summary;
mod traces;

use std::path::Path;
use std::sync::Arc;

use axum::Router;

pub use retention::{
    run_once, spawn_otel_retention, sweep_old_partitions, OtelConfig, SweepResult,
};

/// `GET /api/observability/{summary,traces,traces/{trace_id}}` over
/// `{state_dir}/otel/spans`.
pub fn router(state_dir: &Path, config: OtelConfig) -> Router {
    router_with_limits(state_dir, config, scan::Limits::default())
}

fn router_with_limits(state_dir: &Path, config: OtelConfig, limits: scan::Limits) -> Router {
    routes::router(Arc::new(routes::ObservabilityState {
        spans_dir: state_dir.join("otel").join("spans"),
        config,
        limits,
    }))
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    use axum::body::{to_bytes, Body};
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    #[tokio::test]
    async fn the_public_router_serves_the_three_routes() {
        let dir = tempfile::tempdir().unwrap();
        let app = router(dir.path(), OtelConfig::default());
        for (uri, status) in [
            ("/api/observability/summary", StatusCode::OK),
            ("/api/observability/traces", StatusCode::OK),
            ("/api/observability/traces/0xaa", StatusCode::NOT_FOUND),
            ("/api/observability/elsewhere", StatusCode::NOT_FOUND),
        ] {
            let request = Request::builder().uri(uri).body(Body::empty()).unwrap();
            let response = app.clone().oneshot(request).await.unwrap();
            assert_eq!(response.status(), status, "{uri}");
            let _ = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        }
    }
}
