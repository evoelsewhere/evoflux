//! Port of `GET /api/quote` from app/api/routes/quote.py and
//! app/services/quote_service.py.

#![forbid(unsafe_code)]

mod routes;
mod service;

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;

/// The production router: the real clock, the cache under `cache_dir`, and no
/// API Ninjas client yet (see NOTES.md), so a cache miss answers the fallback.
pub fn router(cache_dir: PathBuf) -> Router {
    routes::router(Arc::new(service::QuoteService::production(cache_dir)))
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::disallowed_methods)]
mod tests {
    use super::*;
    use axum::body::{to_bytes, Body};
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    #[tokio::test]
    async fn production_router_serves_the_quote_route() {
        let dir = tempfile::tempdir().unwrap();
        let request = Request::builder()
            .uri("/api/quote")
            .body(Body::empty())
            .unwrap();
        let response = router(dir.path().to_path_buf())
            .oneshot(request)
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(
            String::from_utf8(bytes.to_vec()).unwrap(),
            r#"{"quote":"First, solve the problem. Then, write the code.","author":"John Johnson"}"#
        );
    }
}
