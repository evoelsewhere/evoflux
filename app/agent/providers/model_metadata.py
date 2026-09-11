"""Model metadata resolution.

Looks up per-model limits and other metadata for a fully-qualified
``provider:model`` string. Static registry metadata supplies the baseline;
sparse metadata from a provider's live catalog takes precedence at runtime.

This module intentionally stays API-compatible with the old metadata resolver,
but its source data now lives beside modality gates in the model registry.
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dc_field
from functools import lru_cache
from typing import Any

from loguru import logger

from app.agent.providers.model_registry import load_model_registry


@dataclass(frozen=True)
class ModelLimits:
    """Token limits for one model.

    ``None`` means unknown, not unlimited.
    """

    context_length: int | None = None
    max_completion_tokens: int | None = None
    #: Cap on the prompt alone, when the provider states one separately from
    #: the whole context window. Most models have no such split.
    max_input_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "context_length": self.context_length,
            "max_completion_tokens": self.max_completion_tokens,
            "max_input_tokens": self.max_input_tokens,
        }


@dataclass(frozen=True)
class ModelThinking:
    """Effective reasoning controls supported by the EvoFlux adapter.

    ``levels`` contains exact accepted values. An empty tuple means the model
    may reason internally, but this integration exposes no safe control.
    ``control`` describes the provider wire contract for diagnostics/UI.
    """

    levels: tuple[str, ...] = ()
    control: str | None = None
    default_level: str | None = None
    default_enabled: bool | None = None
    source: str | None = None
    #: Bounds on an explicit thinking-token budget, when the model documents
    #: one. ``budget_min`` is the smallest budget the endpoint accepts (a
    #: request below it is rejected, not clamped); ``budget_max`` is the
    #: largest it will honour. Both are ``None`` when the model exposes no
    #: budget knob, or exposes one without stating its range.
    budget_min: int | None = None
    budget_max: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "levels": list(self.levels),
            "control": self.control,
            "budget": {"min": self.budget_min, "max": self.budget_max},
            "default_level": self.default_level,
            "default_enabled": self.default_enabled,
            "source": self.source,
        }


@dataclass(frozen=True)
class ModelCost:
    """Per-token pricing metadata when known."""

    input: float | None = None
    output: float | None = None
    cache_read: float | None = None
    cache_write: float | None = None
    #: Billed separately from ``output`` by providers that meter thinking
    #: tokens on their own line.
    reasoning: float | None = None
    input_audio: float | None = None
    output_audio: float | None = None
    #: Rates that replace the headline ones past a context threshold, each
    #: carrying the ``above_tokens`` it applies from. Ordered as the catalog
    #: states them.
    tiers: tuple[dict[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "reasoning": self.reasoning,
            "input_audio": self.input_audio,
            "output_audio": self.output_audio,
            "tiers": [dict(tier) for tier in self.tiers],
        }


@dataclass(frozen=True)
class ModelFeatures:
    """Operational flags and lifecycle metadata from the model catalog."""

    tool_call: bool | None = None
    attachment: bool | None = None
    temperature: bool | None = None
    reasoning: bool | None = None
    structured_output: bool | None = None
    open_weights: bool | None = None
    status: str | None = None
    release_date: str | None = None
    last_updated: str | None = None
    #: Training-data cutoff as the catalog states it (``"2024-12"``).
    knowledge: str | None = None
    family: str | None = None
    #: Display name and blurb from the catalog, so the picker can show what
    #: a model is without EvoFlux restating it.
    name: str | None = None
    description: str | None = None
    #: Streaming field carrying the reasoning trace on this model's wire
    #: (``reasoning_content``, ``reasoning_details``). ``None`` when the
    #: model does not interleave reasoning with its output.
    interleaved_field: str | None = None

    def to_dict(self) -> dict[str, bool | str | None]:
        return {
            "tool_call": self.tool_call,
            "attachment": self.attachment,
            "temperature": self.temperature,
            "reasoning": self.reasoning,
            "structured_output": self.structured_output,
            "open_weights": self.open_weights,
            "status": self.status,
            "release_date": self.release_date,
            "last_updated": self.last_updated,
            "knowledge": self.knowledge,
            "family": self.family,
            "name": self.name,
            "description": self.description,
            "interleaved_field": self.interleaved_field,
        }


@dataclass(frozen=True)
class ModelMetadata:
    """Non-modality metadata for one ``provider:model`` pair."""

    limits: ModelLimits = ModelLimits()
    thinking: ModelThinking = ModelThinking()
    cost: ModelCost = ModelCost()
    features: ModelFeatures = ModelFeatures()
    interfaces: tuple[str, ...] = ()
    #: Alternate service tiers (``{"fast": {"body": ..., "headers": ...,
    #: "cost": ...}}``). The patch is the provider's own wire contract and is
    #: carried verbatim rather than re-spelled.
    modes: dict[str, Any] = dc_field(default_factory=dict)
    #: Per-model overrides of the provider envelope — ``npm``, ``api``,
    #: ``shape`` — for rows that reach a different endpoint than their
    #: provider's default.
    wire: dict[str, str] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "limits": self.limits.to_dict(),
            "thinking": self.thinking.to_dict(),
            "cost": self.cost.to_dict(),
            "features": self.features.to_dict(),
            "interfaces": list(self.interfaces),
            "modes": deepcopy(self.modes),
            "wire": dict(self.wire),
        }


_DEFAULT = ModelMetadata()
_runtime_metadata: dict[str, dict[str, Any]] = {}


def _positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"`{field}` must be a positive integer")
    if value <= 0:
        raise ValueError(f"`{field}` must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int | None:
    """An integer that may legitimately be zero, or ``None``."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"`{field}` must be a non-negative integer")
    if value < 0:
        raise ValueError(f"`{field}` must be a non-negative integer")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"`{field}` must be a list of strings")
    return tuple(value)


