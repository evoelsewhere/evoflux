//! Port of `GET /api/quote` from app/api/routes/quote.py and
//! app/services/quote_service.py.

#![forbid(unsafe_code)]

mod routes;
mod service;

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;

/// The production router: the real clock, the cache under `cache_dir`, and no
/// API Ninjas client yet (see NOTES.md), so a cache miss answers the fallback.
pub fn router(cache_dir: PathBuf) -> Router {
    routes::router(Arc::new(service::QuoteService::production(cache_dir)))
}
