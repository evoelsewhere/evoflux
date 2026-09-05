"""Live model metadata for the ChatGPT Codex endpoint.

The Codex subscription endpoint serves a different context window than the
same model family does on the public API — models.dev describes the latter.
Believing models.dev here sets the compaction threshold above what the
endpoint will actually accept, so a long session is rejected before
compaction ever fires. The endpoint publishes its own limits; this module
reads them from there and offers them to the shared registry as an overlay.

Nothing here is hardcoded: the numbers come from the endpoint, cached on
disk with a TTL. The registry load path only ever reads that cache — no
network and no OAuth happen while metadata is being resolved.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from app.agent.providers.codex.oauth import CODEX_ORIGINATOR, CodexOAuth
from app.core.config import settings

CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
CODEX_MODELS_CACHE_TTL_SECONDS = 60 * 60
#: Used when the endpoint lists a model without its own percentage.
CODEX_EFFECTIVE_CONTEXT_WINDOW_PERCENT = 95

_CACHED_MODEL_FIELDS = (
    "slug",
    "context_window",
    "max_context_window",
    "effective_context_window_percent",
    "auto_compact_token_limit",
    "supports_reasoning_summary_parameter",
)


def _cache_path() -> Path:
    return Path(settings.EVOFLUX_CACHE_DIR) / "codex_models.json"


def _read_cache(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("codex_catalog_cache_unreadable path={} error={}", path, exc)
        return None


def _fetch_catalog() -> Any | None:
    oauth = CodexOAuth.load()
    if oauth is None:
        return None
    try:
        if oauth.is_expired():
            oauth = oauth.refresh()
        headers = {
            "Authorization": f"Bearer {oauth.access_token.get_secret_value()}",
            "Content-Type": "application/json",
            "User-Agent": "EvoFlux/1.0.0",
            "originator": CODEX_ORIGINATOR,
        }
        if oauth.account_id:
            headers["ChatGPT-Account-Id"] = oauth.account_id
        response = httpx.get(
            CODEX_MODELS_URL,
            params={"client_version": "1.0.0"},
            headers=headers,
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        # Metadata is a nicety; a failure here must never stop a run.
        logger.warning("codex_catalog_fetch_failed error={}", type(exc).__name__)
        return None


def _cacheable_catalog(data: Any) -> dict[str, list[dict[str, Any]]]:
    """Keep only the fields used for discovery and limit resolution."""
    items = data.get("models", []) if isinstance(data, dict) else []
    return {
        "models": [
            {field: item[field] for field in _CACHED_MODEL_FIELDS if field in item}
            for item in items
            if isinstance(item, dict) and isinstance(item.get("slug"), str)
        ]
    }


def cached_codex_catalog() -> Any | None:
    """Return cached catalog data, doing no network or OAuth work."""
    return _read_cache(_cache_path())


def load_codex_catalog(*, force: bool = False) -> Any | None:
    """Return cached or freshly fetched catalog data."""
    cache_path = _cache_path()
    cached = cached_codex_catalog()
    if not settings.EVOFLUX_MODEL_REGISTRY_REFRESH:
        return cached
    if cached is not None and not force:
        try:
            age = time.time() - cache_path.stat().st_mtime
            if age < CODEX_MODELS_CACHE_TTL_SECONDS:
                return cached
        except OSError:
            pass

    fetched = _fetch_catalog()
    if fetched is None:
        return cached
    payload = _cacheable_catalog(fetched)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning(
            "codex_catalog_cache_unwritable path={} error={}", cache_path, exc
        )
    return payload


def supports_reasoning_summary(data: Any, model: str) -> bool | None:
    """Whether *model* accepts a reasoning summary parameter, if known."""
    items = data.get("models", []) if isinstance(data, dict) else []
    for item in items:
        if isinstance(item, dict) and item.get("slug") == model:
            supported = item.get("supports_reasoning_summary_parameter")
            return supported if isinstance(supported, bool) else None
    return None


def model_registry_overlay(data: Any) -> dict[str, dict[str, Any]]:
    """Turn catalog rows into registry entries keyed ``codex:<slug>``."""
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return {}

    registry: dict[str, dict[str, Any]] = {}
    for model in data["models"]:
        if not isinstance(model, dict):
            continue
        slug = model.get("slug")
        # ``context_window`` is the window a session actually gets;
        # ``max_context_window`` is the ceiling the plan could offer. Taking
        # the ceiling would put the compaction threshold above what the
        # endpoint accepts today — the exact failure this overlay exists to
        # prevent — so the effective window wins and the ceiling is only a
        # fallback for rows that omit it.
        context = model.get("context_window")
        if context is None:
            context = model.get("max_context_window")
        percent = model.get("effective_context_window_percent")
        if percent is None:
            percent = CODEX_EFFECTIVE_CONTEXT_WINDOW_PERCENT
        if (
            not isinstance(slug, str)
            or not slug
            or isinstance(context, bool)
            or not isinstance(context, int)
            or context <= 0
            or isinstance(percent, bool)
            or not isinstance(percent, int)
            or not 1 <= percent <= 100
        ):
            continue
        registry[f"codex:{slug}".lower()] = {
            "limits": {
                "context_length": context,
                "max_input_tokens": context * percent // 100,
            }
        }
    return registry


__all__ = [
    "cached_codex_catalog",
    "load_codex_catalog",
    "model_registry_overlay",
    "supports_reasoning_summary",
]
