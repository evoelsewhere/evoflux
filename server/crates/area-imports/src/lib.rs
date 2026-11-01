//! Port of app/api/routes/import_route.py, app/services/import_service.py and
//! app/services/importers/**.
//! Stub until lane L6b; `contract-tests/imports/` describes the behaviour and
//! NOTES.md lists what blocks the port.

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
