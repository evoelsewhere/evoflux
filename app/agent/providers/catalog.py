"""The provider catalog the settings UI renders.

This module used to restate every provider: its label, credential variable,
documentation link and connection kind, alongside
:mod:`app.agent.providers.registry`, which states the same facts to open a
connection with, alongside models.dev, which publishes them upstream. Three
copies of one truth, two of them destined to drift.

Now there is one copy of each fact and this module derives its rows:

- **Connection facts** — label, credential variable, endpoint, docs link,
  auth mode, catalog ID — come from
  :data:`app.agent.providers.registry.PROVIDER_REGISTRY`, which is what
  actually opens the connection.
- **Catalog facts** — display name, credential variable names, endpoint,
  model documentation, logo — come from models.dev.
- **Everything a machine cannot know** stays in :data:`_OVERRIDES`: the
  one-line description a human wrote, the multi-field credential forms for
  cloud providers, curated fallback model lists, OAuth commands, and
  metadata aliases.

Rows come in three tiers, in the order of how much EvoFlux knows about each:
curated providers, installed plugins, then every remaining provider in the
models.dev catalog — reachable from a base URL and a key, with no code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal, TypedDict

from app.agent.providers.plugin_api import credential_map

ProviderKind = Literal["api_key", "oauth", "local", "cloud_creds"]


class ProviderEntry(TypedDict, total=False):
    """One provider's metadata.

    ``kind`` decides how the UI collects credentials:

    - ``api_key`` — single text input for ``env_var``.
    - ``oauth`` — browser/device flow handled by
      :mod:`app.cli.commands.auth`. Surfaces a "Connect" button.
    - ``local`` — no credentials needed (e.g. Ollama daemon on
      127.0.0.1). UI shows a connection status instead of inputs.
    - ``cloud_creds`` — needs more than one field (e.g. Vertex AI:
      project + location + gcloud auth). UI renders the field list
      from ``env_vars``.

    ``fallback_models`` is a curated list shown when live discovery is
    incomplete for supported model families (Vertex AI, plus Google
    image/video models that are not reliably returned by the public
    model-listing endpoint). See
    ``documents/features/models-and-providers.md`` for the current contract.
    """

    id: str
    label: str
    description: str
    kind: ProviderKind
    env_var: str  # primary env var for api_key providers
    env_vars: list[str]  # multi-field providers (vertexai)
    credentials: list[dict[str, object]]
    fallback_models: list[str]  # only set for providers without live discovery
    oauth_command: str  # CLI fallback hint for oauth providers
    docs_url: str  # link to provider's API key dashboard
    models_dev_provider_id: str  # provider id used by models.dev when different
    metadata_source_provider: str  # source provider for same-model-id metadata aliases
    metadata_source_exclude: list[str]  # fields not shared with the source provider
    model_registry_aliases: dict[str, str]  # target model -> source provider:model
    live_model_metadata: bool  # discovery also returns per-model capabilities
    auto_connect: bool  # whether catalog/registry loads may contact the provider
    source: str  # "builtin" | "plugin" | "catalog" — how much EvoFlux knows
    transport: str  # wire protocol, for catalog-derived rows


#: How a provider's auth mode maps to the credential form the UI renders.
_AUTH_KINDS: dict[str, ProviderKind] = {
    "api_key": "api_key",
    "oauth": "oauth",
    "local": "local",
    "cloud": "cloud_creds",
}


#: Everything about a curated provider that neither the registry nor
#: models.dev can state: the one-line description a person wrote, the
#: multi-field credential forms cloud providers need, curated fallback model
#: lists, OAuth commands, and metadata aliases. A key appearing here does not
#: replace the derived row — it patches it.
_OVERRIDES: dict[str, ProviderEntry] = {
    "anthropic": {
        "description": "Claude API via Anthropic Messages.",
        "fallback_models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
    },
    "bedrock": {
        "credentials": [
            {
                "label": "AWS Bedrock Region",
                "name": "AWS_BEDROCK_REGION",
                "placeholder": "us-east-1",
                "required": False,
                "secret": False,
            },
            {
                "label": "AWS Profile",
                "name": "AWS_BEDROCK_PROFILE",
                "placeholder": "default",
                "required": False,
                "secret": False,
            },
            {
                "label": "AWS Access Key ID",
                "name": "AWS_ACCESS_KEY_ID",
                "placeholder": "AKIA...",
                "required": False,
                "secret": False,
            },
            {
                "label": "AWS Secret Access Key",
                "name": "AWS_SECRET_ACCESS_KEY",
                "placeholder": "••••••••",
                "required": False,
                "secret": True,
            },
        ],
        "description": "AWS Bedrock using an AWS profile or access "
        "keys. Region defaults to us-east-1.",
        "fallback_models": [
            "bedrock:anthropic.claude-sonnet-4-6",
            "bedrock:amazon.nova-pro-v1:0",
            "bedrock:amazon.nova-lite-v1:0",
        ],
    },
    "cerebras": {"description": "Cerebras Inference — ultra-fast Llama inference."},
    "cliproxy": {
        "description": "Local proxy for Gemini CLI / Codex / Claude Code OAuth.",
        "kind": "api_key",
    },
    "codex": {
        "description": "Use your ChatGPT subscription via Codex OAuth.",
        "live_model_metadata": True,
        "metadata_source_exclude": ["thinking"],
        "metadata_source_provider": "openai",
        "oauth_command": "evoflux auth codex",
    },
    "cohere": {"description": "Cohere's Command A and Embed models."},
    "copilot": {
        "description": "Use your Copilot subscription — OAuth, no API key.",
        "oauth_command": "evoflux auth copilot",
    },
    "deepseek": {"description": "DeepSeek's direct API."},
    "fci": {
        "description": "FPT's OpenAI-compatible inference gateway — Qwen, "
        "GLM, Gemma, gpt-oss, DeepSeek, and Llama models."
    },
    "fireworks": {"description": "Fireworks AI — fast inference for open models."},
    "foundry": {
        "credentials": [
            {
                "label": "Resource name or endpoint URL",
                "name": "FOUNDRY_RESOURCE_NAME",
                "placeholder": "my-resource or "
                "https://my-resource.services.ai.azure.com",
                "required": True,
                "secret": False,
            },
            {
                "label": "API key",
                "name": "FOUNDRY_API_KEY",
                "placeholder": "••••••••",
                "required": True,
                "secret": True,
            },
        ],
        "description": "Azure AI Foundry — OpenAI, DeepSeek, Grok, "
        "Claude and more on your Azure resource.",
    },
    "googlegenai": {
        "description": "Google AI Studio — free tier available.",
        "fallback_models": [
            "gemini-3.1-flash-image-preview",
            "gemini-2.5-flash-image-preview",
            "veo-3.1-generate-preview",
            "veo-3.1-fast-generate-preview",
        ],
    },
    "groq": {
        "description": "Groq's ultra-fast inference — Llama, Mixtral, Gemma, etc."
    },
    "kimi": {
        "description": "Kimi's subscription coding API — K3 and K2.7 Code "
        "with tool use and vision."
    },
    "minimax": {"description": "MiniMax M2 models — long context, multilingual."},
    "mistral": {
        "description": "Mistral's La Plateforme — Mistral, Mixtral, Codestral."
    },
    "nvidia": {"description": "NVIDIA-hosted open models."},
    "ollama": {
        "auto_connect": False,
        "description": "Run models locally with the Ollama daemon.",
    },
    "openai": {"description": "GPT-5.x, GPT-4.1, etc."},
    "openrouter": {"description": "Many models, free tiers available."},
    "perplexity": {
        "description": "Perplexity Sonar models — search-augmented generation."
    },
    "qwencloud": {
        "description": "Qwen3.8 and other QwenCloud models via OpenAI-compatible APIs.",
        "fallback_models": ["qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus"],
        "model_registry_aliases": {"qwen3.8-max-preview": "qwencloud:qwen3.8-max"},
    },
    "router9": {
        "description": "Local proxy aggregating 40+ providers.",
        "kind": "api_key",
    },
    "sambanova": {"description": "SambaNova Cloud — fast Llama and Mistral inference."},
    "together": {
        "description": "Together AI — open models, fine-tuning, serverless inference."
    },
    "vertexai": {
        "description": "Google Cloud's enterprise-grade Gemini.",
        "fallback_models": [
            "gemini-3.5-flash",
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-2.5-pro",
            "imagen-4",
        ],
    },
    "xai": {"description": "xAI's Grok family."},
    "xiaomi": {
        "description": "Xiaomi's MiMo model API — vision, reasoning, and tool calling."
    },
    "zai": {"description": "Z.AI's GLM-5 family."},
}


def _key_label(provider_label: str) -> str:
    """ "Anthropic API key" — the label for a provider's primary credential."""
    return f"{provider_label} API key"


