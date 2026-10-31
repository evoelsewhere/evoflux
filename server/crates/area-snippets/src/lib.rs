//! Port of app/api/routes/snippets.py and app/services/snippets.py.
//! Stub until lane L4b; `contract-tests/snippets/` describes the behaviour.

#![forbid(unsafe_code)]

use axum::Router;

pub fn router() -> Router {
    Router::new()
}
