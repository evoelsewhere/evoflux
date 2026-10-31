//! Port of `GET /api/quote` from app/api/routes/quote.py and app/services/quote_service.py.
//!
//! Stub: the routes arrive with lane L2b.

#![forbid(unsafe_code)]

use axum::Router;

pub fn router() -> Router {
    Router::new()
}