def _finite_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"`{field}` must be a number")
    return float(value)


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError(f"`{field}` must be a boolean")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"`{field}` must be a string")
    return value


def _cost_tiers(value: Any, name: str) -> tuple[dict[str, float], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"`{name}` must be a list of mappings")
    tiers: list[dict[str, float]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"`{name}` must be a list of mappings")
        tiers.append(
            {
                key: float(rate)
                for key, rate in item.items()
                if isinstance(key, str)
                and not isinstance(rate, bool)
                and isinstance(rate, int | float)
            }
        )
    return tuple(tiers)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"`{name}` must be a mapping")
    return deepcopy(value)


def _string_mapping(value: Any, name: str) -> dict[str, str]:
    mapping = _mapping(value, name)
    if not all(
        isinstance(key, str) and isinstance(item, str) for key, item in mapping.items()
    ):
        raise TypeError(f"`{name}` must map strings to strings")
    return mapping


def _merge_metadata(spec: dict[str, Any]) -> ModelMetadata:
    limits_spec = spec.get("limits") or {}
    thinking_spec = spec.get("thinking") or {}
    cost_spec = spec.get("cost") or {}
    features_spec = spec.get("features") or {}
    if not isinstance(limits_spec, dict):
        raise TypeError("`limits` must be a mapping")
    if not isinstance(thinking_spec, dict):
        raise TypeError("`thinking` must be a mapping")
    if not isinstance(cost_spec, dict):
        raise TypeError("`cost` must be a mapping")
    if not isinstance(features_spec, dict):
        raise TypeError("`features` must be a mapping")
    budget_spec = thinking_spec.get("budget") or {}
    if not isinstance(budget_spec, dict):
        raise TypeError("`thinking.budget` must be a mapping")

    return ModelMetadata(
        limits=ModelLimits(
            context_length=_positive_int(
                limits_spec.get("context_length"), "limits.context_length"
            ),
            max_completion_tokens=_positive_int(
                limits_spec.get("max_completion_tokens"),
                "limits.max_completion_tokens",
            ),
            max_input_tokens=_positive_int(
                limits_spec.get("max_input_tokens"), "limits.max_input_tokens"
            ),
        ),
        thinking=ModelThinking(
            levels=_string_tuple(thinking_spec.get("levels"), "thinking.levels"),
            control=_optional_string(thinking_spec.get("control"), "thinking.control"),
            default_level=_optional_string(
                thinking_spec.get("default_level"), "thinking.default_level"
            ),
            default_enabled=_optional_bool(
                thinking_spec.get("default_enabled"), "thinking.default_enabled"
            ),
            source=_optional_string(thinking_spec.get("source"), "thinking.source"),
            # A budget floor of zero is meaningful — it is how a model says
            # "a zero budget turns thinking off" — so it cannot go through
            # the positive-int guard.
            budget_min=_non_negative_int(budget_spec.get("min"), "thinking.budget.min"),
            budget_max=_positive_int(budget_spec.get("max"), "thinking.budget.max"),
        ),
        cost=ModelCost(
            input=_finite_float(cost_spec.get("input"), "cost.input"),
            output=_finite_float(cost_spec.get("output"), "cost.output"),
            cache_read=_finite_float(cost_spec.get("cache_read"), "cost.cache_read"),
            cache_write=_finite_float(cost_spec.get("cache_write"), "cost.cache_write"),
            reasoning=_finite_float(cost_spec.get("reasoning"), "cost.reasoning"),
            input_audio=_finite_float(cost_spec.get("input_audio"), "cost.input_audio"),
            output_audio=_finite_float(
                cost_spec.get("output_audio"), "cost.output_audio"
            ),
            tiers=_cost_tiers(cost_spec.get("tiers"), "cost.tiers"),
        ),
        features=ModelFeatures(
            tool_call=_optional_bool(
                features_spec.get("tool_call"), "features.tool_call"
            ),
            attachment=_optional_bool(
                features_spec.get("attachment"), "features.attachment"
            ),
            temperature=_optional_bool(
                features_spec.get("temperature"), "features.temperature"
            ),
            reasoning=_optional_bool(
                features_spec.get("reasoning"), "features.reasoning"
            ),
            structured_output=_optional_bool(
                features_spec.get("structured_output"), "features.structured_output"
            ),
            open_weights=_optional_bool(
                features_spec.get("open_weights"), "features.open_weights"
            ),
            status=_optional_string(features_spec.get("status"), "features.status"),
            release_date=_optional_string(
                features_spec.get("release_date"), "features.release_date"
            ),
            last_updated=_optional_string(
                features_spec.get("last_updated"), "features.last_updated"
            ),
            knowledge=_optional_string(
                features_spec.get("knowledge"), "features.knowledge"
            ),
            family=_optional_string(features_spec.get("family"), "features.family"),
            name=_optional_string(features_spec.get("name"), "features.name"),
            description=_optional_string(
                features_spec.get("description"), "features.description"
            ),
            interleaved_field=_optional_string(
                features_spec.get("interleaved_field"), "features.interleaved_field"
            ),
        ),
        interfaces=_string_tuple(spec.get("interfaces"), "interfaces"),
        modes=_mapping(spec.get("modes"), "modes"),
        wire=_string_mapping(spec.get("wire"), "wire"),
    )


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge_dict(current, value)
        else:
            result[key] = deepcopy(value)
    return result


