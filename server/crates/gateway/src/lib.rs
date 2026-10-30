//! The `evoflux-server` gateway (design §3): the routing table, the Python
//! sidecar supervisor and the HTTP/SSE/WebSocket proxy in front of it.

#![forbid(unsafe_code)]
// `ApiError` carries a HeaderMap per the shared interface; boxing it everywhere is noise.
#![allow(clippy::result_large_err)]

pub mod proxy;
pub mod routing;
pub mod supervisor;
