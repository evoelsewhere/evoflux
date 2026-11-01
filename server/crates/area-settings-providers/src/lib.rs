//! Port of app/api/routes/settings.py (minus `/conductor`, `/webbridge` and
//! `/computer-app`, which other units own), app/api/routes/auth.py,
//! app/core/runtime_settings.py and app/agent/sandbox_config.py.
//! Stub until lane Lb; `contract-tests/settings-providers/` describes the behaviour
//! and NOTES.md lists what the port depends on.

#![forbid(unsafe_code)]

use axum::Router;

pub fn router() -> Router {
    Router::new()
}

#[cfg(test)]
mod tests {
    use super::router;

    #[test]
    fn stub_router_has_no_routes() {
        assert!(!router().has_routes());
    }
}
