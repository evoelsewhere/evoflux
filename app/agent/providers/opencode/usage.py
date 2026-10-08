"""OpenCode Go usage snapshot support.

Go meters each subscription in three windows — a rolling 5-hour window, a
weekly one and a monthly one — and the console shows each as a percentage
with a reset time. The same numbers are served to the subscription's own API
key at ``GET {go base}/usage``::

    {"usage": {"rolling": {"status": "ok", "percent": 0,
                           "resetsAt": "2026-10-07T20:49:51.000Z"},
               "weekly":  {...}, "monthly": {...}}}

Only percentages and reset times are published — not dollars spent — so each
window maps onto :class:`ProviderUsageWindow` as-is. Zen has no equivalent
endpoint (its balance lives in the console only), so this is Go-only.

The endpoint is not part of OpenCode's documented API, so every field is read
defensively: an unknown ``status`` or a missing window degrades the panel
rather than breaking it.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import cast

import httpx
from loguru import logger

from app.api.schemas.settings import (
    ProviderUsageLimit,
    ProviderUsageResponse,
    ProviderUsageWindow,
)
from app.core.version import VERSION

PROVIDER_ID = "opencode-go"
ENV_VAR = "OPENCODE_GO_API_KEY"

#: Response key → (label, window length in minutes). The lengths are what the
#: UI keys its "5h window / Weekly / Monthly" wording on.
_WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("rolling", "Rolling", 5 * 60),
    ("weekly", "Weekly", 7 * 24 * 60),
    ("monthly", "Monthly", 30 * 24 * 60),
)


class OpenCodeUsageCredentialsError(ValueError):
    """Raised when no OpenCode Go key is configured."""


class OpenCodeUsageUnavailableError(RuntimeError):
    """Raised when the usage endpoint cannot be reached or parsed."""


def _api_key() -> str:
    value = os.getenv(ENV_VAR, "").strip()
    if not value:
        from app.core.config import settings

        secret = getattr(settings, ENV_VAR, None)
        value = (
            secret.get_secret_value()
            if hasattr(secret, "get_secret_value")
            else str(secret or "")
        ).strip()
    if not value:
        raise OpenCodeUsageCredentialsError("OpenCode Go API key not found.")
    return value


def _usage_url() -> str:
    from app.agent.providers.registry import resolve_base_url, resolve_provider

    config = resolve_provider(PROVIDER_ID)
    base = resolve_base_url(config) if config is not None else ""
    if not base:
        raise OpenCodeUsageUnavailableError("OpenCode Go endpoint is not known.")
    return f"{base.rstrip('/')}/usage"


def _parse_timestamp(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _percent(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return max(0.0, min(100.0, float(value)))


def _is_exhausted(status: object, percent: float) -> bool:
    """A window blocks requests when full, or when the gateway says it is not ok."""
    return percent >= 100.0 or (isinstance(status, str) and status != "ok")


def parse_usage(payload: object) -> ProviderUsageResponse:
    """Map the endpoint's ``usage`` object onto the shared usage schema."""
    if not isinstance(payload, dict):
        raise OpenCodeUsageUnavailableError("Provider usage response was invalid.")
    usage = cast("dict[str, object]", payload).get("usage")
    if not isinstance(usage, dict):
        raise OpenCodeUsageUnavailableError("Provider usage response was invalid.")
    windows = cast("dict[str, object]", usage)

    limits: list[ProviderUsageLimit] = []
    exhausted: list[str] = []
    for key, label, minutes in _WINDOWS:
        raw = windows.get(key)
        if not isinstance(raw, dict):
            continue
        item = cast("dict[str, object]", raw)
        percent = _percent(item.get("percent"))
        if percent is None:
            continue
        if _is_exhausted(item.get("status"), percent):
            exhausted.append(key)
        limits.append(
            ProviderUsageLimit(
                limit_id=key,
                limit_name="Go",
                primary=ProviderUsageWindow(
                    used_percent=percent,
                    window_minutes=minutes,
                    resets_at=_parse_timestamp(item.get("resetsAt")),
                ),
                plan_type="go",
            )
        )
    if not limits:
        raise OpenCodeUsageUnavailableError("Provider usage response had no windows.")
    if exhausted:
        # The panel reads the reached-limit notice off the first row.
        limits[0] = limits[0].model_copy(
            update={"rate_limit_reached_type": exhausted[0]}
        )
    return ProviderUsageResponse(provider=PROVIDER_ID, limits=limits)


async def get_usage() -> ProviderUsageResponse:
    key = _api_key()
    url = _usage_url()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                    "User-Agent": f"EvoFlux/{VERSION}",
                },
            )
            response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        # Never log the exception text for HTTP errors verbatim beyond the
        # status: httpx messages carry the URL, not the key, but stay terse.
        logger.info("provider_usage_unavailable provider={} error={}", PROVIDER_ID, exc)
        raise OpenCodeUsageUnavailableError("Provider usage unavailable.") from exc
    return parse_usage(payload)
