//! Port of app/api/routes/commands.py and app/services/commands.py.

#![forbid(unsafe_code)]
#![allow(clippy::result_large_err)]

mod builtin;
mod pyjson;
mod routes;
mod service;
pub mod support;

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;

/// The directories discovery reads besides the workspace: `{config_dir}/commands`
/// and `{home}/.config/opencode/commands`.
#[derive(Debug, Clone)]
pub struct Roots {
    pub config_dir: PathBuf,
    pub home: PathBuf,
}

pub fn router(roots: Roots) -> Router {
    routes::router(Arc::new(roots))
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::disallowed_methods)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    #[tokio::test]
    async fn router_serves_the_command_list() {
        let dir = tempfile::tempdir().unwrap();
        let app = router(Roots {
            config_dir: dir.path().join("config"),
            home: dir.path().join("home"),
        });
        let request = Request::builder()
            .uri("/api/commands")
            .body(Body::empty())
            .unwrap();
        let response = app.oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    }
}
