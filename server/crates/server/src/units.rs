//! Area routers and services mounted by the production server.
use axum::Router;
use evoflux_core::{config::Settings, db::Db, paths::Paths};
use evoflux_gateway::routing::RoutingTable;
use std::sync::Arc;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
pub struct UnitState {
    pub settings: Arc<Settings>,
    pub paths: Arc<Paths>,
    pub db: Option<Arc<Db>>,
    /// The one shared HTTPS client (`evoflux-net`); units clone it, never build their own.
    pub http: evoflux_net::Client,
}
pub fn router(_state: &UnitState) -> Router {
    #[cfg(test)]
    if _state.settings.app_env == "serve-test-unit" {
        return Router::new().route(
            "/test-unit",
            axum::routing::get(|| async { "test unit response" }),
        );
    }
    Router::new()
        .merge(evoflux_area_health_live::router(crate::handshake::version()))
        .merge(evoflux_area_quote::router(
            _state.settings.cache_dir.clone(),
            _state
                .settings
                .ninja_api_key
                .as_ref()
                .map(|key| key.expose().to_owned()),
            _state.http.clone(),
        ))
        .fallback(not_found)
}

/// FastAPI's 404 for a path inside a Rust-owned unit prefix that no route serves.
async fn not_found() -> evoflux_core::ApiError {
    evoflux_core::ApiError::new(axum::http::StatusCode::NOT_FOUND, "Not Found")
}
pub fn start_rust_services(
    _table: &RoutingTable,
    _state: &UnitState,
    _cancel: CancellationToken,
) -> Vec<JoinHandle<()>> {
    #[cfg(test)]
    if _state.settings.app_env == "serve-test-unit"
        && _table.units().iter().any(|unit| {
            unit.name == "test-unit"
                && unit.owner == evoflux_gateway::routing::Owner::Rust
                && unit.services.iter().any(|name| name == "test-service")
        })
    {
        test_support::mark_started();
        return vec![tokio::spawn(async move {
            _cancel.cancelled().await;
            test_support::mark_stopped();
        })];
    }
    Vec::new()
}

#[cfg(test)]
pub(crate) mod test_support {
    use std::sync::atomic::{AtomicBool, Ordering};
    static STARTED: AtomicBool = AtomicBool::new(false);
    static STOPPED: AtomicBool = AtomicBool::new(false);
    pub fn reset() {
        STARTED.store(false, Ordering::SeqCst);
        STOPPED.store(false, Ordering::SeqCst);
    }
    pub fn mark_started() {
        STARTED.store(true, Ordering::SeqCst);
    }
    pub fn mark_stopped() {
        STOPPED.store(true, Ordering::SeqCst);
    }
    pub fn started() -> bool {
        STARTED.load(Ordering::SeqCst)
    }
    pub fn stopped() -> bool {
        STOPPED.load(Ordering::SeqCst)
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used)]
mod tests {
    use super::*;
    use axum::body::{to_bytes, Body};
    use axum::http::{Request, StatusCode};
    use std::collections::HashMap;
    use tower::ServiceExt;

    async fn get(uri: &str) -> (StatusCode, String) {
        let tmp = tempfile::tempdir().unwrap();
        let mut vars = HashMap::new();
        vars.insert(
            "EVOFLUX_CACHE_DIR".to_owned(),
            tmp.path().to_string_lossy().into_owned(),
        );
        let settings = Settings::from_vars(&vars, Some(tmp.path()), tmp.path()).unwrap();
        let state = UnitState {
            paths: Arc::new(Paths::resolve(&settings)),
            settings: Arc::new(settings),
            db: None,
            http: evoflux_net::build_client().unwrap(),
        };
        let request = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let response = router(&state).oneshot(request).await.unwrap();
        let status = response.status();
        let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        (status, String::from_utf8(bytes.to_vec()).unwrap())
    }

    #[tokio::test]
    async fn serves_health_live() {
        let (status, body) = get("/api/health/live").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            body,
            format!(
                r#"{{"status":"ok","version":"{}"}}"#,
                crate::handshake::version()
            )
        );
    }

    #[tokio::test]
    async fn serves_quote_from_the_configured_cache_dir() {
        let (status, body) = get("/api/quote").await;
        assert_eq!(status, StatusCode::OK);
        assert!(body.contains("John Johnson"), "{body}");
    }

    #[tokio::test]
    async fn unserved_paths_answer_python_404_body() {
        for uri in ["/api/health/live/x", "/api/quote/x"] {
            let (status, body) = get(uri).await;
            assert_eq!(status, StatusCode::NOT_FOUND, "{uri}");
            assert_eq!(body, r#"{"detail":"Not Found"}"#, "{uri}");
        }
    }
}
