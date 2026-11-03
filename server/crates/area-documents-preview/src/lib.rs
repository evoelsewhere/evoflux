//! Port of app/api/routes/team/{document_versions,motion_review,office_runtime,files}.py
//! and app/services/{document_preview,document_versions,document_text,motion_review_service,office_runtime}.
//! Stub until lane Lb; contract-tests/documents-preview describes the behaviour.

#![forbid(unsafe_code)]

use axum::Router;

pub fn router() -> Router {
    Router::new()
}

#[cfg(test)]
mod tests {
    use super::router;

    #[test]
    fn stub_router_has_no_routes() {
        assert!(!router().has_routes());
    }
}
