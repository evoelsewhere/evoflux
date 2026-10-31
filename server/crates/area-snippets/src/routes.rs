//! Port of app/api/routes/snippets.py: `GET /api/snippets` and
//! `POST /api/snippets/{name:path}/render`. Transport only.

use std::sync::Arc;

use axum::extract::Request;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::Router;
use evoflux_api_types::snippets::{SnippetListResponse, SnippetRenderResponse, SnippetSummary};
use evoflux_area_commands::support::{
    checked_workspace, discover, dispatch, json_ok, method_not_allowed, not_found, percent_decode,
    query_last, redirect, Dispatch, Entry,
};
use evoflux_area_commands::Roots;
use evoflux_core::ApiError;

use crate::service::candidate_roots;

const PREFIX: &str = "/api/snippets";

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
        .route("/api/snippets/", any(handler.clone()))
        .route("/api/snippets/{*rest}", any(handler))
}

async fn respond(roots: Arc<Roots>, request: Request) -> Result<Response, ApiError> {
    let (parts, _body) = request.into_parts();
    let query = parts.uri.query();
    let decoded = percent_decode(parts.uri.path(), false);
    match dispatch(PREFIX, &decoded, &parts.method) {
        Dispatch::List => list(&roots, query).await,
        Dispatch::Render(name) => render(&roots, &name, query).await,
        Dispatch::Redirect(path) => Ok(redirect(&parts.headers, &path, query)),
        Dispatch::MethodNotAllowed(allow) => Err(method_not_allowed(allow)),
        Dispatch::NotFound => Err(not_found()),
    }
}

/// `_workspace_path`: the parameter is required here, unlike for commands.
async fn discovered(
    roots: &Roots,
    query: Option<&str>,
) -> Result<std::collections::BTreeMap<String, Entry>, ApiError> {
    let Some(raw) = query_last(query, "workspace") else {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Snippet workspace is required.",
        ));
    };
    let workspace = checked_workspace(raw, roots.home.clone()).await?;
    let config_dir = roots.config_dir.clone();
    evoflux_core::blocking::run(move || discover(&candidate_roots(&workspace, &config_dir))).await?
}

async fn list(roots: &Roots, query: Option<&str>) -> Result<Response, ApiError> {
    let snippets = discovered(roots, query)
        .await?
        .into_values()
        .map(|entry| SnippetSummary {
            name: entry.name,
            description: entry.description,
            source: entry.source.to_owned(),
        })
        .collect();
    json_ok(serde_json::to_vec(&SnippetListResponse { snippets }))
}

