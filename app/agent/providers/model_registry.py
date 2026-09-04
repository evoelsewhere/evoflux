"""Shared model registry loader.

Registry precedence is:

1. bundled ``model_registry.json`` snapshot for cold/offline starts;
2. cached/refreshed ``https://models.dev/api.json`` metadata;
3. local ``{EVOFLUX_CONFIG_DIR}/model_registry.yaml`` overrides.

Provider-discovered runtime metadata is applied by ``model_metadata.py`` after
these static sources. Public resolver APIs stay in ``capabilities.py`` and
``model_metadata.py``; this module owns static source loading, normalization,
aliases, and merge order.

The ``models.dev`` fetch above is lazy and memoized, so a long-running process
only ever sees the catalog it read first. ``registry_refresh.py`` drives
``refresh_models_dev_cache`` on an interval to keep it current.
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import httpx
import yaml
from loguru import logger

from app.core.config import settings


ModelRegistry = dict[str, dict[str, Any]]

MODELS_DEV_URL = "https://models.dev/api.json"
MODELS_DEV_CACHE_TTL_SECONDS = 24 * 60 * 60


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = deepcopy(value)
    return result


def _provider_entries(include_plugins: bool) -> list[Any]:
    from app.agent.providers.catalog import all_providers, builtin_providers

    return list(all_providers() if include_plugins else builtin_providers())


def _provider_id_aliases(*, include_plugins: bool = True) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for entry in _provider_entries(include_plugins):
        provider_id = entry.get("id")
        source_id = entry.get("models_dev_provider_id")
        if isinstance(provider_id, str) and isinstance(source_id, str) and source_id:
            # First claim wins. ``all_providers()`` yields curated entries
            # before the catalog long tail, and a curated provider's alias
            # (``alibaba`` -> ``qwencloud``) must not be overwritten by a
            # catalog row that maps the same ID to itself.
            aliases.setdefault(source_id.lower(), provider_id.lower())
    return aliases


def _model_registry_aliases(
    *, include_plugins: bool = True
) -> tuple[dict[str, tuple[str, frozenset[str]]], dict[str, str]]:
    provider_aliases: dict[str, tuple[str, frozenset[str]]] = {}
    model_aliases: dict[str, str] = {}
    for entry in _provider_entries(include_plugins):
        provider_id = entry.get("id")
        if not isinstance(provider_id, str) or not provider_id:
            continue
        target_provider = provider_id.lower()
        source_provider = entry.get("metadata_source_provider")
        if isinstance(source_provider, str) and source_provider:
            excluded = entry.get("metadata_source_exclude", [])
            excluded_fields = frozenset(
                field.lower() for field in excluded if isinstance(field, str) and field
            )
            provider_aliases[target_provider] = (
                source_provider.lower(),
                excluded_fields,
            )

        aliases = entry.get("model_registry_aliases")
        if not isinstance(aliases, dict):
            continue
        for target_model, source_key in aliases.items():
            if not isinstance(target_model, str) or not isinstance(source_key, str):
                continue
            target_key = (
                target_model
                if ":" in target_model
                else f"{target_provider}:{target_model}"
            )
            model_aliases[target_key.lower()] = source_key.lower()
    return provider_aliases, model_aliases


def apply_model_registry_aliases(
    registry: ModelRegistry, *, overwrite: bool = False, include_plugins: bool = True
) -> ModelRegistry:
    """Add provider-owned metadata aliases for runtime provider/model IDs."""
    provider_aliases, model_aliases = _model_registry_aliases(
        include_plugins=include_plugins
    )
    result = dict(registry)
    for key, value in registry.items():
        if ":" not in key:
            continue
        provider_id, model_id = key.split(":", 1)
        for target_provider, (
            source_provider,
            excluded_fields,
        ) in provider_aliases.items():
            if provider_id != source_provider:
                continue
            target_key = f"{target_provider}:{model_id}"
            aliased_value = {
                field: deepcopy(field_value)
                for field, field_value in value.items()
                if field not in excluded_fields
            }
            if overwrite:
                current = deepcopy(result.get(target_key, {}))
                for field in excluded_fields:
                    current.pop(field, None)
                result[target_key] = _deep_merge(current, aliased_value)
            elif target_key not in result:
                result[target_key] = aliased_value

    for target_key, source_key in model_aliases.items():
        source = result.get(source_key)
        if source and overwrite:
            result[target_key] = _deep_merge(result.get(target_key, {}), source)
        elif source and target_key not in result:
            result[target_key] = deepcopy(source)
    return result


def _sibling_providers() -> dict[str, tuple[str, ...]]:
    """Catalog providers that are the same vendor as a curated provider.

    Several vendors publish one API under several catalog rows: a
    pay-as-you-go endpoint plus regional and subscription-plan variants.
    models.dev lists them separately (``xiaomi`` alongside
    ``xiaomi-token-plan-sgp``), and the model lists differ — the plan
    endpoints carry TTS and ASR models the base row does not.

    A user on a plan endpoint configures the curated provider and points its
    base URL at the plan, so their models resolve under ``xiaomi:`` and miss
    every sibling's metadata. This finds the siblings the only way that is
    not guesswork: a shared credential variable. Two catalog rows that read
    the same secret are the same account at the same vendor.
    """
    curated = {
        entry["id"]: entry
        for entry in _provider_entries(include_plugins=False)
        if isinstance(entry.get("id"), str)
    }
    by_env: dict[str, list[str]] = {}
    for provider_id, provider in _models_dev_providers().items():
        for name in provider.get("env") or []:
            if isinstance(name, str) and name:
                by_env.setdefault(name, []).append(provider_id)

    claimed = set(curated)
    claimed |= {
        str(entry["models_dev_provider_id"])
        for entry in curated.values()
        if entry.get("models_dev_provider_id")
    }

    siblings: dict[str, tuple[str, ...]] = {}
    for provider_id, entry in curated.items():
        # A local daemon serves the user's own files. Quantized checkpoints
        # share names with hosted ones but not their limits, so borrowing
        # metadata there would state a context window that is not true.
        if entry.get("kind") == "local":
            continue
        source = str(entry.get("models_dev_provider_id") or provider_id)
        env_var = entry.get("env_var")
        if not isinstance(env_var, str) or not env_var:
            continue
        related = [
            candidate
            for candidate in by_env.get(env_var, ())
            # Two conditions, because either alone is wrong. A shared
            # credential can span genuinely different products — Kimi Code
            # and the Moonshot platform both read ``MOONSHOT_API_KEY`` — so
            # the name has to mark the candidate as a variant of *this*
            # provider's row, which is the convention models.dev follows for
            # regional and plan endpoints (``xiaomi-token-plan-sgp``).
            if candidate.startswith(f"{source}-") and candidate not in claimed
        ]
        if related:
            siblings[provider_id] = tuple(sorted(related))
    return siblings


def apply_sibling_model_aliases(registry: ModelRegistry) -> ModelRegistry:
    """Fill a curated provider's gaps from its own vendor's other rows.

    Only gaps: a model the provider's own catalog row describes always wins,
    because that row matches the endpoint EvoFlux resolves by default. This
    adds the models only a plan or regional variant lists, so a user on that
    endpoint sees the same names, limits and descriptions as everyone else
    instead of a bare model ID.
    """
    result = dict(registry)
    for provider_id, sources in _sibling_providers().items():
        for source in sources:
            prefix = f"{source}:"
            for key, value in registry.items():
                if not key.startswith(prefix):
                    continue
                target = f"{provider_id}:{key[len(prefix) :]}"
                if target not in result:
                    result[target] = deepcopy(value)
    return result


def _coerce_registry(parsed: Any, source: str) -> ModelRegistry:
    if not isinstance(parsed, dict):
        logger.warning(
            "{} did not parse to a mapping (got {}); ignoring",
            source,
            type(parsed).__name__,
        )
        return {}

    registry: ModelRegistry = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            logger.warning("{}: skipping malformed entry key={!r}", source, key)
            continue
        registry[key.lower()] = value
    return registry


def _load_bundled_registry() -> ModelRegistry:
    resource = files("app.agent.providers").joinpath("model_registry.json")
    raw = resource.read_text(encoding="utf-8")
    return _coerce_registry(json.loads(raw), "model_registry.json")


def _models_dev_cache_path() -> Path:
    return Path(settings.EVOFLUX_CACHE_DIR) / "models-dev.json"


def _read_json_file(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read model registry cache {} ({})", path, exc)
        return None


def _read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("failed to read model registry cache {} ({})", path, exc)
        return None


def _render_models_dev(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"))


def _write_models_dev_cache(cache_path: Path, payload: str) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "failed to write models.dev registry cache {} ({})", cache_path, exc
        )


def _fetch_models_dev() -> Any | None:
    try:
        response = httpx.get(MODELS_DEV_URL, timeout=5.0)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("failed to fetch models.dev registry ({})", exc)
        return None


def _load_models_dev_data() -> Any | None:
    if not settings.EVOFLUX_MODEL_REGISTRY_REFRESH:
        return _read_json_file(_models_dev_cache_path())

    cache_path = _models_dev_cache_path()
    cached = _read_json_file(cache_path)
    if cached is not None:
        try:
            if time.time() - cache_path.stat().st_mtime < MODELS_DEV_CACHE_TTL_SECONDS:
                return cached
        except OSError:
            pass

    fetched = _fetch_models_dev()
    if fetched is None:
        return cached

    _write_models_dev_cache(cache_path, _render_models_dev(fetched))
    return fetched


def refresh_models_dev_cache() -> bool:
    """Re-fetch models.dev past the TTL and report whether the catalog moved.

    ``load_model_registry`` memoizes its merge for the life of the process, so
    the TTL on the disk cache only ever expires between boots: a server left
    running for a month keeps whatever metadata its first registry read saw.
    This is the path that lets it notice a new model without a restart.

    Derived caches are dropped only when the fetched payload differs from the
    cached one — a no-op refresh must not make every reader rebuild the merged
    registry. The cache file is rewritten either way, because its ``mtime`` is
    the TTL clock and leaving it stale makes the next cold start fetch again
    for nothing.

    Blocking: runs one synchronous HTTP request. Call it from a worker thread.
    """
    if not settings.EVOFLUX_MODEL_REGISTRY_REFRESH:
        return False

    fetched = _fetch_models_dev()
    if fetched is None:
        return False

    cache_path = _models_dev_cache_path()
    payload = _render_models_dev(fetched)
    changed = _read_text_file(cache_path) != payload
    _write_models_dev_cache(cache_path, payload)
    if not changed:
        logger.debug("models_dev_cache_current path={}", cache_path)
        return False

    reset_catalog_caches()
    logger.info(
        "models_dev_cache_refreshed providers={}",
        len(fetched) if isinstance(fetched, dict) else 0,
    )
    return True


def _modalities_to_capabilities(model: dict[str, Any]) -> dict[str, Any]:
    modalities = model.get("modalities")
    if not isinstance(modalities, dict):
        return {}

    input_modalities = modalities.get("input") or []
    output_modalities = modalities.get("output") or []
    if not isinstance(input_modalities, list):
        input_modalities = []
    if not isinstance(output_modalities, list):
        output_modalities = []

    capabilities: dict[str, Any] = {}
    input_caps = {
        "vision": "image" in input_modalities,
        "audio": "audio" in input_modalities,
        "video": "video" in input_modalities,
    }
    input_caps = {key: value for key, value in input_caps.items() if value}
    if input_caps:
        capabilities["input"] = input_caps

    output_caps = {
        "text": "text" in output_modalities,
        "image": "image" in output_modalities,
        "audio": "audio" in output_modalities,
        "video": "video" in output_modalities,
    }
    if output_caps["image"] or output_caps["audio"] or output_caps["video"]:
        capabilities["output"] = output_caps
    return capabilities


def _positive(value: Any) -> int | None:
    """An ``int`` that is genuinely a count, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _non_negative(value: Any) -> int | None:
    """An ``int`` that may legitimately be zero (a budget floor), or ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _limits_from_model(model: dict[str, Any]) -> dict[str, int]:
    limit = model.get("limit")
    if not isinstance(limit, dict):
        return {}

    result: dict[str, int] = {}
    for source, target in (
        ("context", "context_length"),
        ("output", "max_completion_tokens"),
        ("input", "max_input_tokens"),
    ):
        value = _positive(limit.get(source))
        if value is not None:
            result[target] = value
    return result


#: Cost fields models.dev quotes as USD per million tokens.
_COST_FIELDS = (
    "input",
    "output",
    "cache_read",
    "cache_write",
    "reasoning",
    "input_audio",
    "output_audio",
)


def _cost_rates(source: Any) -> dict[str, float]:
    if not isinstance(source, dict):
        return {}
    return {
        field: value
        for field in _COST_FIELDS
        if (value := _number(source.get(field))) is not None
    }


def _cost_tier(tier: Any) -> dict[str, Any] | None:
    """One entry of ``cost.tiers`` — a rate that applies past a threshold.

    models.dev states long-context surcharges two ways: the older
    ``context_over_200k`` object and the newer ``tiers`` list. Both mean
    "beyond N context tokens, these rates replace the headline ones", so
    both normalize to the same shape and a caller only has to read one.
    """
    if not isinstance(tier, dict):
        return None
    rates: dict[str, Any] = dict(_cost_rates(tier))
    if not rates:
        return None
    threshold = tier.get("tier")
    size = _positive(threshold.get("size")) if isinstance(threshold, dict) else None
    if size is not None:
        rates["above_tokens"] = size
    return rates


def _cost_from_model(model: dict[str, Any]) -> dict[str, Any]:
    cost = model.get("cost")
    if not isinstance(cost, dict):
        return {}

    result: dict[str, Any] = dict(_cost_rates(cost))

    tiers: list[dict[str, Any]] = []
    raw_tiers = cost.get("tiers")
    if isinstance(raw_tiers, list):
        tiers.extend(entry for item in raw_tiers if (entry := _cost_tier(item)))
    over_200k = cost.get("context_over_200k")
    if isinstance(over_200k, dict):
        entry = _cost_tier({**over_200k, "tier": {"size": 200_000}})
        # Rows carrying both spellings state the same surcharge twice; the
        # older field is only a fallback for rows that have not moved to
        # ``tiers`` yet.
        if entry is not None and not any(
            existing.get("above_tokens") == entry.get("above_tokens")
            for existing in tiers
        ):
            tiers.append(entry)
    if tiers:
        result["tiers"] = tiers
    return result


def _interleaved_field(model: dict[str, Any]) -> str | None:
    """Which streaming field carries this model's reasoning trace.

    ``interleaved: true`` means the model interleaves thinking with tool
    calls but says nothing about the field name; the object form names it
    (``reasoning_content`` on most OpenAI-compatible hosts,
    ``reasoning_details`` on OpenRouter). Only the named form is useful to
    a parser, so the bare ``true`` maps to the OpenAI-compatible default.
    """
    interleaved = model.get("interleaved")
    if interleaved is True:
        return "reasoning_content"
    if isinstance(interleaved, dict):
        field = interleaved.get("field")
        if isinstance(field, str) and field:
            return field
    return None


def _features_from_model(model: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in (
        "tool_call",
        "attachment",
        "temperature",
        "reasoning",
        "structured_output",
        "open_weights",
    ):
        value = model.get(field)
        if isinstance(value, bool):
            result[field] = value

    for field in (
        "status",
        "release_date",
        "last_updated",
        "knowledge",
        "family",
        "name",
        "description",
    ):
        value = model.get(field)
        if isinstance(value, str) and value:
            result[field] = value

    interleaved = _interleaved_field(model)
    if interleaved:
        result["interleaved_field"] = interleaved
    return result


def _modes_from_model(model: dict[str, Any]) -> dict[str, Any]:
    """``experimental.modes`` — alternate service tiers for the same model.

    Each mode names a body/header patch that switches the request onto a
    different tier (OpenAI's ``service_tier: priority``, Anthropic's
    fast-mode beta) along with the rates that tier bills at. EvoFlux keeps
    the patch verbatim: it is the provider's own wire contract, and
    inventing a normalized spelling for it would only add a translation
    that can drift.
    """
    experimental = model.get("experimental")
    if not isinstance(experimental, dict):
        return {}
    modes = experimental.get("modes")
    if not isinstance(modes, dict):
        return {}

    result: dict[str, Any] = {}
    for name, spec in modes.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            continue
        entry: dict[str, Any] = {}
        rates = _cost_rates(spec.get("cost"))
        if rates:
            entry["cost"] = rates
        provider = spec.get("provider")
        if isinstance(provider, dict):
            body = provider.get("body")
            headers = provider.get("headers")
            if isinstance(body, dict) and body:
                entry["body"] = deepcopy(body)
            if isinstance(headers, dict) and headers:
                entry["headers"] = {
                    key: value
                    for key, value in headers.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
        if entry:
            result[name] = entry
    return result


def _wire_from_model(model: dict[str, Any]) -> dict[str, Any]:
    """``model.provider`` — a per-model override of the provider envelope.

    A handful of catalog rows reach a different endpoint or speak a
    different shape than the rest of their provider (Bedrock's Mantle
    surface, Azure's Anthropic passthrough). models.dev states that as
    ``npm``/``api``/``shape`` on the model itself, which is exactly the
    granularity transport resolution needs.
    """
    provider = model.get("provider")
    if not isinstance(provider, dict):
        return {}
    result: dict[str, Any] = {}
    for field in ("npm", "api", "shape"):
        value = provider.get(field)
        if isinstance(value, str) and value:
            result[field] = value
    return result


#: Named levels a purely numeric budget control is presented as.
#:
#: A ``budget_tokens`` control is continuous, but EvoFlux's user-facing knob
#: is a named effort, so the budget range has to be sampled at named points.
#: Three is the set every effort-based endpoint also implements, which keeps
#: one model's ladder comparable to another's.
_BUDGET_LADDER: tuple[str, ...] = ("low", "medium", "high")


def _thinking_from_model(model: dict[str, Any]) -> dict[str, Any] | None:
    """Map models.dev ``reasoning_options`` to EvoFlux's thinking contract.

    models.dev publishes the control as a *list*, because one model often
    exposes several at once — Claude Sonnet 5 takes a named effort *and* an
    off switch, Gemini 2.5 Flash takes a token budget *and* an off switch,
    Qwen 3.8 Max takes all three. Reading only the first entry (as this
    function used to) threw away the off switch and every budget bound.

    The three option types compose like this:

    - ``effort`` — its ``values`` already use EvoFlux's vocabulary
      (minimal/low/medium/high/xhigh/max), so they become the ladder.
    - ``toggle`` — the model reasons by default and can be turned off, so
      ``"none"`` joins the ladder.
    - ``budget_tokens`` — a continuous knob with optional ``min``/``max``.
      With no named efforts alongside it the ladder is sampled at
      :data:`_BUDGET_LADDER`; either way the bounds are recorded, because
      they are what stops a budget being sent outside what the model takes.

    ``control`` names the strongest control present, which is what decides
    the wire dialect: named efforts beat a budget, a budget beats a bare
    toggle.

    Returns ``None`` when models.dev has no opinion (key absent or null),
    so curated data survives the merge. An explicit empty list is an
    assertion of "no reasoning controls" and is returned as such.
    """
    if "reasoning_options" not in model:
        return None
    options = model["reasoning_options"]
    if options is None or not isinstance(options, list):
        return None
    if not options:
        return {"levels": [], "control": "none", "source": "models_dev"}

    efforts: list[str] = []
    has_toggle = False
    has_budget = False
    budget: dict[str, int] = {}
    for option in options:
        if not isinstance(option, dict):
            continue
        match option.get("type"):
            case "effort":
                values = option.get("values")
                if isinstance(values, list):
                    efforts.extend(item for item in values if isinstance(item, str))
            case "toggle":
                has_toggle = True
            case "budget_tokens":
                has_budget = True
                for bound in ("min", "max"):
                    value = _non_negative(option.get(bound))
                    if value is not None:
                        budget[bound] = value

    if not (efforts or has_toggle or has_budget):
        return None

    ladder = efforts or (_BUDGET_LADDER if has_budget else ())
    can_disable = has_toggle or "none" in efforts or budget.get("min") == 0
    levels = (["none"] if can_disable else []) + [
        level for level in ladder if level != "none"
    ]

    control = "effort" if efforts else "budget" if has_budget else "toggle"
    entry: dict[str, Any] = {
        "levels": list(dict.fromkeys(levels)),
        "control": control,
        "source": "models_dev",
    }
    if has_budget:
        entry["budget"] = budget
    return entry


def _normalize_models_dev(data: Any, *, include_plugins: bool = True) -> ModelRegistry:
    if not isinstance(data, dict):
        return {}

    registry: ModelRegistry = {}
    provider_aliases = _provider_id_aliases(include_plugins=include_plugins)
    for provider_key, provider in data.items():
        if not isinstance(provider_key, str) or not isinstance(provider, dict):
            continue
        provider_id = str(provider.get("id") or provider_key).lower()
        provider_id = provider_aliases.get(provider_id, provider_id)
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model_key, model in models.items():
            if not isinstance(model_key, str) or not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or model_key)
            entry: dict[str, Any] = {}
            thinking = _thinking_from_model(model)
            for field, value in (
                ("capabilities", _modalities_to_capabilities(model)),
                ("limits", _limits_from_model(model)),
                ("cost", _cost_from_model(model)),
                ("features", _features_from_model(model)),
                ("modes", _modes_from_model(model)),
                ("wire", _wire_from_model(model)),
            ):
                if value:
                    entry[field] = value
            if thinking is not None:
                entry["thinking"] = thinking
            if entry:
                registry[f"{provider_id}:{model_id}".lower()] = entry
    return registry


def _load_user_overlay() -> ModelRegistry:
    path = Path(settings.EVOFLUX_CONFIG_DIR) / "model_registry.yaml"
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("failed to read model registry overlay {} ({})", path, exc)
        return {}
    return _coerce_registry(parsed, str(path))


@lru_cache(maxsize=1)
def load_model_registry() -> ModelRegistry:
    """Load bundled, models.dev, and user model metadata in precedence order."""
    registry = _load_bundled_registry()
    bundled_count = len(registry)
    models_dev = _normalize_models_dev(_load_models_dev_data())
    overlay = _load_user_overlay()

    for key, value in models_dev.items():
        registry[key] = _deep_merge(registry.get(key, {}), value)

    # Source-provider overrides must participate in alias generation (for
    # example an OpenAI limit override inherited by Codex).
    for key, value in overlay.items():
        registry[key] = _deep_merge(registry.get(key, {}), value)
    registry = apply_model_registry_aliases(registry, overwrite=True)
    # Vendors that publish plan and regional variants as separate catalog
    # rows: fill only the gaps, so a user pointed at a plan endpoint still
    # gets real metadata for the models only that endpoint lists.
    registry = apply_sibling_model_aliases(registry)

    # Reapply target-provider overrides after aliases so an explicit
    # ``codex:model`` row remains the highest-precedence static source.
    for key, value in overlay.items():
        registry[key] = _deep_merge(registry.get(key, {}), value)

    logger.debug(
        "model registry loaded bundled={} models_dev={} overlay={} final={}",
        bundled_count,
        len(models_dev),
        len(overlay),
        len(registry),
    )
    return registry


#: Provider-envelope fields worth bundling. The model list is deliberately
#: excluded: per-model metadata already ships flattened in
#: ``model_registry.json`` and duplicating it here would double the payload.
PROVIDER_ENVELOPE_FIELDS = ("id", "name", "env", "npm", "api", "doc")


def provider_envelopes(data: Any) -> dict[str, dict[str, Any]]:
    """Extract the provider-level rows from a models.dev payload."""
    if not isinstance(data, dict):
        return {}
    providers: dict[str, dict[str, Any]] = {}
    for provider_key, provider in data.items():
        if not isinstance(provider_key, str) or not isinstance(provider, dict):
            continue
        provider_id = str(provider.get("id") or provider_key).lower()
        envelope = {
            field: deepcopy(provider[field])
            for field in PROVIDER_ENVELOPE_FIELDS
            if field in provider
        }
        envelope["id"] = provider_id
        providers[provider_id] = envelope
    return providers


@lru_cache(maxsize=1)
def _bundled_provider_envelopes() -> dict[str, dict[str, Any]]:
    """Provider envelopes shipped with the package, for offline cold starts."""
    try:
        resource = files("app.agent.providers").joinpath("provider_catalog.json")
        parsed = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read bundled provider catalog ({})", exc)
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        key.lower(): value
        for key, value in parsed.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


@lru_cache(maxsize=1)
def _models_dev_providers() -> dict[str, dict[str, Any]]:
    """Provider-level rows from models.dev, keyed by catalog provider ID.

    ``load_model_registry`` flattens the catalog down to ``provider:model``
    metadata and drops the provider envelope. Provider resolution needs the
    envelope instead: ``npm`` (which wire protocol), ``api`` (the endpoint)
    and ``env`` (the credential names). Keeping this as a separate view
    avoids reshaping the metadata registry that everything else reads.

    The bundled envelopes underlie the fetched ones so that an install which
    has never reached the network still resolves every provider EvoFlux
    ships support for. Providers that only the live catalog knows about —
    the long tail beyond the curated set — appear once it has been fetched.
    """
    providers = dict(_bundled_provider_envelopes())
    for provider_id, envelope in provider_envelopes(_load_models_dev_data()).items():
        providers[provider_id] = envelope
    return providers


def models_dev_provider_entry(provider_id: str) -> dict[str, Any] | None:
    """Return one models.dev provider envelope, or ``None`` when unknown."""
    normalized = (provider_id or "").strip().lower()
    if not normalized:
        return None
    return _models_dev_providers().get(normalized)


def all_provider_envelopes() -> dict[str, dict[str, Any]]:
    """Every provider envelope EvoFlux knows about, keyed by catalog ID.

    Bundled rows underlie fetched ones, so this answers the same on a cold
    offline install as on a warm one — which is what lets the settings UI
    list the whole catalog rather than only the providers with hand-written
    support.
    """
    return dict(_models_dev_providers())


@lru_cache(maxsize=1)
def provider_model_counts() -> dict[str, tuple[int, int]]:
    """Per provider: how many models are known, and how many cost nothing.

    "Free" means zero per-token cost — a genuinely free tier, or a model
    included in a subscription plan. Either way the next token costs
    nothing, which is the distinction a user picking a provider cares about.

    Counted from the merged registry rather than the provider envelopes,
    because the envelopes deliberately carry no model list. On a cold
    offline install that means the long tail reports nothing until the
    catalog has been fetched once, which is the honest answer rather than a
    number invented from a stale bundle.
    """
    counts: dict[str, list[int]] = {}
    for key, entry in load_model_registry().items():
        provider_id, _, _model = key.partition(":")
        if not provider_id:
            continue
        bucket = counts.setdefault(provider_id, [0, 0])
        bucket[0] += 1
        cost = entry.get("cost")
        if (
            isinstance(cost, dict)
            and cost.get("input") == 0
            and cost.get("output") == 0
        ):
            bucket[1] += 1
    return {key: (value[0], value[1]) for key, value in counts.items()}


def reset_catalog_caches() -> None:
    """Drop every cache derived from the model catalog.

    The catalog feeds a chain of process-wide caches: the merged model
    registry, the provider envelopes, the per-provider model counts, and the
    settings-UI rows the provider catalog derives from all of those. They
    have to be invalidated together — clearing only the first leaves the
    others answering from data that no longer exists, which is subtle enough
    to look like a bug in whatever reads them next.

    Called when the catalog is refreshed, and by tests that stub it.
    """
    from app.agent.providers import capabilities, model_metadata
    from app.agent.providers.catalog import builtin_providers, catalog_providers

    load_model_registry.cache_clear()
    _models_dev_providers.cache_clear()
    _bundled_provider_envelopes.cache_clear()
    provider_model_counts.cache_clear()
    builtin_providers.cache_clear()
    catalog_providers.cache_clear()
    capabilities._registry.cache_clear()
    model_metadata._registry.cache_clear()
