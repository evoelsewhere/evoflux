//! Calling a router in unit tests.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use axum::body::Body;
use axum::http::{HeaderMap, Method, Request, StatusCode};
use axum::Router;
use serde_json::Value;
use tower::ServiceExt;

/// `(status, headers, text)`; `body` is `(content type, bytes)`.
pub(crate) async fn call_text(
    app: &Router,
    method: Method,
    uri: &str,
    body: Option<(&str, &[u8])>,
) -> (StatusCode, HeaderMap, String) {
    let mut request = Request::builder()
        .method(method)
        .uri(uri)
        .header("host", "test");
    let body = match body {
        Some((content_type, bytes)) => {
            request = request.header("content-type", content_type);
            Body::from(bytes.to_vec())
        }
        None => Body::empty(),
    };
    let response = app
        .clone()
        .oneshot(request.body(body).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    (status, headers, String::from_utf8(bytes.to_vec()).unwrap())
}

/// `(status, headers, JSON body or null)`.
pub(crate) async fn call(
    app: &Router,
    method: Method,
    uri: &str,
    body: Option<(&str, &[u8])>,
) -> (StatusCode, HeaderMap, Value) {
    let (status, headers, text) = call_text(app, method, uri, body).await;
    (
        status,
        headers,
        serde_json::from_str(&text).unwrap_or(Value::Null),
    )
}
