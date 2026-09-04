"""Per-request wire fields that are neither the prompt nor a sampling knob.

Two kinds of fact live here, both of which every transport needs and none of
which belongs in a provider subclass:

1. **Static provider headers.** Attribution for aggregating gateways, and
   protocol pins. MiMo-Code sends the same class of header to OpenRouter,
   Vercel and NVIDIA; without it a client is invisible to the gateway's own
   analytics and, on OpenRouter, forfeits app-level attribution.
2. **Alternate service tiers.** The same model served differently —
   ``service_tier: priority``, Anthropic's fast-mode beta, Codex's
   subscription fast lane — each selected by a small body patch and
   sometimes a header, each billing at its own rate.

Distinct from :mod:`app.agent.providers.thinking`, which answers "the caller
asked for effort X, how do I say that here?". Reasoning defaults that belong
on every request (Gemini's ``includeThoughts``, the Responses API's
``summary``) live there too, next to the dialect that needs them.
"""

from __future__ import annotations

from typing import Any

from app.agent.providers.registry import (
    request_headers,
    resolve_provider,
)


def provider_request_headers(provider_id: str) -> dict[str, str]:
    """Static headers every request to this provider should carry.

    Attribution for gateways that rank or bill by referrer, plus any
    always-on protocol pin. Empty for a provider that needs neither, which
    is most of them.
    """
    config = resolve_provider((provider_id or "").strip().lower())
    return request_headers(config) if config is not None else {}


def service_tier_fields(
    provider_id: str,
    model: str,
    tier: object,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Wire fields that select an alternate service tier, and its headers.

    A tier is a *different way to be served the same model* — OpenAI's
    ``service_tier: priority``, Anthropic's fast-mode beta, Codex's
    subscription fast lane. Each is selected by a small body patch, some
    also by a header, and each bills at its own rate.

    Those patches are the provider's own wire contract, so they are carried
    verbatim from the catalog rather than re-spelled here: nothing in this
    function knows what ``speed`` or ``service_tier`` mean, only where to
    put them. That is what lets a tier EvoFlux has never seen work as soon
    as the catalog lists it.

    Returns ``({}, {})`` when the caller asked for nothing, or when this
    model has no such tier — asking for a tier a model does not offer must
    not put an unknown field on the wire.

    Args:
        provider_id: EvoFlux provider ID.
        model: Provider-side model ID.
        tier: The tier name the caller asked for, in any spelling.
    """
    if not isinstance(tier, str) or not tier.strip():
        return {}, {}

    from app.agent.providers.model_metadata import get_model_mode, qualified_model_id

    patch = get_model_mode(qualified_model_id(provider_id, model), tier.strip().lower())
    if not patch:
        return {}, {}

    body = patch.get("body")
    headers = patch.get("headers")
    return (
        dict(body) if isinstance(body, dict) else {},
        {
            key: value
            for key, value in headers.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if isinstance(headers, dict)
        else {},
    )


__all__ = [
    "provider_request_headers",
    "service_tier_fields",
]