async fn render(roots: &Roots, name: &str, query: Option<&str>) -> Result<Response, ApiError> {
    let mut snippets = discovered(roots, query).await?;
    let Some(snippet) = snippets.remove(name) else {
        return Err(ApiError::new(
            StatusCode::NOT_FOUND,
            format!("Snippet '{name}' not found."),
        ));
    };
    json_ok(serde_json::to_vec(&SnippetRenderResponse {
        name: snippet.name,
        content: snippet.body,
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
    use evoflux_area_commands::support::resolve_workspace;
    use serde_json::{json, Value};
    use std::path::{Path, PathBuf};
    use tower::ServiceExt;

    struct Fixture {
        _dir: tempfile::TempDir,
        base: PathBuf,
        router: Router,
    }

    fn fixture() -> Fixture {
        let dir = tempfile::tempdir().unwrap();
        let base = resolve_workspace(&dir.path().to_string_lossy(), dir.path(), dir.path());
        let roots = Roots {
            config_dir: base.join("config"),
            home: base.join("home"),
        };
        std::fs::create_dir_all(base.join("ws")).unwrap();
        Fixture {
            router: router(Arc::new(roots)),
            base,
            _dir: dir,
        }
    }

    fn put(base: &Path, rel: &str, text: &str) {
        let path = base.join(rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }

    async fn call(
        fixture: &Fixture,
        method: &str,
        uri: &str,
        body: &str,
    ) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
        let request = Request::builder()
            .method(method)
            .uri(uri)
            .header(header::HOST, "127.0.0.1:9")
            .body(Body::from(body.to_owned()))
            .unwrap();
        let response = fixture.router.clone().oneshot(request).await.unwrap();
        let (parts, body) = response.into_parts();
        let bytes = to_bytes(body, usize::MAX).await.unwrap().to_vec();
        (parts.status, parts.headers, bytes)
    }

    async fn json_call(fixture: &Fixture, method: &str, uri: &str) -> (StatusCode, Value) {
        let (status, _, body) = call(fixture, method, uri, "").await;
        (status, serde_json::from_slice(&body).unwrap_or(Value::Null))
    }

    fn ws_uri(fixture: &Fixture, path: &str) -> String {
        format!("{path}?workspace={}", fixture.base.join("ws").display())
    }

    #[tokio::test]
    async fn list_is_sorted_with_sources_and_exact_bytes() {
        let f = fixture();
        put(
            &f.base,
            "ws/.evoflux/snippets/zeta.md",
            "---\ndescription: Z\n---\nz",
        );
        put(&f.base, "config/snippets/Beta.md", "b");
        let (status, headers, body) = call(&f, "GET", &ws_uri(&f, "/api/snippets"), "").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(headers[header::CONTENT_TYPE], "application/json");
        assert_eq!(
            String::from_utf8(body).unwrap(),
            concat!(
                r#"{"snippets":[{"name":"Beta","description":"","source":"global-EvoFlux"},"#,
                r#"{"name":"zeta","description":"Z","source":"project-EvoFlux"}]}"#
            )
        );
    }

    #[tokio::test]
    async fn project_snippet_wins_over_global_and_other_roots_are_ignored() {
        let f = fixture();
        put(&f.base, "ws/.evoflux/snippets/a.md", "project");
        put(&f.base, "config/snippets/a.md", "global");
        put(&f.base, "ws/.evoflux/commands/cmd.md", "x");
        put(&f.base, "ws/.opencode/snippets/other.md", "x");
        let (_, list) = json_call(&f, "GET", &ws_uri(&f, "/api/snippets")).await;
        assert_eq!(
            list,
            json!({"snippets": [{"name": "a", "description": "", "source": "project-EvoFlux"}]})
        );
        let (_, rendered) = json_call(&f, "POST", &ws_uri(&f, "/api/snippets/a/render")).await;
        assert_eq!(rendered, json!({"name": "a", "content": "project"}));
    }

    #[tokio::test]
    async fn workspace_is_required_for_both_routes() {
        let f = fixture();
        for (method, uri) in [("GET", "/api/snippets"), ("POST", "/api/snippets/x/render")] {
            let (status, body) = json_call(&f, method, uri).await;
            assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
            assert_eq!(body, json!({"detail": "Snippet workspace is required."}));
        }
    }

    #[tokio::test]
    async fn workspace_errors_are_422_with_the_resolved_path() {
        let f = fixture();
        put(&f.base, "a-file", "x");
        for (method, route) in [("GET", "/api/snippets"), ("POST", "/api/snippets/x/render")] {
            for name in ["gone", "a-file"] {
                let path = f.base.join(name);
                let uri = format!("{route}?workspace={}", path.display());
                let (status, body) = json_call(&f, method, &uri).await;
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
    }

    #[tokio::test]
    async fn render_returns_the_body_without_substitution_and_ignores_the_request_body() {
        let f = fixture();
        put(
            &f.base,
            "config/snippets/git/commit.md",
            "---\ndescription: d\n---\nUse $ARGUMENTS",
        );
        let uri = ws_uri(&f, "/api/snippets/git/commit/render");
        let (status, _, body) = call(&f, "POST", &uri, "{not json").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            String::from_utf8(body).unwrap(),
            r#"{"name":"git/commit","content":"Use $ARGUMENTS"}"#
        );
    }

    #[tokio::test]
    async fn render_unknown_snippet_is_404_and_builtin_init_is_not_a_snippet() {
        let f = fixture();
        for name in ["has%20space", "init"] {
            let uri = ws_uri(&f, &format!("/api/snippets/{name}/render"));
            let (status, body) = json_call(&f, "POST", &uri).await;
            assert_eq!(status, StatusCode::NOT_FOUND);
            let shown = name.replace("%20", " ");
            assert_eq!(
                body,
                json!({"detail": format!("Snippet '{shown}' not found.")})
            );
        }
    }

    #[tokio::test]
    async fn trailing_slash_redirects_with_307_and_the_query() {
        let f = fixture();
        for (method, uri, location) in [
            (
                "GET",
                "/api/snippets/?workspace=x",
                "/api/snippets?workspace=x",
            ),
            ("POST", "/api/snippets/x/render/", "/api/snippets/x/render"),
        ] {
            let (status, headers, body) = call(&f, method, uri, "").await;
            assert_eq!(status, StatusCode::TEMPORARY_REDIRECT);
            assert_eq!(
                headers[header::LOCATION],
                format!("http://127.0.0.1:9{location}")
            );
            assert!(body.is_empty());
        }
    }

    #[tokio::test]
    async fn wrong_methods_are_405_with_allow_and_unmatched_paths_404() {
        let f = fixture();
        for (method, uri, allow) in [
            ("POST", "/api/snippets", "GET"),
            ("HEAD", "/api/snippets", "GET"),
            ("GET", "/api/snippets/x/render", "POST"),
        ] {
            let (status, headers, _) = call(&f, method, uri, "").await;
            assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED, "{method} {uri}");
            assert_eq!(headers[header::ALLOW], allow);
        }
        let (status, body) = json_call(&f, "GET", "/api/snippets/x").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body, json!({"detail": "Not Found"}));
    }

    #[tokio::test]
    async fn invalid_yaml_is_a_500() {
        let f = fixture();
        put(
            &f.base,
            "config/snippets/bad.md",
            "---\na: [unclosed\n---\nbody",
        );
        let (status, _) = json_call(&f, "GET", &ws_uri(&f, "/api/snippets")).await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    }
}
