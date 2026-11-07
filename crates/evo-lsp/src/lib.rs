//! Language servers for evo: a catalog of servers with installers
//! ([`catalog`], [`install`]), which languages a project uses ([`detect`]),
//! a small LSP client ([`client`]), the running servers ([`pool`]) and the
//! operations the agent's `lsp` tool runs ([`ops`]).

pub mod catalog;
pub mod client;
pub mod detect;
pub mod install;
pub mod ops;
pub mod pool;

pub use pool::Pool;
