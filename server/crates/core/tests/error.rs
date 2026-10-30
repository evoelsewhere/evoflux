#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use axum::body::to_bytes;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use evoflux_core::error::ApiError;

async fn body(err: ApiError) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
    let response = err.into_response();
    let (parts, body) = response.into_parts();
    let bytes = to_bytes(body, usize::MAX).await.unwrap_or_default();
    (parts.status, parts.headers, bytes.to_vec())
}

#[tokio::test]
async fn database_busy_body_exact() {
    let (status, headers, bytes) = body(ApiError::database_busy()).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(
        headers.get("retry-after").map(|v| v.as_bytes()),
        Some(&b"1"[..])
    );
    assert_eq!(
        headers.get("content-type").map(|v| v.as_bytes()),
        Some(&b"application/json"[..])
    );
    // Starlette's JSONResponse renders compact JSON, `detail` before `code`.
    assert_eq!(
        bytes,
        br#"{"detail":"Database is busy. Retry the request in a moment.","code":"database_busy"}"#
    );
    assert_eq!(
        headers.get("content-length").map(|v| v.as_bytes()),
        Some(bytes.len().to_string().as_bytes())
    );
}

#[tokio::test]
async fn backend_unavailable_body_exact() {
    let (status, _, bytes) = body(ApiError::backend_unavailable()).await;
    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert_eq!(
        bytes,
        br#"{"detail":"Backend is restarting.","code":"backend_unavailable"}"#
    );
}

#[tokio::test]
async fn unauthorized_body_is_python_exact_utf8() {
    let (status, _, bytes) = body(ApiError::unauthorized()).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(
        bytes,
        "{\"detail\":\"Unauthorized \u{2014} EvoFlux access key required.\"}".as_bytes()
    );
}

#[tokio::test]
async fn detail_without_code_omits_code_and_keeps_structured_detail() {
    let detail = serde_json::json!([{"loc": ["body"], "msg": "x"}]);
    let (status, _, bytes) = body(ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, detail)).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(bytes, br#"{"detail":[{"loc":["body"],"msg":"x"}]}"#);
}
