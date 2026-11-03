//! Transport helpers shared by the unit's routers: FastAPI's 405, its
//! `redirect_slashes` 307 and Starlette's compact JSON responses.

use axum::http::{header, HeaderMap, HeaderValue, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use evoflux_core::ApiError;
use serde_json::Value;

/// `405 {"detail":"Method Not Allowed"}` with the route's `Allow` header.
pub(crate) fn method_not_allowed(allow: &'static str) -> Response {
    let mut response =
        ApiError::new(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed").into_response();
    response
        .headers_mut()
        .insert(header::ALLOW, HeaderValue::from_static(allow));
    response
}

/// FastAPI `redirect_slashes`: 307 to the same URL without the slash, keeping the query.
pub(crate) fn redirect_to_slashless(path: &str, headers: &HeaderMap, uri: &Uri) -> Response {
    let mut location = path.to_owned();
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

pub(crate) fn json_response(body: &Value) -> Result<Response, ApiError> {
    let bytes = serde_json::to_vec(body).map_err(|_| ApiError::internal())?;
    Ok(([(header::CONTENT_TYPE, "application/json")], bytes).into_response())
}
