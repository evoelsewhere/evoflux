//! Port of `health_live` in app/api/routes/health.py.
//!
//! The handler touches no database, lock, file or shared state, so an answer
//! proves the runtime is alive (design §6.3).

use axum::http::{header, StatusCode};
use axum::http::{HeaderMap, HeaderValue, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::{any, on, MethodFilter};
use axum::Router;
use evoflux_core::ApiError;

pub fn router() -> Router {
    // axum answers HEAD from the GET handler unless HEAD is routed explicitly; Python 405s it.
    Router::new()
        .route(
            "/api/health/live",
            on(MethodFilter::GET, health_live)
                .head(method_not_allowed)
                .fallback(method_not_allowed),
        )
        .route("/api/health/live/", any(redirect_to_slashless))
}

/// FastAPI `redirect_slashes`: 307 to the same URL without the slash, keeping the query.
async fn redirect_to_slashless(headers: HeaderMap, uri: Uri) -> Response {
    let mut location = String::from("/api/health/live");
    if let Some(query) = uri.query() {
        location.push('?');
        location.push_str(query);
    }
    if let Some(host) = headers.get(header::HOST).and_then(|h| h.to_str().ok()) {
        location = format!("http://{host}{location}");
    }
    let mut response = StatusCode::TEMPORARY_REDIRECT.into_response();
    if let Ok(value) = HeaderValue::from_str(&location) {
        response.headers_mut().insert(header::LOCATION, value);
    }
    response
}

async fn health_live() -> Response {
    (
        [(header::CONTENT_TYPE, "application/json")],
        concat!(
            r#"{"status":"ok","version":""#,
            env!("CARGO_PKG_VERSION"),
            r#""}"#
        ),
    )
        .into_response()
}

async fn method_not_allowed() -> Response {
    let mut response =
        ApiError::new(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed").into_response();
    response
        .headers_mut()
        .insert(header::ALLOW, HeaderValue::from_static("GET"));
    response
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use axum::body::{to_bytes, Body};
    use axum::http::{Method, Request};
    use tower::ServiceExt;

    async fn call(method: Method, uri: &str) -> Response {
        let request = Request::builder()
            .method(method)
            .uri(uri)
            .header(header::HOST, "127.0.0.1:4082")
            .body(Body::empty())
            .unwrap();
        router().oneshot(request).await.unwrap()
    }

    async fn json(response: Response) -> serde_json::Value {
        let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    #[tokio::test]
    async fn live_answers_status_and_version() {
        let response = call(Method::GET, "/api/health/live").await;
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()[header::CONTENT_TYPE], "application/json");
        let body = json(response).await;
        assert_eq!(body.as_object().map(|o| o.len()), Some(2));
        assert_eq!(body["status"], "ok");
        assert_eq!(body["version"], env!("CARGO_PKG_VERSION"));
    }

    #[tokio::test]
    async fn live_ignores_query_parameters() {
        let response = call(Method::GET, "/api/health/live?x=1&_token=bad").await;
        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn head_gets_python_405_body() {
        let response = call(Method::HEAD, "/api/health/live").await;
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(response.headers()[header::ALLOW], "GET");
    }

    #[tokio::test]
    async fn trailing_slash_redirects_with_307_for_any_method() {
        for method in [Method::GET, Method::HEAD, Method::POST, Method::DELETE] {
            let response = call(method.clone(), "/api/health/live/?a=1").await;
            assert_eq!(
                response.status(),
                StatusCode::TEMPORARY_REDIRECT,
                "{method}"
            );
            assert_eq!(
                response.headers()[header::LOCATION],
                "http://127.0.0.1:4082/api/health/live?a=1",
                "{method}"
            );
        }
    }

    #[tokio::test]
    async fn other_methods_get_python_405_body() {
        let response = call(Method::POST, "/api/health/live").await;
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(response.headers()[header::ALLOW], "GET");
        assert_eq!(
            json(response).await,
            serde_json::json!({"detail": "Method Not Allowed"})
        );
    }
}
