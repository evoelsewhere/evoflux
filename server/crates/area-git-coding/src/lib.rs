//! Port of app/api/routes/team/{git,git_ai,worktrees,reviews,projects,change_sets,
//! problems,editor}.py and app/services/{git_ops,git_credentials,git_ai_service,
//! coding_workspace_service,coding_project_service,coding_purge_service,
//! code_review_service,change_set_service,problems_service}.py.
//! Stub until lane Lb; `contract-tests/git-coding/` describes the behaviour
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
