//! Concrete providers. Mirrors `packages/ai/src/api/*` + the in-tree faux
//! provider (`packages/agent/src/faux.ts`, hoisted here so every crate's tests
//! can reuse it without depending on `evo-agent`).
//!
//! Faux is always available. HTTP providers are enabled by the `providers`
//! feature.

pub mod faux;

#[cfg(feature = "providers")]
pub mod anthropic;

#[cfg(feature = "providers")]
pub mod aws_credentials;
#[cfg(feature = "providers")]
pub mod bedrock;

#[cfg(feature = "providers")]
pub mod google;

#[cfg(feature = "providers")]
pub mod openai_completions;

#[cfg(feature = "providers")]
pub mod openai_responses;

#[cfg(feature = "providers")]
mod request;

// ---------------------------------------------------------------------------
// Streaming delta batching (shared policy)
// ---------------------------------------------------------------------------

/// Bytes accumulated before a batched text/thinking delta is emitted.
///
/// Every `AssistantMessageEvent` carries a full `partial: Arc<AssistantMessage>`
/// snapshot, so emitting one event per wire delta made a long stream quadratic
/// in the message length: measured, 8000 one-byte deltas cost ~105ms and the
/// scaling was superlinear. Batching keeps per-event work proportional to the
/// *batch* rather than to the whole message so far.
///
/// Channel boundaries always flush (`TextEnd`, `ThinkingEnd`, `ToolCallEnd`,
/// `Done`/`Error`, and a switch between text and thinking), so this changes only
/// how smoothly text appears — never the final message, and never the
/// concatenation of the deltas a consumer sees.
#[cfg(feature = "providers")]
pub(crate) const DELTA_FLUSH_BYTES: usize = 64;

/// Longest a delta may sit unemitted.
///
/// A pure byte threshold would hide output for `DELTA_FLUSH_BYTES / rate` on a
/// slow stream (a model emitting one character per 100ms would show nothing for
/// six seconds). This bounds that: a slow stream flushes on the timer, a fast
/// one on the byte count. 40ms is under three render frames, so it is
/// imperceptible.
#[cfg(feature = "providers")]
pub(crate) const DELTA_FLUSH_INTERVAL: std::time::Duration = std::time::Duration::from_millis(40);