def set_runtime_model_metadata(model_id: str, metadata: dict[str, Any]) -> None:
    """Register sparse metadata reported by a provider's live model catalog."""
    normalized = model_id.strip().lower()
    if ":" not in normalized:
        raise ValueError("runtime model metadata requires a qualified model ID")
    # Validate before publishing so a malformed provider payload cannot poison
    # every subsequent metadata lookup.
    _merge_metadata(_deep_merge_dict(_DEFAULT.to_dict(), metadata))
    _runtime_metadata[normalized] = deepcopy(metadata)


def replace_runtime_provider_metadata(
    provider_id: str, models: dict[str, dict[str, Any]]
) -> None:
    """Atomically replace one provider's live metadata after a fresh discovery."""
    provider = provider_id.strip().lower()
    if not provider or ":" in provider:
        raise ValueError("runtime metadata provider ID must be unqualified")
    replacement: dict[str, dict[str, Any]] = {}
    for model_id, metadata in models.items():
        key = f"{provider}:{model_id.strip().lower()}"
        _merge_metadata(_deep_merge_dict(_DEFAULT.to_dict(), metadata))
        replacement[key] = deepcopy(metadata)

    prefix = f"{provider}:"
    stale = [key for key in _runtime_metadata if key.startswith(prefix)]
    for key in stale:
        _runtime_metadata.pop(key, None)
    _runtime_metadata.update(replacement)


