from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from app.agent.providers.catalog import ProviderEntry
from app.agent.providers.capabilities import get_capabilities
from app.agent.providers.model_metadata import get_model_features
from app.agent.providers.openai.compatible import OPENAI_COMPATIBLE_PROVIDER_SPECS
from app.core.config import settings

TIMEOUT_S = 3.0


@dataclass(frozen=True)
class DiscoveredModel:
    """One live model plus fields authored by the provider catalog."""

    id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)


def _secret_value(value: object) -> str:
    if value is None:
        return ""
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return str(get_secret_value())
    return str(value)


def _resolve(overrides: Mapping[str, str] | None, name: str, default: str = "") -> str:
    """Look up a value: overrides → env → settings → default.

    Used to thread per-request credentials/base-URLs through discovery
    without mutating ``os.environ`` (which would leak to concurrent
    requests).
    """
    if overrides and name in overrides:
        return overrides[name]
    env_val = os.getenv(name)
    if env_val:
        return env_val
    setting_val = _secret_value(getattr(settings, name, None))
    return setting_val or default


def is_agent_model_id(provider_id: str, model_id: str) -> bool:
    """Return whether registry metadata permits text/tool agent use."""
    qualified = f"{provider_id}:{model_id}"
    capabilities = get_capabilities(qualified)
    features = get_model_features(qualified)
    return capabilities.output.text and features.tool_call is not False


def filter_agent_model_ids(provider_id: str, model_ids: list[str]) -> list[str]:
    return [
        model_id for model_id in model_ids if is_agent_model_id(provider_id, model_id)
    ]


def _is_discovered_agent_model(provider_id: str, model: DiscoveredModel) -> bool:
    """Apply live authoritative negatives before registry fallback."""
    output = model.capabilities.get("output")
    if isinstance(output, dict) and output.get("text") is False:
        return False
    features = model.metadata.get("features")
    if isinstance(features, dict) and features.get("tool_call") is False:
        return False
    if provider_id == "fci":
        # FCI serves mixed model types and the bundled registry intentionally
        # does not guess tool support. Only the provider's live positive signal
        # makes a model safe for EvoFlux agent execution.
        return isinstance(features, dict) and features.get("tool_call") is True
    return is_agent_model_id(provider_id, model.id)


def _positive_catalog_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else None
    )


def _live_modalities(item: dict[str, Any]) -> tuple[list[str], list[str]]:
    architecture = item.get("architecture")
    if not isinstance(architecture, dict):
        architecture = {}
    input_modalities = architecture.get("input_modalities")
    output_modalities = architecture.get("output_modalities")
    if not isinstance(input_modalities, list):
        input_modalities = []
    if not isinstance(output_modalities, list):
        output_modalities = []
    return (
        [str(value).lower() for value in input_modalities if isinstance(value, str)],
        [str(value).lower() for value in output_modalities if isinstance(value, str)],
    )


