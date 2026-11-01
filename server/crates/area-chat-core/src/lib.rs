//! Port of the chat-core slice of the agent runtime: `POST /api/team/chat`,
//! `GET /api/team/{session_id}/stream` and `GET /api/team/{session_id}/history`
//! (app/api/routes/team/chat.py), running Work-mode turns on the Rust agent
//! loop with the providers of `evoflux-area-providers` and the read-only tools
//! of `evoflux-area-tools`. Messages, usage and session state go to the same
//! SQLite tables Python reads.

#![forbid(unsafe_code)]
// `ApiError` carries Python's whole error response.
#![allow(clippy::result_large_err)]

mod agent;
#[cfg(test)]
mod flow_tests;
mod pyjson;
mod routes;
mod store;
mod stream_store;
#[cfg(test)]
mod testkit;
mod title;
mod turn;
mod usage;
mod workspace;

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};

use axum::routing::{get, post};
use axum::Router;
use evoflux_core::config::Settings;
use evoflux_core::db::Db;
use tokio_util::sync::CancellationToken;

use crate::stream_store::StreamStore;

/// Shared state of the chat-core routes.
pub struct ChatState {
    settings: Arc<Settings>,
    db: Option<Arc<Db>>,
    store: Arc<StreamStore>,
    /// The shared HTTPS client (`evoflux-net`), for the title request.
    http: evoflux_net::Client,
    /// Turns in flight, by session id, with their interrupt token.
    active: Mutex<HashMap<String, CancellationToken>>,
}

impl ChatState {
    fn active(&self) -> MutexGuard<'_, HashMap<String, CancellationToken>> {
        self.active
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
    }

    /// Reserve the session for a new turn; false when one is running.
    fn begin_turn(&self, session_id: &str) -> bool {
        let mut active = self.active();
        if active.contains_key(session_id) {
            return false;
        }
        active.insert(session_id.to_owned(), CancellationToken::new());
        true
    }

    fn cancel_token(&self, session_id: &str) -> CancellationToken {
        self.active()
            .entry(session_id.to_owned())
            .or_default()
            .clone()
    }

    fn finish_turn(&self, session_id: &str) {
        self.active().remove(session_id);
    }

    /// `interrupt_team`: stop the running turn, if any.
    fn interrupt(&self, session_id: &str) {
        if let Some(token) = self.active().get(session_id) {
            token.cancel();
        }
    }
}

fn new_state(
    settings: Arc<Settings>,
    db: Option<Arc<Db>>,
    http: evoflux_net::Client,
) -> Arc<ChatState> {
    Arc::new(ChatState {
        settings,
        db,
        http,
        store: Arc::new(StreamStore::default()),
        active: Mutex::new(HashMap::new()),
    })
}

fn routes(state: Arc<ChatState>) -> Router {
    Router::new()
        .route("/api/team/chat", post(routes::team_chat))
        .route("/api/team/{session_id}/stream", get(routes::team_stream))
        .route("/api/team/{session_id}/history", get(routes::team_history))
        .with_state(state)
}

/// The chat-core router.
pub fn router(settings: Arc<Settings>, db: Option<Arc<Db>>, http: evoflux_net::Client) -> Router {
    routes(new_state(settings, db, http))
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    fn state() -> ChatState {
        let dir = std::env::temp_dir();
        let settings = Settings::from_vars(&HashMap::new(), Some(&dir), &dir).unwrap();
        ChatState {
            settings: Arc::new(settings),
            db: None,
            http: evoflux_net::build_client().unwrap(),
            store: Arc::new(StreamStore::default()),
            active: Mutex::new(HashMap::new()),
        }
    }

    #[test]
    fn one_turn_per_session_and_interrupt_cancels_it() {
        let state = state();
        assert!(state.begin_turn("s"));
        assert!(!state.begin_turn("s"));
        let token = state.cancel_token("s");
        state.interrupt("other");
        assert!(!token.is_cancelled());
        state.interrupt("s");
        assert!(token.is_cancelled());
        state.finish_turn("s");
        assert!(state.begin_turn("s"));
        assert!(!state.cancel_token("s").is_cancelled());
    }

    async fn call(method: &str, uri: &str, form: &str) -> (u16, String, String) {
        use axum::body::{to_bytes, Body};
        use tower::ServiceExt;
        let dir = std::env::temp_dir();
        let settings = Settings::from_vars(&HashMap::new(), Some(&dir), &dir).unwrap();
        let app = router(
            Arc::new(settings),
            None,
            evoflux_net::build_client().unwrap(),
        );
        let request = axum::http::Request::builder()
            .method(method)
            .uri(uri)
            .header("content-type", "application/x-www-form-urlencoded")
            .body(Body::from(form.to_owned()))
            .unwrap();
        let response = app.oneshot(request).await.unwrap();
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get("content-type")
            .map(|v| v.to_str().unwrap().to_owned())
            .unwrap_or_default();
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        (
            status,
            content_type,
            String::from_utf8(body.to_vec()).unwrap(),
        )
    }

    #[tokio::test]
    async fn routes_answer_like_python() {
        let sid = "06ae6ab0-636d-720e-8000-b0d548016ce8";
        let (status, content_type, body) =
            call("GET", &format!("/api/team/{sid}/stream"), "").await;
        assert_eq!(
            (status, content_type.as_str(), body.as_str()),
            (200, "text/event-stream; charset=utf-8", "")
        );
        let (status, _, body) = call("GET", "/api/team/not-a-uuid/history", "").await;
        assert_eq!(status, 422);
        assert!(body.contains("invalid character: found `n` at 1"), "{body}");
        let (status, _, body) = call("GET", &format!("/api/team/{sid}/history?before=x"), "").await;
        assert_eq!(
            (status, body.as_str()),
            (422, r#"{"detail":"Invalid before cursor: x"}"#)
        );
        let (status, _, _) = call("GET", &format!("/api/team/{sid}/history"), "").await;
        assert_eq!(status, 503);
        let (status, _, body) = call("POST", "/api/team/chat", "").await;
        assert_eq!(
            (status, body.as_str()),
            (
                422,
                r#"{"detail":"Value error, message is required when interrupt=false."}"#
            )
        );
        let (status, _, body) = call("POST", "/api/team/chat", "message=hi&model=nope%3Ax").await;
        assert_eq!(
            (status, body.as_str()),
            (422, r#"{"detail":"Choose a model from the registry."}"#)
        );
        let (status, _, _) = call("POST", "/api/team/chat", "message=hi").await;
        assert_eq!(status, 503);
    }
}
