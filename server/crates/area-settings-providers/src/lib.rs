//! Port of app/api/routes/settings.py (minus `/conductor`, `/webbridge` and
//! `/computer-app`, which other units own), app/api/routes/auth.py,
//! app/core/runtime_settings.py and app/agent/sandbox_config.py.
//! Ported so far: `/api/auth/**` (OAuth flows excepted, see `auth_routes`).
//! `contract-tests/settings-providers/` describes the behaviour and NOTES.md
//! lists what the rest of the port depends on.

#![forbid(unsafe_code)]
#![allow(clippy::result_large_err)]

mod auth_routes;
mod body;
mod models;
mod pyjson;
mod routes;
mod sandbox;
mod sections;
#[cfg(test)]
mod sections_tests;
mod settings_service;
#[cfg(test)]
mod test_support;

use axum::Router;
use std::path::PathBuf;

pub fn router(config_dir: PathBuf) -> Router {
    Router::new()
        .merge(auth_routes::router())
        .merge(sections::router(config_dir))
}

#[cfg(test)]
mod tests {
    use super::router;

    #[test]
    fn router_serves_the_auth_routes() {
        assert!(router(std::env::temp_dir()).has_routes());
    }
}