def _metadata_from_openai_catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize rich OpenAI-compatible catalogs without inventing fields.

    OpenAI's own ``/models`` response contains only identity fields, while
    OpenRouter, FCI and Kimi return richer provider-owned contracts. Every
    field below is conditional so a basic catalog remains an ID list rather
    than an accidental source of false negatives.
    """
    metadata: dict[str, Any] = {}
    supported_endpoints = item.get("supported_endpoints")
    if isinstance(supported_endpoints, list):
        metadata["interfaces"] = [
            value for value in supported_endpoints if isinstance(value, str) and value
        ]
    limits: dict[str, int] = {}
    context = _positive_catalog_int(item.get("context_length"))
    top_provider = item.get("top_provider")
    if not isinstance(top_provider, dict):
        top_provider = {}
    max_completion = _positive_catalog_int(top_provider.get("max_completion_tokens"))
    if context is not None:
        limits["context_length"] = context
    if max_completion is not None:
        limits["max_completion_tokens"] = max_completion
    if limits:
        metadata["limits"] = limits

    supported = item.get("supported_parameters")
    if isinstance(supported, list):
        parameters = {value for value in supported if isinstance(value, str) and value}
        metadata["features"] = {
            "tool_call": "tools" in parameters,
            "temperature": "temperature" in parameters,
            "reasoning": bool(
                {"reasoning", "include_reasoning", "reasoning_effort"} & parameters
            ),
        }

    reasoning = item.get("reasoning")
    if isinstance(reasoning, dict):
        efforts = reasoning.get("supported_efforts")
        levels = (
            [value for value in efforts if isinstance(value, str) and value]
            if isinstance(efforts, list)
            else []
        )
        if reasoning.get("mandatory") is False and "none" not in levels:
            levels.append("none")
        thinking: dict[str, Any] = {
            "levels": levels,
            "control": "effort",
            "source": "provider_live",
        }
        default_effort = reasoning.get("default_effort")
        if isinstance(default_effort, str) and default_effort:
            thinking["default_level"] = default_effort
        if isinstance(reasoning.get("default_enabled"), bool):
            thinking["default_enabled"] = reasoning["default_enabled"]
        metadata["thinking"] = thinking

    # Kimi's catalog uses explicit booleans instead of supported_parameters.
    if isinstance(item.get("supports_reasoning"), bool):
        metadata.setdefault("features", {})["reasoning"] = item["supports_reasoning"]
    return metadata


def _capabilities_from_openai_catalog_item(
    item: dict[str, Any],
) -> dict[str, Any]:
    input_modalities, output_modalities = _live_modalities(item)
    capabilities: dict[str, Any] = {}
    input_caps: dict[str, bool] = {}
    output_caps: dict[str, bool] = {}
    if input_modalities:
        input_caps = {
            "vision": "image" in input_modalities,
            "audio": "audio" in input_modalities,
            "video": "video" in input_modalities,
        }
    elif isinstance(item.get("supports_image_in"), bool):
        input_caps["vision"] = item["supports_image_in"]
        if isinstance(item.get("supports_video_in"), bool):
            input_caps["video"] = item["supports_video_in"]
    if output_modalities:
        output_caps = {
            "text": "text" in output_modalities,
            "image": "image" in output_modalities,
            "audio": "audio" in output_modalities,
            "video": "video" in output_modalities,
        }
    if input_caps:
        capabilities["input"] = input_caps
    if output_caps:
        capabilities["output"] = output_caps
    return capabilities


def _entry_from_openai_catalog_item(item: dict[str, Any]) -> DiscoveredModel | None:
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None
    return DiscoveredModel(
        id=model_id,
        metadata=_metadata_from_openai_catalog_item(item),
        capabilities=_capabilities_from_openai_catalog_item(item),
    )


async def _openai_compatible_models(
    *,
    provider_id: str,
    base_url: str,
    api_key: str,
    extra_headers: Mapping[str, str] | None = None,
) -> list[DiscoveredModel]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    if extra_headers:
        headers.update(extra_headers)
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    # FPT may wrap an OpenAI-compatible list in its standard
    # ``code/message/data`` envelope.
    if isinstance(items, dict):
        items = items.get("data", [])
    if not isinstance(items, list):
        items = []
    models = sorted(
        (
            model
            for item in items
            if isinstance(item, dict)
            and (model := _entry_from_openai_catalog_item(item)) is not None
        ),
        key=lambda model: model.id,
    )
    logger.debug(
        "provider_models_discovered provider={} count={}", provider_id, len(models)
    )
    return models


# The v1 surface has no deployments listing; this legacy data-plane route
# still answers with api-key auth on both Foundry resource domains.
FOUNDRY_DEPLOYMENTS_API_VERSION = "2023-03-15-preview"


async def _foundry_models(
    overrides: Mapping[str, str] | None,
) -> list[DiscoveredModel]:
    """Return the deployment names on a Microsoft Foundry resource.

    ``GET {base}/models`` on the v1 surface lists the *region catalog*
    (hundreds of deployable models), not what the resource actually
    serves — only deployment names are invocable. Prefer the legacy
    deployments route; fall back to the catalog if it is ever retired
    so discovery (and the UI's save gate) keeps working.
    """
    from app.agent.providers.foundry import foundry_base_url

    api_key = _resolve(overrides, "FOUNDRY_API_KEY")
    resource = _resolve(overrides, "FOUNDRY_RESOURCE_NAME")
    if not (api_key and resource):
        return []
    base_url = foundry_base_url(resource)
    headers = {"Authorization": f"Bearer {api_key}", "api-key": api_key}
    deployments_url = f"{base_url.removesuffix('/v1')}/deployments"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.get(
                deployments_url,
                params={"api-version": FOUNDRY_DEPLOYMENTS_API_VERSION},
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return await _openai_compatible_models(
            provider_id="foundry",
            base_url=base_url,
            api_key=api_key,
            extra_headers={"api-key": api_key},
        )
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    models = sorted(
        (
            model
            for item in items
            if isinstance(item, dict)
            and (model := _entry_from_openai_catalog_item(item)) is not None
        ),
        key=lambda model: model.id,
    )
    logger.debug(
        "provider_models_discovered provider=foundry count={} source=deployments",
        len(models),
    )
    return models


async def _google_genai_models(
    overrides: Mapping[str, str] | None,
) -> list[DiscoveredModel]:
    api_key = _resolve(overrides, "GOOGLE_API_KEY")
    if not api_key:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
        )
        response.raise_for_status()
    data = response.json()
    items = data.get("models", []) if isinstance(data, dict) else []
    models: list[DiscoveredModel] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        methods = item.get("supportedGenerationMethods", [])
        if isinstance(name, str) and "generateContent" in methods:
            metadata: dict[str, Any] = {}
            limits: dict[str, int] = {}
            context = _positive_catalog_int(item.get("inputTokenLimit"))
            output = _positive_catalog_int(item.get("outputTokenLimit"))
            if context is not None:
                limits["context_length"] = context
            if output is not None:
                limits["max_completion_tokens"] = output
            if limits:
                metadata["limits"] = limits
            models.append(
                DiscoveredModel(
                    id=name.removeprefix("models/"),
                    metadata=metadata,
                )
            )
    return sorted(models, key=lambda model: model.id)


async def _anthropic_models(
    overrides: Mapping[str, str] | None,
) -> list[DiscoveredModel]:
    api_key = _resolve(overrides, "ANTHROPIC_API_KEY")
    if not api_key:
        return []
    base_url = _resolve(overrides, "ANTHROPIC_BASE_URL", settings.ANTHROPIC_BASE_URL)
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        response.raise_for_status()
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    return sorted(
        (
            DiscoveredModel(id=str(item["id"]))
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ),
        key=lambda model: model.id,
    )


async def _copilot_models() -> list[DiscoveredModel]:
    from app.agent.providers.copilot.oauth import CopilotOAuth

    oauth = CopilotOAuth.load()
    if oauth is None:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(
            "https://api.githubcopilot.com/models",
            headers={
                "Authorization": f"Bearer {oauth.github_token.get_secret_value()}",
                "Accept": "application/json",
                "User-Agent": "EvoFlux/1.0.0",
            },
        )
        response.raise_for_status()
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    return sorted(
        (
            DiscoveredModel(
                id=str(item["id"]),
                metadata=_metadata_from_openai_catalog_item(item),
                capabilities=_capabilities_from_openai_catalog_item(item),
            )
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item.get("model_picker_enabled", True)
        ),
        key=lambda model: model.id,
    )


async def _ollama_models(
    overrides: Mapping[str, str] | None,
) -> list[DiscoveredModel]:
    """Use Ollama's native API; its OpenAI shim omits model capabilities."""
    configured = _resolve(
        overrides,
        "OLLAMA_BASE_URL",
        OPENAI_COMPATIBLE_PROVIDER_SPECS["ollama"].base_url,
    ).rstrip("/")
    root = configured.removesuffix("/v1")
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(f"{root}/api/tags")
        response.raise_for_status()
        data = response.json()
        items = data.get("models", []) if isinstance(data, dict) else []
        names = [
            str(item["name"])
            for item in items
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]

        async def inspect(model_id: str) -> DiscoveredModel:
            show = await client.post(f"{root}/api/show", json={"model": model_id})
            show.raise_for_status()
            details = show.json()
            raw_capabilities = details.get("capabilities", [])
            capabilities = {
                value for value in raw_capabilities if isinstance(value, str)
            }
            model_info = details.get("model_info")
            context_lengths = (
                [
                    value
                    for key, value in model_info.items()
                    if isinstance(key, str)
                    and key.endswith(".context_length")
                    and _positive_catalog_int(value) is not None
                ]
                if isinstance(model_info, dict)
                else []
            )
            metadata: dict[str, Any] = {
                "features": {
                    "tool_call": "tools" in capabilities,
                    "reasoning": "thinking" in capabilities,
                }
            }
            if context_lengths:
                metadata["limits"] = {"context_length": max(context_lengths)}
            return DiscoveredModel(
                id=model_id,
                metadata=metadata,
                capabilities={
                    "input": {"vision": "vision" in capabilities},
                    "output": {"text": "completion" in capabilities},
                },
            )

        return sorted(
            await asyncio.gather(*(inspect(name) for name in names)),
            key=lambda model: model.id,
        )


async def _codex_models() -> list[DiscoveredModel]:
    from app.agent.providers.codex.oauth import CodexOAuth

    oauth = CodexOAuth.load()
    if oauth is None:
        return []
    if oauth.is_expired():
        oauth = oauth.refresh()
    headers = {
        "Authorization": f"Bearer {oauth.access_token.get_secret_value()}",
        "Content-Type": "application/json",
        "User-Agent": "EvoFlux/1.0.0",
        "originator": "EvoFlux",
    }
    if oauth.account_id:
        headers["ChatGPT-Account-Id"] = oauth.account_id
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.get(
            "https://chatgpt.com/backend-api/codex/models",
            params={"client_version": "1.0.0"},
            headers=headers,
        )
        response.raise_for_status()
    data = response.json()
    items = data.get("models", []) if isinstance(data, dict) else []
    models: list[DiscoveredModel] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("slug"), str):
            continue
        levels: list[str] = []
        supported = item.get("supported_reasoning_levels")
        if isinstance(supported, list):
            for option in supported:
                effort = option.get("effort") if isinstance(option, dict) else None
                if isinstance(effort, str) and effort and effort not in levels:
                    levels.append(effort)
        metadata: dict[str, Any] = {
            "thinking": {
                "levels": levels,
                "control": "effort",
                "source": "provider_live",
            }
        }
        models.append(DiscoveredModel(id=str(item["slug"]), metadata=metadata))
    return sorted(models, key=lambda model: model.id)


