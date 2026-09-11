"""OpenAI-compatible provider specs, derived from the provider registry.

The registry in :mod:`app.agent.providers.registry` is the single source of
truth for endpoints and credentials. This module projects the subset that
speaks an OpenAI-shaped wire protocol into the flat spec shape the factory
and the CLI's provider prompts already consume.

A provider qualifies when its transport is Chat Completions or Responses —
i.e. it can be driven by a base URL plus a bearer token. Anthropic, Gemini,
Bedrock, Vertex and Azure providers are excluded because they need their own
handler, not a different URL.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache

from app.agent.providers.registry import (
    PROVIDER_REGISTRY,
    ProviderConfig,
    Transport,
    resolve_base_url,
)

#: Transports that a plain base-URL-plus-key spec can describe.
_OPENAI_SHAPED = frozenset({Transport.OPENAI_COMPLETIONS, Transport.OPENAI_RESPONSES})


@dataclass(frozen=True)
class OpenAICompatibleProviderSpec:
    """Flat view of one OpenAI-compatible provider.

    A projection of :class:`~app.agent.providers.registry.ProviderConfig`,
    kept as its own type because callers (the factory, ``evoflux init``) only
    need these five fields and should not depend on transport internals.
    """

    provider_id: str
    label: str
    env_var: str
    base_url: str
    base_url_env_var: str | None = None
    default_api_key: str = ""


def _spec_from_config(config: ProviderConfig) -> OpenAICompatibleProviderSpec:
    return OpenAICompatibleProviderSpec(
        provider_id=config.id,
        label=config.label,
        env_var=config.env_var,
        base_url=resolve_base_url(config),
        base_url_env_var=config.base_url_env_var,
        default_api_key=config.default_api_key,
    )


def is_openai_compatible(config: ProviderConfig) -> bool:
    """Whether *config* can be reached with a base URL and a bearer token.

    OAuth providers are excluded even when their wire format is OpenAI's:
    they have no ``env_var`` to read a credential from, and their token comes
    from a device flow that a spec cannot express.

    The endpoint is read through :func:`resolve_base_url` rather than off
    ``config.base_url``, because most providers no longer restate a URL that
    models.dev already publishes — reading the field directly would make
    every catalog-backed provider look unreachable.
    """
    if config.transport not in _OPENAI_SHAPED:
        return False
    if config.auth == "oauth":
        return False
    return bool(resolve_base_url(config) and config.env_var)


@lru_cache(maxsize=1)
def _build_compatible_specs() -> dict[str, OpenAICompatibleProviderSpec]:
    return {
        pid: _spec_from_config(config)
        for pid, config in PROVIDER_REGISTRY.items()
        if is_openai_compatible(config)
    }


class _CompatibleSpecs(Mapping[str, OpenAICompatibleProviderSpec]):
    """The spec table, built on first read rather than at import.

    Every entry now resolves its endpoint through the model catalog, and
    reading the catalog can mean fetching it. Building this at import time
    therefore put a blocking network call on the path of merely importing
    the module — including at server startup. Deferring the build to first
    use keeps the mapping interface its callers already rely on while
    letting the process start without waiting on models.dev.
    """

    def __getitem__(self, key: str) -> OpenAICompatibleProviderSpec:
        return _build_compatible_specs()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(_build_compatible_specs())

    def __len__(self) -> int:
        return len(_build_compatible_specs())


OPENAI_COMPATIBLE_PROVIDER_SPECS: Mapping[str, OpenAICompatibleProviderSpec] = (
    _CompatibleSpecs()
)
