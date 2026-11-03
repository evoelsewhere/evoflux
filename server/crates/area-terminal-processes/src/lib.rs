//! Port of app/api/routes/team/{terminal,processes,preview}.py, the two file-watch
//! routes of app/api/routes/team/files.py and
//! app/services/{terminal_service,process_manager,workspace_file_watcher}.py.
//! Stub until lane Lb; `contract-tests/terminal-processes/` describes the behaviour
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
