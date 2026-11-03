//! Port of app/api/routes/settings.py: sandbox, context, version-control,
//! team-spawn, follow-up, background-tasks and response-style transport.

use std::path::PathBuf;

use axum::body::Bytes;
use axum::http::{header, HeaderMap, Method, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::Router;
use evoflux_core::ApiError;

use crate::body;
use crate::models;
use crate::routes::{json_response, method_not_allowed, redirect_to_slashless};
use crate::settings_service;

pub(crate) fn router(config_dir: PathBuf) -> Router {
    let mut router = Router::new();
    for (name, fields) in [
        ("sandbox", models::SANDBOX),
        ("context", models::CONTEXT),
        ("version-control", models::VERSION_CONTROL),
        ("team-spawn", models::TEAM_SPAWN),
        ("follow-up", models::FOLLOW_UP),
        ("background-tasks", models::BACKGROUND_TASKS),
        ("response-style", models::RESPONSE_STYLE),
    ] {
        let path = format!("/api/settings/{name}");
        let dir = config_dir.clone();
        router = router.route(
            &path,
            any(move |method: Method, headers: HeaderMap, bytes: Bytes| {
                let dir = dir.clone();
                async move {
                    let result = match method {
                        Method::GET => settings_service::get(&dir, name).await,
                        Method::PUT => {
                            let content_type = headers
                                .get(header::CONTENT_TYPE)
                                .and_then(|h| h.to_str().ok());
                            match body::parse_model(content_type, &bytes, fields) {
                                Ok(body) => settings_service::put(&dir, name, body).await,
                                Err(error) => return error.into_response(),
                            }
                        }
                        // Starlette matches the GET route first and answers its `Allow: GET`.
                        _ => return method_not_allowed("GET"),
                    };
                    match result {
                        Ok(body) => json_response(&body).unwrap_or_else(ApiError::into_response),
                        Err(response) => response,
                    }
                }
            }),
        );
        router = router.route(
            &format!("{path}/"),
            any(move |headers: HeaderMap, uri: Uri| {
                let path = path.clone();
                async move { redirect_to_slashless(&path, &headers, &uri) }
            }),
        );
    }
    router
}

// Keep the response error type near the transport it models.
pub(crate) type Result<T> = std::result::Result<T, Response>;