def has_runtime_model_metadata(model_id: str | None) -> bool:
    return bool(model_id and model_id.lower() in _runtime_metadata)


def clear_runtime_model_metadata() -> None:
    """Clear provider-discovered metadata (primarily useful for tests)."""
    _runtime_metadata.clear()


def _load_registry() -> dict[str, ModelMetadata]:
    registry: dict[str, ModelMetadata] = {}
    for key, value in load_model_registry().items():
        metadata = {
            field: value[field]
            for field in (
                "limits",
                "thinking",
                "cost",
                "features",
                "interfaces",
                "modes",
                "wire",
            )
            if field in value
        }
        if not metadata:
            continue
        try:
            registry[key] = _merge_metadata(metadata)
        except (TypeError, ValueError) as exc:
            logger.warning("model registry: skipping metadata for {!r} ({})", key, exc)
    logger.debug("model registry: loaded {} metadata entries", len(registry))
    return registry


@lru_cache(maxsize=1)
def _registry() -> dict[str, ModelMetadata]:
    return _load_registry()


def qualified_model_id(provider_id: str, model: str) -> str:
    """Join *provider_id* and *model* into a registry key.

    Callers hand this function either a bare model ID or one that is
    already qualified, so it has to tell the two apart. A colon is not the
    signal: Bedrock model IDs carry their own (``us.anthropic.claude-…-v1:0``),
    and treating those as pre-qualified parsed the version suffix as the
    model and the whole rest as the provider, so every Bedrock model missed
    the catalog. The provider prefix is the only reliable marker.
    """
    prefix = f"{provider_id.strip().lower()}:"
    normalized = model.strip()
    if normalized.lower().startswith(prefix):
        return normalized
    return f"{provider_id}:{normalized}"


def get_model_metadata(model_id: str | None) -> ModelMetadata:
    """Return metadata for a fully-qualified ``provider:model`` string."""
    if not model_id:
        return _DEFAULT
    normalized = model_id.lower()
    base = _registry().get(normalized, _DEFAULT)
    runtime = _runtime_metadata.get(normalized)
    resolved = (
        base
        if runtime is None
        else _merge_metadata(_deep_merge_dict(base.to_dict(), runtime))
    )
    if normalized == "kimi:k3":
        # The live catalog reports K3's 1M model maximum, not the account's
        # entitlement. Default to the Moderato-safe 256K unless 1M is explicit.
        from app.core.config import settings

        raw_context = os.getenv("KIMI_CODE_K3_CONTEXT_WINDOW") or str(
            settings.KIMI_CODE_K3_CONTEXT_WINDOW
        )
        try:
            configured_context = int(raw_context)
        except (TypeError, ValueError):
            configured_context = 262144
        context_length = 1048576 if configured_context == 1048576 else 262144
        spec = resolved.to_dict()
        spec["limits"]["context_length"] = context_length
        resolved = _merge_metadata(spec)
    return resolved


