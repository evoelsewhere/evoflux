//! Port of the OpenAI-compatible model providers in `app/agent/providers/`:
//! Chat Completions with streaming for 9Router, Xiaomi MiMo and the providers
//! built on `openai/compatible` (see [`factory::PROVIDERS`]).
//!
//! [`provider_for`] resolves a `provider:model` string against the settings
//! (`*_API_KEY`, `*_BASE_URL`, environment over `.env`), as `build_provider`
//! does. [`Provider::stream`] makes one call and yields text and reasoning
//! deltas and usage as they arrive, then the assembled tool calls and
//! [`ProviderEvent::Done`]. Retries, backoff, fallback and the typed provider
//! errors live in [`retry`], as they live in the agent loop in Python.

#![forbid(unsafe_code)]

mod client;
mod error;
pub mod factory;
mod request;
pub mod retry;
mod stream;
pub mod thinking;
mod types;

use std::sync::Arc;
use std::time::SystemTime;

use async_trait::async_trait;
use futures_core::stream::BoxStream;

pub use client::{CompatibleProvider, STREAM_TIMEOUT};
pub use error::ProviderError;
pub use types::{ContentBlock, FunctionCall, FunctionSpec, Message, ToolCall, ToolSpec, Usage};

/// One model call.
#[derive(Debug, Clone, PartialEq)]
pub struct ChatRequest {
    /// The model, as `provider:model` or the provider's own model ID; empty
    /// means the model [`provider_for`] resolved.
    pub model: String,
    pub messages: Vec<Message>,
    pub tools: Vec<ToolSpec>,
    /// Call options (`temperature`, `top_p`, `max_tokens`, `thinking_level`,
    /// `prompt_cache_key`, `service_tier`): an object, or `null` for none.
    pub options: serde_json::Value,
}

/// What a streaming call yields.
#[derive(Debug, Clone, PartialEq)]
pub enum ProviderEvent {
    TextDelta(String),
    ReasoningDelta(String),
    /// A complete tool call, assembled from the streamed deltas. Empty
    /// arguments arrive as `{}`.
    ToolCall {
        id: String,
        name: String,
        arguments: serde_json::Value,
    },
    Usage(Usage),
    /// The end of a completed stream; `finish_reason` is the last one the
    /// provider sent, or empty when it sent none.
    Done {
        finish_reason: String,
    },
}

/// A model provider.
#[async_trait]
pub trait Provider: Send + Sync {
    async fn stream(
        &self,
        req: ChatRequest,
    ) -> Result<BoxStream<'static, Result<ProviderEvent, ProviderError>>, ProviderError>;
}

/// The provider for a `provider:model` string, like Python's `build_provider`.
pub fn provider_for(
    settings: &evoflux_core::config::Settings,
    model: &str,
) -> Result<Arc<dyn Provider>, ProviderError> {
    let resolved = factory::resolve(settings, model, SystemTime::now())?;
    let client = evoflux_net::build_client_with(evoflux_net::Timeouts {
        connect: STREAM_TIMEOUT,
        read: STREAM_TIMEOUT,
    })
    .map_err(|e| ProviderError::Client(e.to_string()))?;
    Ok(Arc::new(CompatibleProvider::new(client, resolved)))
}
