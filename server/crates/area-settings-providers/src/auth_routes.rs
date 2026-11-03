//! Port of app/api/routes/auth.py (`/api/auth`).
//!
//! The OAuth flows themselves (device code and browser login for codex,
//! copilot and xiaomi, provider plugins' login and callback) run Python
//! provider code and are not ported: a known provider's login answers one
//! SSE `failed` event with `reason: "not_ported"`, and every callback is
//! "unsupported" (no provider plugins in Rust). KNOWN_DIFFERENCES.md.

use axum::body::Bytes;
use axum::extract::Path;
use axum::http::{header, HeaderMap, HeaderValue, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::{any, get, post, MethodRouter};
use axum::Router;
use evoflux_core::ApiError;
use serde_json::{json, Value};

use crate::body;
use crate::models::OAUTH_CALLBACK;
use crate::routes::{json_response, method_not_allowed, redirect_to_slashless};

/// `app.cli.commands.auth._PROVIDERS`, sorted as the 404 lists them.
const OAUTH_PROVIDERS: [&str; 3] = ["codex", "copilot", "xiaomi"];

pub(crate) fn router() -> Router {
    Router::new()
        .route("/api/auth/check", only("GET", get(check)))
        .route("/api/auth/check/", any(redirect))
        .route("/api/auth/{provider}/login", only("GET", get(login)))
        .route("/api/auth/{provider}/login/", any(redirect))
        .route(
            "/api/auth/{provider}/callback",
            only("POST", post(callback)),
        )
        .route("/api/auth/{provider}/callback/", any(redirect))
}

/// FastAPI routes answer every other method, HEAD included, with a 405.
fn only(allow: &'static str, route: MethodRouter) -> MethodRouter {
    let route = if allow == "GET" {
        route.head(move || async move { method_not_allowed(allow) })
    } else {
        route
    };
    route.fallback(move || async move { method_not_allowed(allow) })
}

async fn redirect(headers: HeaderMap, uri: Uri) -> Response {
    let path = uri
        .path()
        .strip_suffix('/')
        .unwrap_or(uri.path())
        .to_owned();
    redirect_to_slashless(&path, &headers, &uri)
}

async fn check() -> Result<Response, ApiError> {
    json_response(&json!({"ok": true}))
}

async fn login(Path(provider): Path<String>) -> Response {
    if !OAUTH_PROVIDERS.contains(&provider.as_str()) {
        let known: Vec<String> = OAUTH_PROVIDERS.iter().map(|id| format!("'{id}'")).collect();
        return ApiError::new(
            StatusCode::NOT_FOUND,
            format!(
                "Unknown OAuth provider '{provider}'. Known: [{}].",
                known.join(", ")
            ),
        )
        .into_response();
    }
    let data = json!({
        "message": format!("OAuth login for '{provider}' is not available in the Rust server yet."),
        "reason": "not_ported",
    });
    let frame = format!("event: failed\r\ndata: {data}\r\n\r\n");
    (
        [
            (
                header::CONTENT_TYPE,
                HeaderValue::from_static("text/event-stream; charset=utf-8"),
            ),
            (header::CACHE_CONTROL, HeaderValue::from_static("no-store")),
        ],
        frame,
    )
        .into_response()
}

async fn callback(
    Path(provider): Path<String>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Result<Response, ApiError> {
    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok());
    // Validation precedes the plugin lookup, as in FastAPI.
    body::parse_model(content_type, &bytes, OAUTH_CALLBACK)?;
    Err(ApiError::new(
        StatusCode::NOT_FOUND,
        Value::from(format!("OAuth callback unsupported for '{provider}'")),
    ))
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
mod tests {
    use crate::test_support::call;
    use axum::http::Method;
    use serde_json::json;

    #[tokio::test]
    async fn check_is_get_only() {
        let app = super::router();
        let (status, _, body) = call(&app, Method::GET, "/api/auth/check", None).await;
        assert_eq!((status.as_u16(), body), (200, json!({"ok": true})));
        for method in [
            Method::POST,
            Method::PUT,
            Method::DELETE,
            Method::PATCH,
            Method::HEAD,
        ] {
            let (status, headers, body) = call(&app, method.clone(), "/api/auth/check", None).await;
            assert_eq!(status.as_u16(), 405, "{method}");
            assert_eq!(headers["allow"], "GET");
            if method != Method::HEAD {
                assert_eq!(body, json!({"detail": "Method Not Allowed"}));
            }
        }
        let (status, headers, _) = call(&app, Method::GET, "/api/auth/check/?a=1", None).await;
        assert_eq!(status.as_u16(), 307);
        assert_eq!(headers["location"], "http://test/api/auth/check?a=1");
    }

    #[tokio::test]
    async fn login_lists_the_known_providers_case_sensitively() {
        let app = super::router();
        for id in ["nope", "Codex"] {
            let (status, _, body) =
                call(&app, Method::GET, &format!("/api/auth/{id}/login"), None).await;
            assert_eq!(status.as_u16(), 404);
            assert_eq!(
                body,
                json!({"detail": format!("Unknown OAuth provider '{id}'. Known: ['codex', 'copilot', 'xiaomi'].")})
            );
        }
        let (status, _, _) = call(&app, Method::POST, "/api/auth/codex/login", None).await;
        assert_eq!(status.as_u16(), 405);
    }

    #[tokio::test]
    async fn known_provider_login_is_one_failed_event() {
        let app = super::router();
        for id in ["codex", "copilot", "xiaomi"] {
            let (status, headers, text) = crate::test_support::call_text(
                &app,
                Method::GET,
                &format!("/api/auth/{id}/login?mode=browser"),
                None,
            )
            .await;
            assert_eq!(status.as_u16(), 200);
            assert!(headers["content-type"]
                .to_str()
                .unwrap()
                .starts_with("text/event-stream"));
            let data = text
                .strip_prefix("event: failed\r\ndata: ")
                .and_then(|rest| rest.strip_suffix("\r\n\r\n"))
                .unwrap();
            let data: serde_json::Value = serde_json::from_str(data).unwrap();
            assert_eq!(data["reason"], "not_ported");
            assert!(data["message"].as_str().unwrap().contains(id));
        }
    }

    #[tokio::test]
    async fn callback_validates_before_the_lookup() {
        let app = super::router();
        let ok = Some(("application/json", &br#"{"code":"abc"}"#[..]));
        for id in ["nope", "codex"] {
            let (status, _, body) =
                call(&app, Method::POST, &format!("/api/auth/{id}/callback"), ok).await;
            assert_eq!(status.as_u16(), 404);
            assert_eq!(
                body,
                json!({"detail": format!("OAuth callback unsupported for '{id}'")})
            );
        }
        for bytes in [
            &br#"{}"#[..],
            br#"{"code":"c","x":1}"#,
            br#"{"code":5}"#,
            b"",
        ] {
            let (status, _, body) = call(
                &app,
                Method::POST,
                "/api/auth/nope/callback",
                Some(("application/json", bytes)),
            )
            .await;
            assert_eq!(status.as_u16(), 422, "{body}");
        }
        let (status, _, _) = call(&app, Method::GET, "/api/auth/nope/callback", None).await;
        assert_eq!(status.as_u16(), 405);
    }
}