def _curated_credentials(config: Any) -> list[dict[str, object]]:
    """The credential form for a provider whose auth is one key plus a URL.

    Generated rather than restated: the field names come from the registry,
    which is the same place the connection reads them from, so a renamed
    variable cannot leave the form pointing at the old name.
    """
    fields: list[dict[str, object]] = []
    if config.env_var:
        fields.append(
            {
                "name": config.env_var,
                "label": _key_label(config.label),
                "secret": True,
                "required": config.auth != "local",
                "placeholder": "",
            }
        )
    if config.base_url_env_var:
        from app.agent.providers.registry import catalog_base_url

        fields.append(
            {
                "name": config.base_url_env_var,
                "label": "Base URL",
                "secret": False,
                "required": False,
                "placeholder": config.base_url or catalog_base_url(config),
            }
        )
    return fields


def _curated_entry(provider_id: str, config: Any) -> ProviderEntry:
    """Build one curated row from its connection config plus its override."""
    from app.agent.providers.registry import (
        PROVIDER_REGISTRY,
        catalog_docs_url,
        provider_label,
    )

    from app.agent.providers.registry import catalog_base_url, catalog_entry

    override = dict(_OVERRIDES.get(provider_id) or {})
    entry: ProviderEntry = {
        "id": provider_id,
        "label": provider_label(config),
        # A hand-written line beats a derived one, but a derived one beats a
        # blank row: name the host and the wire shape, which is what the
        # catalog can actually say.
        "description": _catalog_description(
            catalog_entry(config), config.base_url or catalog_base_url(config)
        ),
        "kind": _AUTH_KINDS.get(config.auth, "api_key"),
        "env_var": config.env_var,
        "credentials": _curated_credentials(config),
        "fallback_models": [],
        "oauth_command": "",
        # The provider's own key page when EvoFlux knows one, else the
        # catalog's model documentation — better than no link at all.
        "docs_url": config.docs_url or catalog_docs_url(config),
        "metadata_source_exclude": [],
        "model_registry_aliases": {},
        "live_model_metadata": False,
        "auto_connect": True,
        "source": "builtin",
        "transport": str(config.transport),
    }
    # ``models_dev_id`` says where to *read* this provider's catalog row.
    # ``models_dev_provider_id`` says something stronger: re-key that
    # catalog provider's models under this ID. That is right for a rename
    # (``google`` -> ``googlegenai``) and wrong when the catalog ID is
    # itself an EvoFlux provider — Codex reads OpenAI's rows but must not
    # take them over, or ``openai:*`` models would vanish from the
    # registry. Sharing is what ``metadata_source_provider`` is for.
    if config.models_dev_id and config.models_dev_id not in PROVIDER_REGISTRY:
        entry["models_dev_provider_id"] = config.models_dev_id
    entry.update(override)  # ty: ignore[invalid-argument-type]
    entry["env_vars"] = [
        str(field.get("name", "")) for field in entry.get("credentials") or []
    ]
    return entry


