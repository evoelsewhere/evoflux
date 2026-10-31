//! Port of app/api/routes/snippets.py and app/services/snippets.py.

#![forbid(unsafe_code)]
#![allow(clippy::result_large_err)]

mod routes;
mod service;

use std::sync::Arc;

use axum::Router;
pub use evoflux_area_commands::Roots;

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
    async fn router_serves_the_snippet_list() {
        let dir = tempfile::tempdir().unwrap();
        let app = router(Roots {
            config_dir: dir.path().join("config"),
            home: dir.path().join("home"),
        });
        let uri = format!("/api/snippets?workspace={}", dir.path().display());
        let request = Request::builder().uri(uri).body(Body::empty()).unwrap();
        let response = app.oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    }
}
