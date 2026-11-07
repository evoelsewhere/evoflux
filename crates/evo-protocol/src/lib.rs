//! `evo-protocol` — the wire contract between the evo engine and its clients.
//!
//! This crate owns the message types and transports that a front end (the
//! desktop app, the transitional `evo --connect` client, tests) uses to talk to
//! a headless engine, so the contract has a single source of truth and clients
//! do not need to depend on the engine itself.
//!
//! - [`protocol`] — wire types ([`protocol::RemoteEvent`],
//!   [`protocol::RemoteCommand`], [`protocol::RemoteResponse`]).
//! - [`framing`] / [`cbor`] / [`codec`] — the binary transport: 4-byte
//!   length-prefixed frames carrying CBOR-encoded protocol messages. JSONL
//!   stays the default transport.
//! - [`client`] — a TCP JSONL connection to an engine endpoint.
//! - [`mesh`] — the session mesh protocol: envelopes, node addresses and
//!   lifecycle events shared by sessions, subagents and their clients.
//! - [`office`] — Office preview, document versions and the
//!   `office_file_changed` event.
//! - [`message_accumulator`] — folds streamed assistant deltas back into
//!   complete messages on the client side.
//! - [`RpcMessageUpdates`] — how assistant message updates are put on the wire.

pub mod cbor;
pub mod client;
pub mod codec;
pub mod framing;
/// The session mesh wire types (they live in `evo-mesh`, which the desktop
/// shell embeds without the engine crates).
pub use evo_mesh::wire as mesh;
pub mod message_accumulator;
pub mod office;
pub mod protocol;

/// RPC message-update wire representation. Missing capability metadata on older
/// hosts means snapshot semantics, not the engine's default.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RpcMessageUpdates {
    #[default]
    CompactDeltas,
    Snapshot,
}

impl RpcMessageUpdates {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CompactDeltas => "compact-deltas",
            Self::Snapshot => "snapshot",
        }
    }
}
