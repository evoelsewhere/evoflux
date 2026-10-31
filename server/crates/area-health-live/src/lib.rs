//! Port of `GET /api/health/live` from app/api/routes/health.py (`health_live` only).
//!
//! Stub: the routes arrive with lane L1b.

#![forbid(unsafe_code)]

use axum::Router;

pub fn router() -> Router {
    Router::new()
}