@lru_cache(maxsize=1)
def builtin_providers() -> list[ProviderEntry]:
    """Curated providers, in registry order, without loading user plugins."""
    from app.agent.providers.registry import PROVIDER_REGISTRY

    return [
        _curated_entry(provider_id, config)
        for provider_id, config in PROVIDER_REGISTRY.items()
    ]


#: Human labels for the credential a catalog provider needs, keyed by the
#: suffix models.dev uses. The names are conventional across the catalog, so
#: this reads the variable rather than restating a per-provider label.
_CREDENTIAL_LABELS: tuple[tuple[str, str], ...] = (
    ("_ACCESS_KEY_ID", "Access key ID"),
    ("_SECRET_ACCESS_KEY", "Secret access key"),
    ("_RESOURCE_NAME", "Resource name"),
    ("_BASE_URL", "Base URL"),
    ("_API_KEY", "API key"),
    ("_TOKEN", "Access token"),
    ("_REGION", "Region"),
    ("_PROJECT", "Project"),
    ("_LOCATION", "Location"),
    ("_KEY", "API key"),
)

#: Suffixes that name a setting rather than a secret.
_PUBLIC_SUFFIXES = frozenset(
    {"_BASE_URL", "_REGION", "_PROJECT", "_LOCATION", "_RESOURCE_NAME"}
)


