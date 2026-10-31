//! Port of `GET /api/health/live` from app/api/routes/health.py (`health_live` only).

#![forbid(unsafe_code)]

mod routes;

pub use routes::router;
