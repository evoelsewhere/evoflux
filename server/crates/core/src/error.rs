//! Python-shaped API errors.
//!
//! Port of `app/core/exception_handlers.py`. Starlette's `JSONResponse` writes
//! compact JSON (no spaces, non-ASCII kept as UTF-8) and FastAPI puts `detail`
//! first, then `code`; this type reproduces those bytes.

use axum::http::header::{CONTENT_LENGTH, CONTENT_TYPE, RETRY_AFTER};
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use serde_json::Value;

#[derive(Debug, Clone)]
pub struct ApiError {
    pub status: StatusCode,
    pub detail: Value,
    pub code: Option<&'static str>,
    pub headers: HeaderMap,
}

impl ApiError {
    pub fn new(status: StatusCode, detail: impl Into<Value>) -> Self {
        Self {
            status,
            detail: detail.into(),
            code: None,
            headers: HeaderMap::new(),
        }
    }

    pub fn with_code(mut self, code: &'static str) -> Self {
        self.code = Some(code);
        self
    }

    /// `_database_busy`: 503, `Retry-After: 1`.
    pub fn database_busy() -> Self {
        let mut err = Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "Database is busy. Retry the request in a moment.",
        )
        .with_code("database_busy");
        err.headers
            .insert(RETRY_AFTER, HeaderValue::from_static("1"));
        err
    }

    /// The gateway's answer while the Python child is down or restarting.
    pub fn backend_unavailable() -> Self {
        Self::new(StatusCode::BAD_GATEWAY, "Backend is restarting.")
            .with_code("backend_unavailable")
    }

    /// `DesktopTokenMiddleware` rejection of a missing or wrong token.
    pub fn unauthorized() -> Self {
        Self::new(
            StatusCode::UNAUTHORIZED,
            "Unauthorized \u{2014} EvoFlux access key required.",
        )
    }

    /// `DesktopTokenMiddleware` rejection of an untrusted tailnet identity.
    pub fn untrusted_tailnet_identity() -> Self {
        Self::new(StatusCode::UNAUTHORIZED, "Untrusted tailnet identity.")
    }

    /// Python's catch-all domain error (`_EVOFLUX_fallback`).
    pub fn internal() -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, "Internal server error.")
    }

    /// The exact response bytes: `{"detail":…[,"code":"…"]}`.
    pub fn body_bytes(&self) -> Vec<u8> {
        let mut body = b"{\"detail\":".to_vec();
        match serde_json::to_vec(&self.detail) {
            Ok(detail) => body.extend_from_slice(&detail),
            Err(_) => body.extend_from_slice(b"null"),
        }
        if let Some(code) = self.code {
            body.extend_from_slice(b",\"code\":");
            match serde_json::to_vec(code) {
                Ok(code) => body.extend_from_slice(&code),
                Err(_) => body.extend_from_slice(b"null"),
            }
        }
        body.push(b'}');
        body
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} {}", self.status.as_u16(), self.detail)
    }
}

impl std::error::Error for ApiError {}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = self.body_bytes();
        let mut response = Response::new(axum::body::Body::from(body.clone()));
        *response.status_mut() = self.status;
        let headers = response.headers_mut();
        for (name, value) in &self.headers {
            headers.insert(name.clone(), value.clone());
        }
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        headers.insert(CONTENT_LENGTH, HeaderValue::from(body.len()));
        response
    }
}
