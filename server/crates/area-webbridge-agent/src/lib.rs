//! Port of the `/api/team/webbridge/sessions/**` and `/api/team/webbridge/interactions`
//! routes of app/api/routes/team/webbridge.py and the services they call
//! (app/services/{interactive_message_service,chat_service,webbridge_artifact_service}.py).
//! Stub until lane Lb; `contract-tests/webbridge-agent/` describes the behaviour and
//! NOTES.md lists what the port depends on.

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