async def _bedrock_models(
    overrides: Mapping[str, str] | None = None,
) -> list[DiscoveredModel]:
    # boto3 is synchronous — run the whole discovery in a worker thread so
    # its network round-trips (list_foundation_models + paginated
    # list_inference_profiles) never block the event loop.
    return await asyncio.to_thread(_bedrock_models_sync, overrides)


def _bedrock_models_sync(
    overrides: Mapping[str, str] | None = None,
) -> list[DiscoveredModel]:
    import boto3
    from botocore.config import Config as BotoConfig

    region = (
        _resolve(overrides, "AWS_BEDROCK_REGION")
        or settings.AWS_BEDROCK_REGION
        or os.getenv("AWS_BEDROCK_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    kwargs: dict[str, object] = {
        "region_name": region,
        # Match the httpx discovery budget — a stalled AWS endpoint must not
        # pin the worker thread for botocore's default 60s × retries.
        "config": BotoConfig(
            connect_timeout=TIMEOUT_S,
            read_timeout=TIMEOUT_S,
            retries={"max_attempts": 1},
        ),
    }
    profile = (
        overrides["AWS_BEDROCK_PROFILE"]
        if overrides and "AWS_BEDROCK_PROFILE" in overrides
        else settings.AWS_BEDROCK_PROFILE or os.getenv("AWS_BEDROCK_PROFILE")
    )
    access_key = _resolve(overrides, "AWS_ACCESS_KEY_ID")
    secret_key = _resolve(overrides, "AWS_SECRET_ACCESS_KEY")
    if profile:
        session = boto3.Session(profile_name=profile)
        client = session.client("bedrock", **kwargs)
    elif access_key and secret_key:
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        client = session.client("bedrock", **kwargs)
    else:
        client = boto3.client("bedrock", **kwargs)
    models_by_id: dict[str, DiscoveredModel] = {}

    response = client.list_foundation_models(byOutputModality="TEXT")
    summaries = response.get("modelSummaries", [])
    for item in summaries:
        if not isinstance(item, dict) or not isinstance(item.get("modelId"), str):
            continue
        input_modalities = item.get("inputModalities")
        output_modalities = item.get("outputModalities")
        capabilities: dict[str, Any] = {}
        if isinstance(input_modalities, list):
            values = {
                str(value).upper()
                for value in input_modalities
                if isinstance(value, str)
            }
            capabilities["input"] = {
                "vision": "IMAGE" in values,
                "audio": "AUDIO" in values,
                "video": "VIDEO" in values,
            }
        if isinstance(output_modalities, list):
            values = {
                str(value).upper()
                for value in output_modalities
                if isinstance(value, str)
            }
            capabilities["output"] = {
                "text": "TEXT" in values,
                "image": "IMAGE" in values,
                "audio": "AUDIO" in values,
                "video": "VIDEO" in values,
            }
        models_by_id[str(item["modelId"])] = DiscoveredModel(
            id=str(item["modelId"]),
            capabilities=capabilities,
        )

    for profile_type in ("SYSTEM_DEFINED", "APPLICATION"):
        next_token: str | None = None
        while True:
            params = {"typeEquals": profile_type, "maxResults": 1000}
            if next_token:
                params["nextToken"] = next_token
            profiles_response = client.list_inference_profiles(**params)
            profile_summaries = profiles_response.get("inferenceProfileSummaries", [])
            for item in profile_summaries:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("inferenceProfileId"), str)
                    and item.get("status") in (None, "ACTIVE")
                ):
                    profile_id = str(item["inferenceProfileId"])
                    models_by_id.setdefault(profile_id, DiscoveredModel(id=profile_id))
            next_token = profiles_response.get("nextToken")
            if not isinstance(next_token, str) or not next_token:
                break

    return sorted(models_by_id.values(), key=lambda model: model.id)


