//! The placeholder a host runs with before any provider is connected.
//!
//! A desktop host must start, show its UI and let the user connect a provider
//! even when no credential exists yet; refusing to start (the CLI behaviour)
//! would leave nothing to connect *from*. Every request to this provider fails
//! with a message that says what to do, and the host swaps in real provider
//! runtimes once a credential is saved. Mirrors EvoFlux's `unconfigured.py`.

use super::*;
use evo_ai::{Api, AssistantMessage, AssistantMessageEvent, ErrorReason, StopReason};

/// Provider id of the placeholder; never a real provider.
pub const UNCONFIGURED_PROVIDER_ID: &str = "unconfigured";

/// What a request to the placeholder answers with.
pub const UNCONFIGURED_MESSAGE: &str =
    "No model provider is connected. Open Settings → Providers to add an API key, then send your message again.";

fn placeholder_model() -> Model {
    Model::new(
        "none",
        "No provider connected",
        Api::Other(UNCONFIGURED_PROVIDER_ID.into()),
        UNCONFIGURED_PROVIDER_ID,
        "",
    )
}

struct UnconfiguredProvider {
    models: Vec<Model>,
}

#[async_trait::async_trait]
impl Provider for UnconfiguredProvider {
    fn id(&self) -> &str {
        UNCONFIGURED_PROVIDER_ID
    }

    fn models(&self) -> &[Model] {
        &self.models
    }

    async fn stream_simple(
        &self,
        model: &Model,
        _ctx: &Context,
        _opts: &SimpleStreamOptions,
    ) -> AssistantMessageEventStream {
        let (mut producer, stream) = evo_ai::event_stream::create_assistant_message_event_stream();
        let error = AssistantMessage::terminal(
            model.api.clone(),
            UNCONFIGURED_PROVIDER_ID,
            model.id.clone(),
            StopReason::Error,
            UNCONFIGURED_MESSAGE,
            0,
        );
        tokio::spawn(async move {
            producer
                .push(AssistantMessageEvent::Error {
                    reason: ErrorReason::Error,
                    error,
                })
                .await;
        });
        stream
    }
}

/// Whether `model` is the placeholder rather than a real selection.
pub fn is_unconfigured(model: &Model) -> bool {
    model.provider == UNCONFIGURED_PROVIDER_ID
}

impl ResolvedModel {
    /// A runnable resolution with no provider connected. Its catalog is empty,
    /// so model pickers show nothing to choose until a provider is added.
    pub fn unconfigured(theme: Option<String>) -> Self {
        let model = placeholder_model();
        let provider: Arc<dyn Provider> = Arc::new(UnconfiguredProvider {
            models: vec![model.clone()],
        });
        Self {
            provider: provider.clone(),
            model: model.clone(),
            thinking_level: ThinkingLevel::Off,
            has_provider_key: false,
            theme,
            providers: vec![provider],
            compat_warnings: Vec::new(),
            execution: Arc::new(ExecutionBinding::new(
                UNCONFIGURED_PROVIDER_ID,
                vec![model],
                RequestAuth::None,
                None,
            )),
            snapshot_catalog: Vec::new(),
            snapshot_auth: BTreeMap::new(),
        }
    }

    /// Whether this resolution is the no-provider placeholder.
    pub fn is_unconfigured(&self) -> bool {
        is_unconfigured(&self.model)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn requests_fail_with_guidance() {
        let resolved = ResolvedModel::unconfigured(None);
        assert!(resolved.is_unconfigured());
        let ctx = Context::new(Vec::new());
        let stream = resolved
            .provider
            .stream_simple(&resolved.model, &ctx, &SimpleStreamOptions::default())
            .await;
        let message = stream.result().await.unwrap();
        assert_eq!(message.stop_reason, StopReason::Error);
        assert_eq!(message.error_message.as_deref(), Some(UNCONFIGURED_MESSAGE));
    }
}
