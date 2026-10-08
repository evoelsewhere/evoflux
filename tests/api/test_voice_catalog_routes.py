from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import httpx
from fastapi import HTTPException

from app.api.routes import voice
from app.core.runtime_settings import (
    VoiceSttProviderSettings,
    VoiceSttSettings,
)


def _run_immediate(coroutine):
    try:
        awaited = coroutine.send(None)
    except StopIteration as result:
        return result.value
    while True:
        try:
            value = awaited.send(None)
        except StopIteration as result:
            value = result.value
        try:
            awaited = coroutine.send(value)
        except StopIteration as result:
            return result.value


def test_openai_compatible_model_catalog_route_is_registered() -> None:
    assert any(
        route.path == "/providers/{provider_id}/models"
        and "GET" in route.methods
        for route in voice.router.routes
    )


def test_model_catalog_extracts_unique_nonempty_model_ids() -> None:
    assert voice._extract_model_ids(
        {
            "data": [
                {"id": "whisper-large-v3"},
                {"id": "whisper-large-v3-turbo"},
                {"id": "whisper-large-v3-turbo"},
                {"id": " "},
                {"name": "missing-id"},
            ]
        }
    ) == ["whisper-large-v3", "whisper-large-v3-turbo"]


def test_model_discovery_uses_server_credential_and_returns_only_model_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = VoiceSttProviderSettings(
        id="groq",
        name="Groq Whisper",
        adapter="openai_compatible",
        base_url="https://api.groq.com/openai/v1",
        models=[],
    )
    monkeypatch.setattr(
        voice,
        "load_runtime_settings",
        lambda: SimpleNamespace(voice_stt=VoiceSttSettings(providers={"groq": profile})),
    )
    monkeypatch.setattr(voice, "_read_key", lambda _name: "test-secret")
    observed: dict[str, object] = {}

    class FakeClient:
        async def get(self, url: str, *, headers: dict[str, str], timeout: object):
            observed.update(url=url, headers=headers, timeout=timeout)
            return httpx.Response(
                200,
                json={"data": [{"id": "whisper-large-v3-turbo"}]},
            )

        async def aclose(self) -> None:
            return None

    def create_client(**kwargs: object) -> FakeClient:
        observed["client_kwargs"] = kwargs
        return FakeClient()

    monkeypatch.setattr(voice, "create_voice_http_client", create_client)

    result = _run_immediate(voice.list_voice_provider_models("groq"))

    assert result == {"models": ["whisper-large-v3-turbo"]}
    assert observed["url"] == "https://api.groq.com/openai/v1/models"
    assert observed["headers"] == {"Authorization": "Bearer test-secret"}
    assert observed["client_kwargs"] == {"private_hosts": set(), "private_only": False}
    assert "test-secret" not in str(result)


def test_settings_accepts_an_unconfigured_provider_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = VoiceSttSettings()
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        voice,
        "load_runtime_settings",
        lambda: SimpleNamespace(voice_stt=previous),
    )
    monkeypatch.setattr(voice, "_write_secrets", Mock())
    monkeypatch.setattr(
        voice,
        "save_runtime_settings",
        lambda settings: saved.update(settings=settings),
    )
    async def current_settings() -> dict[str, object]:
        return {"providers": [], "chain": []}

    monkeypatch.setattr(voice, "get_voice_settings", current_settings)
    request = voice.VoiceSettingsRequest(
        config=VoiceSttSettings(
            providers={
                "draft": VoiceSttProviderSettings(
                    id="draft",
                    name="Draft provider",
                    adapter="openai_compatible",
                    base_url="",
                    models=[],
                    locale=None,
                    enabled=True,
                )
            }
        )
    )

    status = 200
    try:
        _run_immediate(voice.put_voice_settings(request))
    except HTTPException as exc:
        status = exc.status_code

    assert status == 200
    saved_settings = saved["settings"]
    assert saved_settings.voice_stt.providers["draft"].base_url == ""
