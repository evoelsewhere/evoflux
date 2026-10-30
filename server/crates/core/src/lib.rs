//! Shared foundation for the EvoFlux Rust server: configuration, paths, the
//! Python-shaped error type, telemetry, desktop authentication, blocking-work
//! helper, the runtime stall watchdog and SQLite access (`db`).

// `ApiError` carries a HeaderMap per the shared interface; boxing it everywhere is noise.
#![allow(clippy::result_large_err)]

pub mod auth;
pub mod blocking;
pub mod config;
pub mod db;
pub mod error;
pub mod paths;
pub mod telemetry;
pub mod watchdog;

pub use error::ApiError;
