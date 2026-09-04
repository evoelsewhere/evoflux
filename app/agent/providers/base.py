from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.agent.schemas.chat import AssistantMessage, ChatCompletionChunk, ChatMessage


def get_qualified_model_id(provider: object) -> str | None:
    """Return a stable provider:model identity, tolerating extension test doubles."""
    model = getattr(provider, "model", None)
    if not isinstance(model, str) or not model:
        return None
    provider_name = getattr(provider, "provider_name", None)
    if isinstance(provider_name, str) and provider_name:
        return f"{provider_name}:{model}"
    return model


class LLMProviderBase(ABC):
    """Abstract base class for LLM providers.

    Each provider translates between the canonical chat schemas
    (ChatMessage, AssistantMessage, ChatCompletionChunk) and its own
    API format internally. Callers only ever deal with canonical types.

    Known parameters (``temperature``, ``top_p``, ``max_tokens``) are
    explicit, typed constructor arguments — use these for standard
    sampling controls. ``model_kwargs`` accepts provider-specific extras
    (e.g. ``thinking_level``).  Per-call ``**kwargs`` passed to
    ``chat()``/``stream()`` have the highest priority and override
    everything.

    Priority (lowest → highest): named params → model_kwargs → call kwargs.
    """

    model: str

    #: Registry ID this class serves when nothing else says otherwise.
    #:
    #: The factory calls :meth:`bind_provider_name` with the ID the user
    #: actually selected, which is what one class serving two registry
    #: entries needs (``ZAIProvider`` answers for both ``zai`` and
    #: ``zhipuai``). But a provider constructed directly — in a test, or by
    #: a caller that already knows which class it wants — still needs an
    #: identity, because reasoning translation and model metadata are both
    #: keyed by ``provider:model``. Subclasses set this to their own ID.
    default_provider_id: str | None = None

    provider_name: str | None = None

    def __init__(
        self,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ):
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.model_kwargs = model_kwargs or {}
        if self.provider_name is None:
            self.provider_name = type(self).default_provider_id

    def _merged_kwargs(self, **call_kwargs: Any) -> dict[str, Any]:
        """Merge provider-level defaults with per-call overrides.

        Priority (lowest → highest): named params → model_kwargs → call_kwargs.
        """
        base: dict[str, Any] = {}
        if self.temperature is not None:
            base["temperature"] = self.temperature
        if self.top_p is not None:
            base["top_p"] = self.top_p
        if self.max_tokens is not None:
            base["max_tokens"] = self.max_tokens
        return {**base, **self.model_kwargs, **call_kwargs}

    def cache_affinity_kwargs(self, cache_key: str | None) -> dict[str, Any]:
        """Translate one opaque session key to provider-supported call kwargs.

        Providers opt in explicitly so compatible gateways never receive an
        undocumented wire field merely because they share an OpenAI shape.
        """
        return {}

    def bind_provider_name(self, provider_name: str) -> None:
        """Bind the factory provider ID after construction."""
        self.provider_name = provider_name

    def qualified_model_id(self) -> str:
        """Return the pricing/telemetry identity for this provider instance."""
        return get_qualified_model_id(self) or self.model

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AssistantMessage:
        """Call the LLM and return the final AssistantMessage."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Call the LLM and yield ChatCompletionChunk objects as they arrive."""
        ...
