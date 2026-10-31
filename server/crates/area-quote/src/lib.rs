//! Port of `GET /api/quote` from app/api/routes/quote.py and
//! app/services/quote_service.py.

#![forbid(unsafe_code)]

mod routes;
mod service;

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;

/// The production router: the real clock, the cache under `cache_dir`, and the
/// API Ninjas client (the shared one from `UnitState`) when `api_key` is set.
pub fn router(cache_dir: PathBuf, api_key: Option<String>, client: evoflux_net::Client) -> Router {
    router_for(cache_dir, api_key, client, service::API_BASE_URL)
}

fn router_for(
    cache_dir: PathBuf,
    api_key: Option<String>,
    client: evoflux_net::Client,
    base_url: &str,
) -> Router {
    routes::router(Arc::new(service::QuoteService::production(
        cache_dir, api_key, client, base_url,
    )))
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
        let response = router(
            dir.path().to_path_buf(),
            None,
            evoflux_net::build_client().unwrap(),
        )
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

    #[tokio::test]
    async fn the_route_fetches_through_the_injected_base_url() {
        let app = axum::Router::new().route(
            "/v2/quoteoftheday",
            axum::routing::get(|| async {
                (
                    [("content-type", "application/json")],
                    r#"[{"quote": "From upstream", "author": "Mock"}]"#,
                )
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base_url = format!("http://{}", listener.local_addr().unwrap());
        tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let dir = tempfile::tempdir().unwrap();
        let request = Request::builder()
            .uri("/api/quote")
            .body(Body::empty())
            .unwrap();
        let response = router_for(
            dir.path().to_path_buf(),
            Some("k".to_owned()),
            evoflux_net::build_client().unwrap(),
            &base_url,
        )
        .oneshot(request)
        .await
        .unwrap();
        let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(
            String::from_utf8(bytes.to_vec()).unwrap(),
            r#"{"quote":"From upstream","author":"Mock"}"#
        );
        assert!(dir.path().join("quoteoftheday.json").is_file());
    }
}
