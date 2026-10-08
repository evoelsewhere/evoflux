"""Tests for app/agent/providers/opencode/usage.py (OpenCode Go usage)."""

from __future__ import annotations

import pytest

from app.agent.providers.opencode import usage
from app.services import provider_usage

PAYLOAD = {
    "usage": {
        "rolling": {
            "status": "ok",
            "percent": 12.5,
            "resetsAt": "2026-10-07T20:49:51.000Z",
        },
        "weekly": {
            "status": "ok",
            "percent": 40,
            "resetsAt": "2026-10-12T00:00:00.000Z",
        },
        "monthly": {
            "status": "ok",
            "percent": 0,
            "resetsAt": "2026-11-07T15:34:33.000Z",
        },
    }
}


class _FakeResponse:
    def __init__(self, payload: object):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _FakeClient:
    payload: object = PAYLOAD
    captured: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, *, headers):  # type: ignore[no-untyped-def]
        type(self).captured = {"url": url, "headers": headers}
        return _FakeResponse(self.payload)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
    monkeypatch.delenv("OPENCODE_GO_BASE_URL", raising=False)
    monkeypatch.setattr(usage.httpx, "AsyncClient", _FakeClient)
    _FakeClient.payload = PAYLOAD


@pytest.mark.asyncio
async def test_get_usage_maps_three_windows() -> None:
    result = await usage.get_usage()

    assert result.provider == "opencode-go"
    assert [limit.limit_id for limit in result.limits] == [
        "rolling",
        "weekly",
        "monthly",
    ]
    rolling, weekly, monthly = (limit.primary for limit in result.limits)
    assert rolling is not None and weekly is not None and monthly is not None
    assert (rolling.used_percent, rolling.window_minutes) == (12.5, 300)
    assert (weekly.used_percent, weekly.window_minutes) == (40.0, 10080)
    assert (monthly.used_percent, monthly.window_minutes) == (0.0, 43200)
    assert rolling.resets_at == 1791406191
    assert result.limits[0].plan_type == "go"
    assert result.limits[0].rate_limit_reached_type is None


@pytest.mark.asyncio
async def test_get_usage_calls_go_endpoint_with_bearer_key() -> None:
    await usage.get_usage()

    assert _FakeClient.captured["url"] == "https://opencode.ai/zen/go/v1/usage"
    headers = _FakeClient.captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer go-key"
    assert headers["User-Agent"].startswith("EvoFlux/")


@pytest.mark.asyncio
async def test_get_usage_honours_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_GO_BASE_URL", "https://proxy.example/go/v1/")

    await usage.get_usage()

    assert _FakeClient.captured["url"] == "https://proxy.example/go/v1/usage"


@pytest.mark.asyncio
async def test_zen_key_is_not_used_for_go_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENCODE_GO_API_KEY")
    monkeypatch.setenv("OPENCODE_API_KEY", "zen-key")
    from app.core.config import settings

    if getattr(settings, "OPENCODE_GO_API_KEY", None):
        pytest.skip("OPENCODE_GO_API_KEY configured through settings")

    with pytest.raises(usage.OpenCodeUsageCredentialsError):
        await usage.get_usage()


@pytest.mark.asyncio
async def test_full_window_is_reported_as_limit_reached() -> None:
    _FakeClient.payload = {
        "usage": {
            "rolling": {"status": "ok", "percent": 10, "resetsAt": None},
            "weekly": {"status": "ok", "percent": 100, "resetsAt": None},
        }
    }

    result = await usage.get_usage()

    assert result.limits[0].rate_limit_reached_type == "weekly"


@pytest.mark.asyncio
async def test_unknown_status_is_treated_as_limit_reached() -> None:
    _FakeClient.payload = {
        "usage": {"rolling": {"status": "rate-limited", "percent": 20}}
    }

    result = await usage.get_usage()

    assert result.limits[0].rate_limit_reached_type == "rolling"


@pytest.mark.asyncio
async def test_missing_or_malformed_windows_are_skipped() -> None:
    _FakeClient.payload = {
        "usage": {
            "rolling": {"status": "ok", "percent": "n/a"},
            "weekly": "oops",
            "monthly": {"status": "ok", "percent": 250, "resetsAt": "not-a-date"},
        }
    }

    result = await usage.get_usage()

    assert [limit.limit_id for limit in result.limits] == ["monthly"]
    monthly = result.limits[0].primary
    assert monthly is not None
    assert monthly.used_percent == 100.0
    assert monthly.resets_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"usage": []}, {"usage": {}}])
async def test_unusable_payload_is_unavailable(payload: object) -> None:
    _FakeClient.payload = payload

    with pytest.raises(usage.OpenCodeUsageUnavailableError):
        await usage.get_usage()


@pytest.mark.asyncio
async def test_dispatcher_routes_opencode_go_and_translates_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await provider_usage.get_provider_usage("opencode-go")
    assert result.provider == "opencode-go"

    monkeypatch.delenv("OPENCODE_GO_API_KEY")
    from app.core.config import settings

    if getattr(settings, "OPENCODE_GO_API_KEY", None):
        pytest.skip("OPENCODE_GO_API_KEY configured through settings")
    with pytest.raises(provider_usage.ProviderUsageCredentialsError):
        await provider_usage.get_provider_usage("opencode-go")


@pytest.mark.asyncio
async def test_dispatcher_translates_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeClient.payload = {}

    with pytest.raises(provider_usage.ProviderUsageUnavailableError):
        await provider_usage.get_provider_usage("opencode-go")


@pytest.mark.asyncio
async def test_zen_usage_stays_unsupported() -> None:
    with pytest.raises(provider_usage.ProviderUsageUnsupportedError):
        await provider_usage.get_provider_usage("opencode")