def _credential_label(name: str) -> tuple[str, bool]:
    """A display label for one environment variable, and whether it is secret.

    Anything that is not obviously an endpoint, a region or a project
    identifier is treated as secret — the safe default for a field whose
    meaning was inferred rather than stated.
    """
    upper = name.upper()
    for suffix, label in _CREDENTIAL_LABELS:
        if upper.endswith(suffix):
            return label, suffix not in _PUBLIC_SUFFIXES
    return name.replace("_", " ").title(), True


def _catalog_description(envelope: dict[str, Any], api: str) -> str:
    """A one-line description built from what the catalog actually states."""
    npm = envelope.get("npm")
    host = api.split("//", 1)[-1].split("/", 1)[0]
    if isinstance(npm, str) and npm.startswith("@ai-sdk/"):
        return f"{host} — {npm.removeprefix('@ai-sdk/')} API, from models.dev."
    return f"{host} — from the models.dev catalog."


def _catalog_entry_from_envelope(envelope: dict[str, Any]) -> ProviderEntry | None:
    """Build a settings-UI row from one models.dev provider envelope.

    Returns ``None`` for an envelope EvoFlux cannot connect from — no
    endpoint, an endpoint templated on credentials there is no form for, or
    no credential variable at all. Listing those would put a row in the UI
    that can never reach a working state.
    """
    from app.agent.providers.registry import (
        _derived_base_url_env_var,
        transport_for_npm,
    )

    provider_id = str(envelope.get("id") or "").strip().lower()
    if not provider_id:
        return None

    api = envelope.get("api")
    api = api.strip() if isinstance(api, str) else ""
    if not api or "${" in api:
        return None

    env_names = [
        name for name in (envelope.get("env") or []) if isinstance(name, str) and name
    ]
    if not env_names:
        return None

    credentials: list[dict[str, object]] = []
    for index, name in enumerate(env_names):
        label, secret = _credential_label(name)
        credentials.append(
            {
                "name": name,
                "label": label,
                "secret": secret,
                "required": index == 0,
                "placeholder": "",
            }
        )
    base_url_var = _derived_base_url_env_var(provider_id)
    if base_url_var not in env_names:
        credentials.append(
            {
                "name": base_url_var,
                "label": "Base URL",
                "secret": False,
                "required": False,
                "placeholder": api,
            }
        )

    doc = envelope.get("doc")
    label = envelope.get("name")
    return {
        "id": provider_id,
        "label": label if isinstance(label, str) and label else provider_id,
        "description": _catalog_description(envelope, api),
        "kind": "api_key",
        "env_var": env_names[0],
        "env_vars": [*env_names, base_url_var],
        "credentials": credentials,
        "fallback_models": [],
        "oauth_command": "",
        "docs_url": doc if isinstance(doc, str) else "",
        "models_dev_provider_id": provider_id,
        "metadata_source_exclude": [],
        "model_registry_aliases": {},
        "live_model_metadata": False,
        # Opening the settings page must not fan out to 160-odd endpoints.
        # Catalog rows list their models only when the user asks — the same
        # rule Ollama already follows — which also stops a vendor's key
        # being sent to a plan variant of theirs the user never selected.
        "auto_connect": False,
        "source": "catalog",
        "transport": str(transport_for_npm(envelope.get("npm"))),
    }


