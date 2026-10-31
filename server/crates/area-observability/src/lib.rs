//! Port of app/api/routes/observability.py, app/services/observability_service.py
//! and app/core/otel_retention.py.
//! Stub until lane L5b; `contract-tests/observability/` describes the behaviour.

#![forbid(unsafe_code)]

use axum::Router;

pub fn router() -> Router {
    Router::new()
}
