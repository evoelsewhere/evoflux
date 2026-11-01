//! Port of app/api/routes/plugins.py and
//! app/plugin_platform/{marketplaces,installer,registry,review,trust,validator,
//! workspace,credentials,models,builtins}.py.
//! Stub until lane Lb; `contract-tests/plugins-marketplace/` describes the behaviour
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
