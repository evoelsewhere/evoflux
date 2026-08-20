"""OpenAI Codex usage snapshot support."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

import httpx
from loguru import logger

from app.api.schemas.settings import (
    ProviderUsageCredits,
    ProviderUsageLimit,
    ProviderUsageResponse,
    ProviderUsageWindow,
)


class CodexUsageCredentialsError(ValueError):
    """Raised when Codex OAuth credentials are missing."""


class CodexUsageUnavailableError(RuntimeError):
    """Raised when the upstream usage endpoint cannot be reached or parsed."""


def _first(values: dict[str, object], *names: str) -> object | None:
    for name in names:
        if name in values:
            return values[name]
    return None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number_text(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    rendered = format(parsed, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _difference(total: str | None, value: str | None) -> str | None:
    if total is None or value is None:
        return None
    try:
        result = Decimal(total) - Decimal(value)
    except InvalidOperation:
        return None
    if result < 0:
        return None
    return _number_text(result)


def _usage_window(data: object) -> ProviderUsageWindow | None:
    if not isinstance(data, dict):
        return None
    values = cast("dict[str, object]", data)
    used = _first(values, "used_percent", "usedPercent")
    if isinstance(used, bool) or not isinstance(used, int | float):
        return None
    direct_minutes = _first(values, "window_minutes", "windowDurationMins")
    seconds = _first(values, "limit_window_seconds", "limitWindowSeconds")
    if isinstance(direct_minutes, int) and not isinstance(direct_minutes, bool):
        minutes = direct_minutes if direct_minutes > 0 else None
    else:
        minutes = (
            (seconds + 59) // 60
            if isinstance(seconds, int)
            and not isinstance(seconds, bool)
            and seconds > 0
            else None
        )
    reset_at = _first(values, "reset_at", "resets_at", "resetsAt")
    return ProviderUsageWindow(
        used_percent=float(used),
        window_minutes=minutes,
        resets_at=(
            reset_at
            if isinstance(reset_at, int) and not isinstance(reset_at, bool)
            else None
        ),
    )


def _usage_credits(data: object) -> ProviderUsageCredits | None:
    if not isinstance(data, dict):
        return None
    values = cast("dict[str, object]", data)
    raw_has_credits = _first(values, "has_credits", "hasCredits")
    raw_unlimited = values.get("unlimited")
    raw_balance = _first(
        values, "balance", "remaining", "remaining_credits", "remainingCredits"
    )
    balance = _number_text(raw_balance) or _text(raw_balance)
    used = _number_text(
        _first(values, "used", "used_credits", "usedCredits", "credits_used")
    )
    total = _number_text(
        _first(
            values,
            "total",
            "total_credits",
            "totalCredits",
            "credit_limit",
            "creditLimit",
            "monthly_limit",
            "monthlyLimit",
        )
    )
    if used is None:
        used = _difference(total, balance)
    if balance is None:
        balance = _difference(total, used)
    if (
        not isinstance(raw_has_credits, bool)
        and not isinstance(raw_unlimited, bool)
        and balance is None
        and used is None
        and total is None
    ):
        return None
    unlimited = raw_unlimited if isinstance(raw_unlimited, bool) else False
    has_credits = (
        raw_has_credits
        if isinstance(raw_has_credits, bool)
        else unlimited or balance is not None or used is not None or total is not None
    )
    return ProviderUsageCredits(
        has_credits=has_credits,
        unlimited=unlimited,
        balance=balance,
        used=used,
        total=total,
    )


def _usage_limit(
    data: object,
    *,
    limit_id: str | None = None,
    limit_name: str | None = None,
    plan_type: str | None = None,
    rate_limit_reached_type: str | None = None,
) -> ProviderUsageLimit | None:
    if not isinstance(data, dict):
        return None
    values = cast("dict[str, object]", data)
    raw_rate_limit = _first(values, "rate_limit", "rateLimit")
    rate_limit_values = (
        cast("dict[str, object]", raw_rate_limit)
        if isinstance(raw_rate_limit, dict)
        else values
    )
    primary = _usage_window(_first(rate_limit_values, "primary_window", "primary"))
    secondary = _usage_window(
        _first(rate_limit_values, "secondary_window", "secondary")
    )
    credits = _usage_credits(values.get("credits"))
    if primary is None and secondary is None and credits is None:
        return None
    return ProviderUsageLimit(
        limit_id=limit_id
        or _text(_first(values, "limit_id", "limitId", "metered_feature")),
        limit_name=limit_name or _text(_first(values, "limit_name", "limitName")),
        primary=primary,
        secondary=secondary,
        credits=credits,
        plan_type=plan_type or _text(_first(values, "plan_type", "planType")),
        rate_limit_reached_type=rate_limit_reached_type
        or _rate_limit_reached_type(
            _first(values, "rate_limit_reached_type", "rateLimitReachedType")
        ),
    )


def _rate_limit_reached_type(value: object) -> str | None:
    if isinstance(value, dict):
        values = cast("dict[str, object]", value)
        return _text(values.get("type"))
    return _text(value)


def _official_limits(values: dict[str, object]) -> list[ProviderUsageLimit]:
    by_id = values.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        rows = cast("dict[str, object]", by_id)
        ordered_ids = sorted(rows, key=lambda value: (value != "codex", value))
        limits = [
            limit
            for limit_id in ordered_ids
            if (limit := _usage_limit(rows[limit_id], limit_id=limit_id)) is not None
        ]
        if limits:
            return limits

    primary = values.get("rateLimits")
    if isinstance(primary, dict):
        limit = _usage_limit(primary)
        if limit is not None:
            return [limit]
    return []


def _spend_control_limit(
    values: dict[str, object],
    *,
    plan_type: str | None,
) -> ProviderUsageLimit | None:
    spend_control = _first(values, "spend_control", "spendControl")
    if not isinstance(spend_control, dict):
        return None
    spend_values = cast("dict[str, object]", spend_control)
    individual = _first(spend_values, "individual_limit", "individualLimit")
    if not isinstance(individual, dict):
        return None
    limit_values = cast("dict[str, object]", individual)
    total = _number_text(_first(limit_values, "limit", "total"))
    used = _number_text(limit_values.get("used"))
    remaining = _number_text(limit_values.get("remaining"))
    raw_percent = _first(limit_values, "used_percent", "usedPercent")
    if isinstance(raw_percent, bool) or not isinstance(raw_percent, int | float):
        if total is None or used is None or Decimal(total) <= 0:
            return None
        used_percent = float(Decimal(used) / Decimal(total) * 100)
    else:
        used_percent = float(raw_percent)
    reset_at = _first(limit_values, "reset_at", "resetsAt")
    credits = _usage_credits(
        {
            "has_credits": remaining is None or Decimal(remaining) > 0,
            "unlimited": False,
            "balance": remaining,
            "used": used,
            "total": total,
        }
    )
    return ProviderUsageLimit(
        limit_id="codex_monthly_usage",
        limit_name="Monthly usage",
        primary=ProviderUsageWindow(
            used_percent=used_percent,
            window_minutes=30 * 24 * 60,
            resets_at=(
                reset_at
                if isinstance(reset_at, int) and not isinstance(reset_at, bool)
                else None
            ),
        ),
        credits=credits,
        plan_type=plan_type,
        rate_limit_reached_type=_rate_limit_reached_type(
            _first(values, "rate_limit_reached_type", "rateLimitReachedType")
        ),
    )


def _parse_usage_payload(payload: dict[str, object]) -> ProviderUsageResponse:
    result = payload.get("result")
    values = cast("dict[str, object]", result) if isinstance(result, dict) else payload
    official = _official_limits(values)
    if official:
        return ProviderUsageResponse(provider="codex", limits=official)

    common_plan = _text(_first(values, "plan_type", "planType"))
    reached_type = _rate_limit_reached_type(
        _first(values, "rate_limit_reached_type", "rateLimitReachedType")
    )
    limits: list[ProviderUsageLimit] = []
    spend_limit = _spend_control_limit(values, plan_type=common_plan)
    if spend_limit is not None:
        limits.append(spend_limit)
    else:
        primary = _usage_limit(
            values,
            limit_id="codex",
            plan_type=common_plan,
            rate_limit_reached_type=reached_type,
        )
        if primary is not None:
            limits.append(primary)
    additional = _first(values, "additional_rate_limits", "additionalRateLimits")
    if isinstance(additional, list):
        for item in additional:
            if not isinstance(item, dict):
                continue
            item_values = cast("dict[str, object]", item)
            limit = _usage_limit(item_values, plan_type=common_plan)
            if limit is not None:
                limits.append(limit)
    return ProviderUsageResponse(provider="codex", limits=limits)


def _usage_headers() -> dict[str, str]:
    from app.agent.providers.codex.oauth import CodexOAuth

    oauth = CodexOAuth.load()
    if oauth is None:
        raise CodexUsageCredentialsError("Codex OAuth credentials not found.")
    if oauth.is_expired():
        oauth = oauth.refresh()
    headers = {
        "Authorization": f"Bearer {oauth.access_token.get_secret_value()}",
        "Accept": "application/json",
        "User-Agent": "EvoFlux/1.0.0",
        "originator": "EvoFlux",
    }
    if oauth.account_id:
        headers["ChatGPT-Account-Id"] = oauth.account_id
    return headers


async def get_usage() -> ProviderUsageResponse:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://chatgpt.com/backend-api/wham/usage",
                headers=_usage_headers(),
            )
            response.raise_for_status()
        payload = response.json()
    except CodexUsageCredentialsError:
        raise
    except Exception as exc:
        logger.info("provider_usage_unavailable provider=codex error={}", exc)
        raise CodexUsageUnavailableError("Provider usage unavailable.") from exc

    if not isinstance(payload, dict):
        raise CodexUsageUnavailableError("Provider usage response was invalid.")

    return _parse_usage_payload(cast("dict[str, object]", payload))
