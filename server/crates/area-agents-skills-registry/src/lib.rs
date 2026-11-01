//! Port of app/api/routes/agents.py, app/api/routes/skills.py,
//! app/services/{agent_fs,agent_service,skills_service}.py,
//! app/core/{agent_settings,skill_settings}.py and
//! app/agent/skills/{registry,spec,models}.py.
//! Stub until lane Lb; `contract-tests/agents-skills-registry/` describes the behaviour
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
