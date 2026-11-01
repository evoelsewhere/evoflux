//! Port of app/api/routes/mcp.py and app/agent/mcp/{config,models,oauth,manager,
//! runner,transport}.py.
//! Stub until lane Lb; `contract-tests/mcp-management/` describes the behaviour
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
