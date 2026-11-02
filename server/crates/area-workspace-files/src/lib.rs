//! Port of app/api/routes/team/{files,language_servers}.py, the workspace
//! validate/browse/tree routes of app/api/routes/team/chat.py,
//! app/services/{snapshot_service,language_server_service}.py and
//! app/agent/lsp_manager.py.
//! Stub until lane Lb; `contract-tests/workspace-files/` describes the behaviour
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
