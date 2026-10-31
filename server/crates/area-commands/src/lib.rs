//! Port of app/api/routes/commands.py and app/services/commands.py.
//! Stub until lane L3b; `contract-tests/commands/` describes the behaviour.

#![forbid(unsafe_code)]

use axum::Router;

pub fn router() -> Router {
    Router::new()
}