async def discover_provider_model_entries(
    entry: ProviderEntry,
    *,
    overrides: Mapping[str, str] | None = None,
) -> list[DiscoveredModel]:
    """Return live provider models and provider-owned metadata.

    ``overrides`` lets callers (e.g. the settings ``/models`` route) inject
    a candidate API key + base URL for a single request without mutating
    ``os.environ`` — which would leak to other concurrent requests.
    """
    provider_id = entry["id"]
    try:
        match provider_id:
            case "openai":
                models = await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url=_resolve(
                        overrides, "OPENAI_BASE_URL", settings.OPENAI_BASE_URL
                    ),
                    api_key=_resolve(overrides, "OPENAI_API_KEY"),
                )
            case "ollama":
                models = await _ollama_models(overrides)
            case _ if provider_id in OPENAI_COMPATIBLE_PROVIDER_SPECS:
                spec = OPENAI_COMPATIBLE_PROVIDER_SPECS[provider_id]
                base_url = spec.base_url
                if spec.base_url_env_var:
                    base_url = _resolve(overrides, spec.base_url_env_var, spec.base_url)
                if provider_id == "fci":
                    from app.agent.providers.fci.fci import normalize_fci_base_url

                    base_url = normalize_fci_base_url(base_url)
                models = await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url=base_url,
                    api_key=_resolve(overrides, spec.env_var) or spec.default_api_key,
                )
            case "zai":
                models = await _openai_compatible_models(
                    provider_id=provider_id,
                    base_url="https://api.z.ai/api/paas/v4",
                    api_key=_resolve(overrides, "ZAI_API_KEY"),
                )
            case "foundry":
                models = await _foundry_models(overrides)
            case "googlegenai":
                models = await _google_genai_models(overrides)
            case "anthropic":
                models = await _anthropic_models(overrides)
            case "copilot":
                models = await _copilot_models()
            case "codex":
                entries = await _codex_models()
            case "bedrock":
                models = await _bedrock_models(overrides)
            case _:
                from app.agent.providers.plugin_registry import (
                    ProviderCredentialStore,
                    find_provider_plugin,
                )

                plugin = find_provider_plugin(provider_id)
                if plugin is not None:
                    store = ProviderCredentialStore(provider_id, dict(overrides or {}))
                    if plugin.discover_models is not None:
                        models = await plugin.discover_models(store)
                    else:
                        models = list(plugin.fallback_models)
                else:
                    models = []
        raw_entries = entries if provider_id == "codex" else models
        normalized_entries: list[DiscoveredModel] = []
        for model in raw_entries:
            if isinstance(model, DiscoveredModel):
                normalized_entries.append(model)
            elif isinstance(model, str):
                normalized_entries.append(DiscoveredModel(id=model))
        filtered = [
            model
            for model in normalized_entries
            if _is_discovered_agent_model(provider_id, model)
        ]
        from app.agent.providers.capabilities import (
            replace_runtime_provider_capabilities,
        )
        from app.agent.providers.model_metadata import replace_runtime_provider_metadata

        replace_runtime_provider_metadata(
            provider_id,
            {model.id: model.metadata for model in filtered if model.metadata},
        )
        replace_runtime_provider_capabilities(
            provider_id,
            {model.id: model.capabilities for model in filtered if model.capabilities},
        )
        return filtered
    except Exception as exc:
        logger.info(
            "provider_models_unavailable provider={} error={}", provider_id, exc
        )
        return []


async def discover_provider_models(
    entry: ProviderEntry,
    *,
    overrides: Mapping[str, str] | None = None,
) -> list[str]:
    """Compatibility API returning only live model IDs."""
    return [
        model.id
        for model in await discover_provider_model_entries(entry, overrides=overrides)
    ]


async def ensure_runtime_model_metadata(model_id: str | None) -> None:
    """Load live metadata once before validating a provider-owned control."""
    if not model_id or ":" not in model_id:
        return
    from app.agent.providers.catalog import find
    from app.agent.providers.model_metadata import has_runtime_model_metadata

    if has_runtime_model_metadata(model_id):
        return
    provider_id, _ = model_id.split(":", 1)
    entry = find(provider_id)
    if entry is None:
        return
    await discover_provider_model_entries(entry)
