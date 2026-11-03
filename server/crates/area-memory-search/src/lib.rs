//! Port of app/api/routes/wiki.py, app/api/routes/team/{search_everywhere,app_search}.py
//! and app/services/{wiki,memory,app_search_service,search_everywhere_service}.py.
//! Stub until lane Lb; `contract-tests/memory-search/` describes the behaviour
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
