//! Port of app/api/routes/commands.py: `GET /api/commands` and
//! `POST /api/commands/{name:path}/render`. Transport only.

use std::sync::Arc;

use axum::body::to_bytes;
use axum::extract::Request;
use axum::http::{header::CONTENT_TYPE, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::Router;
use evoflux_api_types::commands::{CommandListResponse, CommandRenderResponse, CommandSummary};
use evoflux_core::ApiError;

use crate::service::{builtin_command, candidate_roots, parse_render_body, render_command};
use crate::support::{
    checked_workspace, discover, dispatch, json_ok, method_not_allowed, not_found, percent_decode,
    query_last, redirect, Dispatch,
};
use crate::Roots;

const PREFIX: &str = "/api/commands";
const BODY_LIMIT: usize = 16 * 1024 * 1024;

pub(crate) fn router(roots: Arc<Roots>) -> Router {
    let handler = move |request: Request| {
        let roots = Arc::clone(&roots);
        async move {
            respond(roots, request)
                .await
                .unwrap_or_else(IntoResponse::into_response)
        }
    };
    Router::new()
        .route(PREFIX, any(handler.clone()))
        .route("/api/commands/", any(handler.clone()))
        .route("/api/commands/{*rest}", any(handler))
}

async fn respond(roots: Arc<Roots>, request: Request) -> Result<Response, ApiError> {
    let (parts, body) = request.into_parts();
    let query = parts.uri.query();
    let decoded = percent_decode(parts.uri.path(), false);
    match dispatch(PREFIX, &decoded, &parts.method) {
        Dispatch::List => list(&roots, query).await,
        Dispatch::Render(name) => {
            let content_type = parts
                .headers
                .get(CONTENT_TYPE)
                .and_then(|value| value.to_str().ok());
            let bytes = to_bytes(body, BODY_LIMIT).await.map_err(|_| {
                ApiError::new(StatusCode::PAYLOAD_TOO_LARGE, "Request body too large.")
            })?;
            // FastAPI validates the body before the handler checks the workspace.
            let arguments = parse_render_body(content_type, &bytes)?;
            render(&roots, &name, &arguments, query).await
        }
        Dispatch::Redirect(path) => Ok(redirect(&parts.headers, &path, query)),
        Dispatch::MethodNotAllowed(allow) => Err(method_not_allowed(allow)),
        Dispatch::NotFound => Err(not_found()),
    }
}

async fn workspace(
    roots: &Roots,
    query: Option<&str>,
) -> Result<Option<std::path::PathBuf>, ApiError> {
    match query_last(query, "workspace") {
        Some(raw) => checked_workspace(raw, roots.home.clone()).await.map(Some),
        None => Ok(None),
    }
}

async fn discovered(
    roots: &Roots,
    workspace: Option<std::path::PathBuf>,
) -> Result<std::collections::BTreeMap<String, crate::support::Entry>, ApiError> {
    let (config_dir, home) = (roots.config_dir.clone(), roots.home.clone());
    evoflux_core::blocking::run(move || {
        discover(&candidate_roots(workspace.as_deref(), &config_dir, &home))
    })
    .await?
}

async fn list(roots: &Roots, query: Option<&str>) -> Result<Response, ApiError> {
    let workspace = workspace(roots, query).await?;
    let commands = discovered(roots, workspace)
        .await?
        .into_values()
        .map(|entry| CommandSummary {
            name: entry.name,
            description: entry.description,
            source: entry.source.to_owned(),
        })
        .collect();
    json_ok(serde_json::to_vec(&CommandListResponse { commands }))
}

async fn render(
    roots: &Roots,
    name: &str,
    arguments: &str,
    query: Option<&str>,
) -> Result<Response, ApiError> {
    let workspace = workspace(roots, query).await?;
    // Disk commands take precedence so a user can shadow a built-in.
    let mut commands = discovered(roots, workspace).await?;
    let command = commands.remove(name).or_else(|| builtin_command(name));
    let Some(command) = command else {
        return Err(ApiError::new(
            StatusCode::NOT_FOUND,
            format!("Command '{name}' not found."),
        ));
    };
    json_ok(serde_json::to_vec(&CommandRenderResponse {
        name: command.name,
        content: render_command(&command.body, arguments),
    }))
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
    use axum::http::{header, Request, StatusCode};
    use serde_json::{json, Value};
    use tower::ServiceExt;

    struct Fixture {
        _dir: tempfile::TempDir,
        base: std::path::PathBuf,
        router: Router,
    }

    fn fixture() -> Fixture {
        let dir = tempfile::tempdir().unwrap();
        let base = crate::support::resolve_workspace(
            &dir.path().to_string_lossy(),
            dir.path(),
            dir.path(),
        );
        let roots = Roots {
            config_dir: base.join("config"),
            home: base.join("home"),
        };
        Fixture {
            router: router(Arc::new(roots)),
            base,
            _dir: dir,
        }
    }

    fn put(base: &std::path::Path, rel: &str, text: &str) {
        let path = base.join(rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }

    async fn call(
        fixture: &Fixture,
        method: &str,
        uri: &str,
        content_type: Option<&str>,
        body: &str,
    ) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
        let mut request = Request::builder()
            .method(method)
            .uri(uri)
            .header(header::HOST, "127.0.0.1:9");
        if let Some(content_type) = content_type {
            request = request.header(header::CONTENT_TYPE, content_type);
        }
        let response = fixture
            .router
            .clone()
            .oneshot(request.body(Body::from(body.to_owned())).unwrap())
            .await
            .unwrap();
        let (parts, body) = response.into_parts();
        let bytes = to_bytes(body, usize::MAX).await.unwrap().to_vec();
        (parts.status, parts.headers, bytes)
    }

    async fn get_json(fixture: &Fixture, uri: &str) -> (StatusCode, Value) {
        let (status, _, body) = call(fixture, "GET", uri, None, "").await;
        (status, serde_json::from_slice(&body).unwrap_or(Value::Null))
    }

    async fn render(fixture: &Fixture, uri: &str, body: &str) -> (StatusCode, Value) {
        let (status, _, bytes) = call(fixture, "POST", uri, Some("application/json"), body).await;
        (
            status,
            serde_json::from_slice(&bytes).unwrap_or(Value::Null),
        )
    }

    #[tokio::test]
    async fn list_is_sorted_with_sources_and_exact_bytes() {
        let f = fixture();
        put(
            &f.base,
            "config/commands/zeta.md",
            "---\ndescription: Z\n---\nz",
        );
        put(&f.base, "config/commands/Beta.md", "b");
        put(&f.base, "home/.config/opencode/commands/oc.md", "o");
        let (status, headers, body) = call(&f, "GET", "/api/commands", None, "").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(headers[header::CONTENT_TYPE], "application/json");
        assert_eq!(
            String::from_utf8(body).unwrap(),
            concat!(
                r#"{"commands":[{"name":"Beta","description":"","source":"global-EvoFlux"},"#,
                r#"{"name":"oc","description":"","source":"global-opencode"},"#,
                r#"{"name":"zeta","description":"Z","source":"global-EvoFlux"}]}"#
            )
        );
    }

    #[tokio::test]
    async fn list_empty_and_builtin_not_listed() {
        let f = fixture();
        let (status, body) = get_json(&f, "/api/commands").await;
        assert_eq!((status, body), (StatusCode::OK, json!({"commands": []})));
    }

    #[tokio::test]
    async fn workspace_roots_only_with_workspace() {
        let f = fixture();
        put(&f.base, "ws/.evoflux/commands/local.md", "x");
        put(&f.base, "ws/.opencode/commands/oc.md", "x");
        put(&f.base, "config/commands/shared.md", "x");
        let (_, without) = get_json(&f, "/api/commands").await;
        assert_eq!(without["commands"].as_array().unwrap().len(), 1);
        let uri = format!("/api/commands?workspace={}", f.base.join("ws").display());
        let (_, with) = get_json(&f, &uri).await;
        let names: Vec<_> = with["commands"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| c["source"].as_str().unwrap().to_owned())
            .collect();
        assert_eq!(
            names,
            ["project-EvoFlux", "project-opencode", "global-EvoFlux"]
        );
    }

    #[tokio::test]
    async fn workspace_errors_are_422_with_the_resolved_path() {
        let f = fixture();
        put(&f.base, "a-file", "x");
        for name in ["gone", "a-file"] {
            let path = f.base.join(name);
            let uri = format!("/api/commands?workspace={}", path.display());
            let (status, body) = get_json(&f, &uri).await;
            assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
            assert_eq!(
                body,
                json!({"detail": format!(
                    "Workspace does not exist or is not a directory: {}",
                    path.display()
                )})
            );
        }
    }

    #[tokio::test]
    async fn render_substitutes_and_resolves_nested_names() {
        let f = fixture();
        put(
            &f.base,
            "config/commands/git/commit.md",
            "Commit: $ARGUMENTS",
        );
        let (status, body) = render(
            &f,
            "/api/commands/git/commit/render",
            r#"{"arguments":"fix"}"#,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            body,
            json!({"name": "git/commit", "content": "Commit: fix"})
        );
        let (_, encoded) = render(&f, "/api/commands/git%2Fcommit/render", "{}").await;
        assert_eq!(encoded["content"], "Commit: ");
    }

    #[tokio::test]
    async fn render_prefers_disk_over_builtin_and_serves_builtin() {
        let f = fixture();
        let (_, builtin) = render(&f, "/api/commands/init/render", "{}").await;
        assert_eq!(builtin["name"], "init");
        assert!(builtin["content"]
            .as_str()
            .unwrap()
            .starts_with("Inspect the project"));
        put(&f.base, "config/commands/init.md", "custom");
        let (_, shadowed) = render(&f, "/api/commands/init/render", "{}").await;
        assert_eq!(shadowed, json!({"name": "init", "content": "custom"}));
    }

    #[tokio::test]
    async fn render_unknown_name_is_404() {
        let f = fixture();
        let (status, body) = render(&f, "/api/commands/has%20space/render", "{}").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body, json!({"detail": "Command 'has space' not found."}));
    }

    #[tokio::test]
    async fn invalid_body_is_reported_before_the_workspace() {
        let f = fixture();
        let uri = format!(
            "/api/commands/init/render?workspace={}",
            f.base.join("gone").display()
        );
        let (status, body) = render(&f, &uri, r#"{"arguments":5}"#).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["detail"][0]["type"], "string_type");
        let (status, body) = render(&f, &uri, "{}").await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert!(body["detail"].is_string());
    }

    #[tokio::test]
    async fn trailing_slash_redirects_with_307_and_the_query() {
        let f = fixture();
        let (status, headers, body) = call(&f, "GET", "/api/commands/?workspace=x", None, "").await;
        assert_eq!(status, StatusCode::TEMPORARY_REDIRECT);
        assert_eq!(
            headers[header::LOCATION],
            "http://127.0.0.1:9/api/commands?workspace=x"
        );
        assert!(body.is_empty());
        let (status, headers, _) = call(
            &f,
            "POST",
            "/api/commands/init/render/",
            Some("application/json"),
            "{}",
        )
        .await;
        assert_eq!(status, StatusCode::TEMPORARY_REDIRECT);
        assert_eq!(
            headers[header::LOCATION],
            "http://127.0.0.1:9/api/commands/init/render"
        );
    }

    #[tokio::test]
    async fn wrong_methods_are_405_with_allow() {
        let f = fixture();
        for (method, uri, allow) in [
            ("POST", "/api/commands", "GET"),
            ("DELETE", "/api/commands", "GET"),
            ("HEAD", "/api/commands", "GET"),
            ("GET", "/api/commands/init/render", "POST"),
        ] {
            let (status, headers, body) = call(&f, method, uri, None, "").await;
            assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED, "{method} {uri}");
            assert_eq!(headers[header::ALLOW], allow);
            if method != "HEAD" {
                assert_eq!(body, br#"{"detail":"Method Not Allowed"}"#);
            }
        }
    }

    #[tokio::test]
    async fn unmatched_paths_are_404_not_found() {
        let f = fixture();
        let (status, body) = get_json(&f, "/api/commands/init").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body, json!({"detail": "Not Found"}));
    }

    #[tokio::test]
    async fn bodies_up_to_sixteen_mebibytes_are_accepted() {
        let f = fixture();
        put(&f.base, "config/commands/echo.md", "$ARGUMENTS");
        let arguments = "a".repeat(2 * 1024 * 1024);
        let body = json!({ "arguments": arguments }).to_string();
        let (status, rendered) = render(&f, "/api/commands/echo/render", &body).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            rendered["content"].as_str().map(str::len),
            Some(arguments.len())
        );
        let too_big = "a".repeat(16 * 1024 * 1024 + 1);
        let (status, _, _) = call(
            &f,
            "POST",
            "/api/commands/echo/render",
            Some("application/json"),
            &too_big,
        )
        .await;
        assert_eq!(status, StatusCode::PAYLOAD_TOO_LARGE);
    }

    #[tokio::test]
    async fn invalid_yaml_is_a_500() {
        let f = fixture();
        put(
            &f.base,
            "config/commands/bad.md",
            "---\na: [unclosed\n---\nbody",
        );
        let (status, _) = get_json(&f, "/api/commands").await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    }
}
