//! The `evoflux-server` product binary (Phase 0 Task 11): the gateway in front
//! of the Python sidecar, started with the same `serve` flags and desktop
//! handshake as `app/cli/commands/serve.py`.

#![forbid(unsafe_code)]
// `ApiError` carries a HeaderMap per the shared interface; boxing it everywhere is noise.
#![allow(clippy::result_large_err)]

pub mod access_key;
pub mod app;
pub mod cli;
pub mod handshake;
pub mod parent;
pub mod serve;
