//! `evo-mesh` — the session mesh (`docs/features/session-mesh-protocol/spec.md`).
//!
//! - [`wire`] — the envelope, node addresses, events, commands and mail that
//!   engines and their clients exchange (re-exported as `evo_protocol::mesh`).
//! - [`hub`] — routes mail between sessions that run in different engines;
//!   the desktop shell embeds it and feeds it every engine's stdout.
//!
//! No engine crates here, so the shell can depend on it cheaply.

pub mod hub;
pub mod wire;

pub use hub::{ChildInfo, CreatedSession, Effect, Hub, Mail, MailStore, MemoryStore, SessionSpec};