def get_model_limits(model_id: str | None) -> ModelLimits:
    """Return token limits for a fully-qualified ``provider:model`` string."""
    return get_model_metadata(model_id).limits


def get_model_cost(model_id: str | None) -> ModelCost:
    """Return pricing metadata for a fully-qualified ``provider:model`` string."""
    return get_model_metadata(model_id).cost


def get_model_features(model_id: str | None) -> ModelFeatures:
    """Return support flags for a fully-qualified ``provider:model`` string."""
    return get_model_metadata(model_id).features


#: Model families whose reasoning EvoFlux's adapter cannot steer, whatever
#: the catalog says. This is the one place a hardcoded name still belongs:
#: it records a limitation of *this* client, not a fact about the model, and
#: no upstream catalog will ever publish it.
#:
#: Gemma is served through the Gemini endpoint but rejects ``thinkingConfig``
#: outright, so advertising a control would make the UI persist a setting
#: that turns every request into a 400.
_ADAPTER_CANNOT_STEER: dict[str, tuple[str, ...]] = {
    "googlegenai": ("gemma",),
    "vertexai": ("gemma",),
}


def get_effective_model_thinking(model_id: str | None) -> ModelThinking:
    """Intersect the model's published reasoning contract with this adapter.

    The contract itself — which named efforts a model takes, whether it has
    an off switch, what budget bounds it enforces — is catalog data, read
    straight from ``reasoning_options`` in models.dev and merged with any
    curated or user override. It used to be restated here as a stack of
    per-family ``if`` branches; every one of those branches is now derived,
    which is why a new model gets the right controls the day the catalog
    lists it rather than the day someone edits this file.

    What stays is the intersection: a model may document a control that
    EvoFlux's own transport cannot express, and advertising it would make
    the UI persist a setting that is silently dropped or actively rejected.
    """
    if not model_id or ":" not in model_id:
        return ModelThinking()
    provider_id, provider_model = model_id.lower().split(":", 1)

    blocked = _ADAPTER_CANNOT_STEER.get(provider_id, ())
    if any(marker in provider_model for marker in blocked):
        return ModelThinking(control="none", source="adapter_constraint")

    return get_model_metadata(model_id).thinking


def get_model_modes(model_id: str | None) -> dict[str, Any]:
    """Every alternate service tier this model offers.

    Unions what the catalog publishes for the model with the tiers EvoFlux's
    own integration implements (see
    :data:`~app.agent.providers.registry.PROVIDER_MODES`) — Codex's fast
    lane belongs to a ChatGPT subscription, so no model catalog lists it.

    Both are honoured on the wire by
    :func:`app.agent.providers.options.service_tier_fields`, which is why
    they can be reported together: every tier named here is one a request
    can actually select. Callers ask by name rather than testing a provider
    prefix, so adding a tier is data rather than a condition in each
    consumer.
    """
    if not model_id or ":" not in model_id:
        return {}
    from app.agent.providers.registry import provider_modes

    # The catalog is the base; a provider-implemented tier of the same name
    # wins, because it is the one whose patch this client actually speaks.
    merged = dict(get_model_metadata(model_id).modes)
    merged.update(provider_modes(model_id.split(":", 1)[0]))
    return merged


def get_model_mode(model_id: str | None, name: str) -> dict[str, Any]:
    """The wire patch for one tier, or empty when the model has no such tier."""
    return get_model_modes(model_id).get(name) or {}


def get_model_thinking_levels(model_id: str | None) -> tuple[str, ...]:
    """Return exact selectable reasoning controls for one model."""
    return get_effective_model_thinking(model_id).levels


def get_model_interfaces(model_id: str | None) -> tuple[str, ...]:
    """Return provider-advertised invocation interfaces when available."""
    return get_model_metadata(model_id).interfaces
