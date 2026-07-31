"""Model metadata resolution.

Looks up per-model limits and other metadata for a fully-qualified
``provider:model`` string. Static registry metadata supplies the baseline;
sparse metadata from a provider's live catalog takes precedence at runtime.

This module intentionally stays API-compatible with the old metadata resolver,
but its source data now lives beside modality gates in the model registry.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
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

    def to_dict(self) -> dict[str, int | None]:
        return {
            "context_length": self.context_length,
            "max_completion_tokens": self.max_completion_tokens,
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

    def to_dict(self) -> dict[str, list[str] | str | bool | None]:
        return {
            "levels": list(self.levels),
            "control": self.control,
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

    def to_dict(self) -> dict[str, float | None]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }


@dataclass(frozen=True)
class ModelFeatures:
    """Operational flags and lifecycle metadata from the model catalog."""

    tool_call: bool | None = None
    attachment: bool | None = None
    temperature: bool | None = None
    reasoning: bool | None = None
    status: str | None = None
    release_date: str | None = None

    def to_dict(self) -> dict[str, bool | str | None]:
        return {
            "tool_call": self.tool_call,
            "attachment": self.attachment,
            "temperature": self.temperature,
            "reasoning": self.reasoning,
            "status": self.status,
            "release_date": self.release_date,
        }


@dataclass(frozen=True)
class ModelMetadata:
    """Non-modality metadata for one ``provider:model`` pair."""

    limits: ModelLimits = ModelLimits()
    thinking: ModelThinking = ModelThinking()
    cost: ModelCost = ModelCost()
    features: ModelFeatures = ModelFeatures()
    interfaces: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "limits": self.limits.to_dict(),
            "thinking": self.thinking.to_dict(),
            "cost": self.cost.to_dict(),
            "features": self.features.to_dict(),
            "interfaces": list(self.interfaces),
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

    return ModelMetadata(
        limits=ModelLimits(
            context_length=_positive_int(
                limits_spec.get("context_length"), "limits.context_length"
            ),
            max_completion_tokens=_positive_int(
                limits_spec.get("max_completion_tokens"),
                "limits.max_completion_tokens",
            ),
        ),
        thinking=ModelThinking(
            levels=_string_tuple(thinking_spec.get("levels"), "thinking.levels"),
            control=_optional_string(
                thinking_spec.get("control"), "thinking.control"
            ),
            default_level=_optional_string(
                thinking_spec.get("default_level"), "thinking.default_level"
            ),
            default_enabled=_optional_bool(
                thinking_spec.get("default_enabled"), "thinking.default_enabled"
            ),
            source=_optional_string(thinking_spec.get("source"), "thinking.source"),
        ),
        cost=ModelCost(
            input=_finite_float(cost_spec.get("input"), "cost.input"),
            output=_finite_float(cost_spec.get("output"), "cost.output"),
            cache_read=_finite_float(cost_spec.get("cache_read"), "cost.cache_read"),
            cache_write=_finite_float(cost_spec.get("cache_write"), "cost.cache_write"),
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
            status=_optional_string(features_spec.get("status"), "features.status"),
            release_date=_optional_string(
                features_spec.get("release_date"), "features.release_date"
            ),
        ),
        interfaces=_string_tuple(spec.get("interfaces"), "interfaces"),
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
            for field in ("limits", "thinking", "cost", "features", "interfaces")
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


def get_model_metadata(model_id: str | None) -> ModelMetadata:
    """Return metadata for a fully-qualified ``provider:model`` string."""
    if not model_id:
        return _DEFAULT
    normalized = model_id.lower()
    base = _registry().get(normalized, _DEFAULT)
    runtime = _runtime_metadata.get(normalized)
    if runtime is None:
        return base
    return _merge_metadata(_deep_merge_dict(base.to_dict(), runtime))


def get_model_limits(model_id: str | None) -> ModelLimits:
    """Return token limits for a fully-qualified ``provider:model`` string."""
    return get_model_metadata(model_id).limits


def get_model_cost(model_id: str | None) -> ModelCost:
    """Return pricing metadata for a fully-qualified ``provider:model`` string."""
    return get_model_metadata(model_id).cost


def get_model_features(model_id: str | None) -> ModelFeatures:
    """Return support flags for a fully-qualified ``provider:model`` string."""
    return get_model_metadata(model_id).features


def get_effective_model_thinking(model_id: str | None) -> ModelThinking:
    """Intersect the provider model contract with the EvoFlux transport.

    Provider model capability and adapter capability are separate facts. For
    example Bedrock foundation models can reason, but the current Converse
    adapter does not translate EvoFlux's named effort selector. Advertising
    those levels would make the UI persist a setting that is silently ignored.
    """
    if not model_id or ":" not in model_id:
        return ModelThinking()
    provider_id, provider_model = model_id.lower().split(":", 1)
    raw = get_model_metadata(model_id).thinking
    levels = raw.levels

    if provider_id == "bedrock":
        return ModelThinking(
            control="none",
            source="adapter_constraint",
        )
    if provider_id in {"googlegenai", "vertexai"}:
        if "gemma" in provider_model:
            return ModelThinking(control="none", source="adapter_constraint")
        if provider_model.startswith("gemini-3"):
            return ModelThinking(
                levels=tuple(
                    level
                    for level in levels
                    if level in {"minimal", "low", "medium", "high"}
                ),
                control="effort",
                default_level=raw.default_level,
                default_enabled=raw.default_enabled,
                source=raw.source or "provider_profile",
            )
        # The generateContent API uses thinkingBudget for Gemini 2.5.
        # EvoFlux implements only the documented zero-budget off switch for
        # Flash/Lite; sending thinkingLevel to 2.5 models is a provider error.
        if provider_model.startswith("gemini-2.5-flash"):
            return ModelThinking(
                levels=("none",),
                control="budget",
                default_enabled=True,
                source="provider_profile",
            )
        return ModelThinking(control="none", source="adapter_constraint")
    if provider_id == "deepseek" and provider_model.startswith("deepseek-v4"):
        # Direct API contract (July 2026): low/high/max, with xhigh accepted
        # and mapped by the model. Thinking is on by default and can be disabled.
        return ModelThinking(
            levels=("none", "low", "high", "xhigh", "max"),
            control="effort",
            default_level="high",
            default_enabled=True,
            source="provider_profile",
        )
    return raw


def get_model_thinking_levels(model_id: str | None) -> tuple[str, ...]:
    """Return exact selectable reasoning controls for one model."""
    return get_effective_model_thinking(model_id).levels


def get_model_interfaces(model_id: str | None) -> tuple[str, ...]:
    """Return provider-advertised invocation interfaces when available."""
    return get_model_metadata(model_id).interfaces
