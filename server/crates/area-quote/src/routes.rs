//! Port of app/api/routes/quote.py.

use std::sync::Arc;

use axum::extract::State;
use axum::http::{header, HeaderMap, HeaderValue, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::{any, on, MethodFilter};
use axum::Router;
use evoflux_core::ApiError;

use crate::service::QuoteService;

pub(crate) fn router(service: Arc<QuoteService>) -> Router {
    Router::new()
        // axum answers HEAD from the GET handler unless HEAD is routed explicitly; Python 405s it.
        .route(
            "/api/quote",
            on(MethodFilter::GET, quote)
                .head(method_not_allowed)
                .fallback(method_not_allowed),
        )
        .route("/api/quote/", any(redirect_to_slashless))
        .with_state(service)
}

async fn quote(State(service): State<Arc<QuoteService>>) -> Response {
    let quote = service.get_quote_of_the_day().await;
    (
        [(header::CONTENT_TYPE, "application/json")],
        quote.to_json(),
    )
        .into_response()
}

/// FastAPI `redirect_slashes`: 307 to the same URL without the slash, keeping the query.
async fn redirect_to_slashless(headers: HeaderMap, uri: Uri) -> Response {
    let mut location = String::from("/api/quote");
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

async fn method_not_allowed() -> Response {
    let mut response =
        ApiError::new(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed").into_response();
    response
        .headers_mut()
        .insert(header::ALLOW, HeaderValue::from_static("GET"));
    response
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::disallowed_methods)]
mod tests {
    use super::*;
    use crate::service::testing::{service_at, FALLBACK_JSON};
    use axum::body::{to_bytes, Body};
    use axum::http::{Method, Request};
    use tower::ServiceExt;

    async fn call(method: Method, uri: &str, dir: &std::path::Path) -> Response {
        let request = Request::builder()
            .method(method)
            .uri(uri)
            .header(header::HOST, "127.0.0.1:4082")
            .body(Body::empty())
            .unwrap();
        router(service_at(dir)).oneshot(request).await.unwrap()
    }

    async fn text(response: Response) -> String {
        let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        String::from_utf8(bytes.to_vec()).unwrap()
    }

    #[tokio::test]
    async fn get_answers_the_fallback_without_a_cache() {
        let dir = tempfile::tempdir().unwrap();
        let response = call(Method::GET, "/api/quote?date=1999-01-01", dir.path()).await;
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()[header::CONTENT_TYPE], "application/json");
        assert_eq!(text(response).await, FALLBACK_JSON);
    }

    #[tokio::test]
    async fn other_methods_get_python_405_body() {
        let dir = tempfile::tempdir().unwrap();
        let response = call(Method::DELETE, "/api/quote", dir.path()).await;
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(response.headers()[header::ALLOW], "GET");
        assert_eq!(text(response).await, r#"{"detail":"Method Not Allowed"}"#);
    }

    #[tokio::test]
    async fn head_gets_python_405_body() {
        let dir = tempfile::tempdir().unwrap();
        let response = call(Method::HEAD, "/api/quote", dir.path()).await;
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(response.headers()[header::ALLOW], "GET");
    }

    #[tokio::test]
    async fn trailing_slash_redirects_every_method_with_307() {
        let dir = tempfile::tempdir().unwrap();
        for method in [Method::GET, Method::HEAD, Method::POST, Method::DELETE] {
            let response = call(method.clone(), "/api/quote/", dir.path()).await;
            assert_eq!(
                response.status(),
                StatusCode::TEMPORARY_REDIRECT,
                "{method}"
            );
            assert_eq!(
                response.headers()[header::LOCATION],
                "http://127.0.0.1:4082/api/quote",
                "{method}"
            );
        }
    }

    #[tokio::test]
    async fn trailing_slash_redirects_with_307_keeping_the_query() {
        let dir = tempfile::tempdir().unwrap();
        let response = call(Method::GET, "/api/quote/?a=1", dir.path()).await;
        assert_eq!(response.status(), StatusCode::TEMPORARY_REDIRECT);
        assert_eq!(
            response.headers()[header::LOCATION],
            "http://127.0.0.1:4082/api/quote?a=1"
        );
    }
}
