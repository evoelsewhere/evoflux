//! Port of app/api/routes/team/{webbridge,browser,computer}.py (every route except
//! `/api/team/webbridge/sessions/**` and `/interactions`), the WebBridge, agent-browsing
//! and computer-app routes of app/api/routes/settings.py and
//! app/services/{webbridge_service,webbridge_pairing_service,webbridge_appearance,
//! direct_browser_bridge,direct_computer_bridge}.py.
//! Stub until lane Lb; `contract-tests/webbridge-browser/` describes the behaviour and
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