@lru_cache(maxsize=1)
def catalog_providers() -> list[ProviderEntry]:
    """Every models.dev provider EvoFlux can reach, as settings-UI rows.

    This is what makes the long tail usable rather than merely resolvable:
    the factory could already build a provider from its catalog entry, but
    with no row in the settings UI there was no way to enter a key for one.

    Curated providers are excluded — they carry OAuth flows, cloud
    credential forms, attribution headers and deliberate endpoint choices
    the envelope cannot express — and so are the catalog IDs they claim. A
    duplicate row would offer the same endpoint twice under two names and
    shadow the curated provider's metadata alias.
    """
    from app.agent.providers.model_registry import all_provider_envelopes
    from app.agent.providers.registry import PROVIDER_REGISTRY

    claimed = set(PROVIDER_REGISTRY)
    claimed |= {config.models_dev_provider_id for config in PROVIDER_REGISTRY.values()}
    claimed |= set(_OVERRIDES)

    rows: list[ProviderEntry] = []
    for provider_id, envelope in sorted(all_provider_envelopes().items()):
        if provider_id in claimed:
            continue
        entry = _catalog_entry_from_envelope(envelope)
        if entry is not None:
            rows.append(entry)
    return rows


def all_providers(*, include_catalog: bool = True) -> list[ProviderEntry]:
    """Return the full catalog in display order.

    Curated first, then installed plugins, then the models.dev long tail —
    which is also the order of how much EvoFlux knows about each.

    *include_catalog* exists for callers that only care about providers with
    hand-written support, such as deciding which models to bundle offline.
    """
    entries = list(builtin_providers())
    known = {entry["id"] for entry in entries}
    from app.agent.providers.plugin_registry import provider_plugins

    for plugin in provider_plugins().values():
        if plugin.id in known:
            continue
        entry: ProviderEntry = {
            "id": plugin.id,
            "label": plugin.label,
            "description": plugin.description,
            "kind": plugin.kind,
            "env_var": plugin.credentials[0].name if plugin.credentials else "",
            "env_vars": [field.name for field in plugin.credentials],
            "fallback_models": list(plugin.fallback_models),
            "oauth_command": plugin.oauth_command,
            "docs_url": plugin.docs_url,
            "models_dev_provider_id": plugin.models_dev_provider_id,
            "metadata_source_provider": plugin.metadata_source_provider,
            "metadata_source_exclude": [],
            "model_registry_aliases": dict(plugin.model_registry_aliases),
            "live_model_metadata": False,
            "auto_connect": True,
            "source": "plugin",
        }
        entry["credentials"] = credential_map(plugin.credentials)
        entries.append(entry)
        known.add(plugin.id)

    if include_catalog:
        entries.extend(
            entry for entry in catalog_providers() if entry["id"] not in known
        )
    return entries


def find(provider_id: str) -> ProviderEntry | None:
    """Return one entry by ``id`` or None if not in the catalog."""
    for entry in all_providers():
        if entry["id"] == provider_id:
            return entry
    return None


def provider_key_vars() -> dict[str, str]:
    """Primary credential variable per curated provider.

    Callers use this to answer "does this environment hold any provider key
    at all?" — the first-run check, and the doctor command. Derived rather
    than restated so a renamed variable cannot leave the check watching a
    name nothing writes any more.

    Only curated providers are included: the long tail is not part of the
    "is EvoFlux set up?" question, and 165 more names would make the check
    match on a variable the user set for some other tool.
    """
    return {
        entry["id"]: entry["env_var"]
        for entry in builtin_providers()
        if entry.get("env_var")
    }


#: Backwards-compatible view of :func:`provider_key_vars` for callers that
#: import a mapping. Evaluated once at import, which is fine: the curated
#: set does not change at runtime.
PROVIDER_KEY_VAR: dict[str, str] = provider_key_vars()
