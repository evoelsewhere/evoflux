//! Shared foundation for the EvoFlux Rust server: configuration, paths, the
//! Python-shaped error type, telemetry, desktop authentication, blocking-work
//! helper and the runtime stall watchdog.

// `ApiError` carries a HeaderMap per the shared interface; boxing it everywhere is noise.
#![allow(clippy::result_large_err)]

pub mod auth;
pub mod blocking;
pub mod config;
pub mod error;
pub mod paths;
pub mod telemetry;
pub mod watchdog;

pub use error::ApiError;
