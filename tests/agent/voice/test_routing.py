import asyncio
import socket

import httpx
import pytest
from pydantic import BaseModel

from app.core.runtime_settings import (
    VoiceSttProviderSettings,
    VoiceSttRouteEntry,
    VoiceSttSettings,
)
from app.services.voice_transcription import (
    transcribe_audio,
    validate_audio,
    validate_chain,
    validate_endpoint,
)
from app.voice.network import _PinnedDNSBackend, validate_resolved_addresses
from app.voice.types import TranscriptionResult


def make_settings() -> VoiceSttSettings:
    profiles = {
        "primary": VoiceSttProviderSettings(
            id="primary", name="Primary", adapter="openai_compatible",
            base_url="http://127.0.0.1:8080/v1", models=["whisper"],
        ),
        "backup": VoiceSttProviderSettings(
            id="backup", name="Backup", adapter="openai_compatible",
            base_url="http://localhost:8081/v1", models=["whisper"],
        ),
    }
    chain = [
        VoiceSttRouteEntry(provider_id="primary", model_id="whisper"),
        VoiceSttRouteEntry(provider_id="backup", model_id="whisper"),
    ]
    return VoiceSttSettings(providers=profiles, chain=chain)


@pytest.mark.asyncio
async def test_fails_over_in_configured_order_after_primary_auth_failure() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "8080" in str(request.url):
            return httpx.Response(401, json={"error": "secret detail"})
        return httpx.Response(200, json={"text": "recognized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        outcome = await transcribe_audio(
            make_settings(), audio=b"audio", filename="clip.webm", content_type="audio/webm",
            language="en", get_api_key=lambda _: "secret", client=client,
        )

    assert ["8080" in call for call in calls] == [True, False]
    assert outcome.result == TranscriptionResult("recognized", "backup", "whisper")
    assert outcome.fallback_used is True
    assert outcome.attempted == (("primary", "whisper", "authentication"),)


@pytest.mark.asyncio
async def test_request_validation_stops_before_provider_calls() -> None:
    with pytest.raises(ValueError, match="format"):
        validate_audio(b"audio", "application/octet-stream")


def test_rejects_remote_plain_http_but_allows_private_endpoint() -> None:
    assert validate_endpoint("http://192.168.1.24:8080/v1") == "http://192.168.1.24:8080/v1"
    with pytest.raises(ValueError, match="HTTPS"):
        validate_endpoint("http://speech.example.com/v1")
    with pytest.raises(ValueError, match="metadata"):
        validate_endpoint("http://169.254.169.254/latest/meta-data")
    assert validate_endpoint("http://100.101.2.3:8080/v1") == "http://100.101.2.3:8080/v1"


@pytest.mark.parametrize("endpoint", [
    "https://speech.example.com/v1?token=secret",
    "https://speech.example.com/v1#key=secret",
])
def test_rejects_query_and_fragment_from_saved_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="credentials"):
        validate_endpoint(endpoint)


def test_dns_pinning_rejects_metadata_and_requires_private_addresses_when_local_only() -> None:
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("169.254.169.254", 443)),
    ]
    with pytest.raises(OSError, match="restricted"):
        validate_resolved_addresses(records, require_private=False)

    public_records = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
    ]
    with pytest.raises(OSError, match="restricted to local"):
        validate_resolved_addresses(public_records, require_private=True)

    private_records = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.1.2.3", 443)),
    ]
    with pytest.raises(OSError, match="only to public"):
        validate_resolved_addresses(private_records, require_private=False, require_public=True)


def test_dns_pinning_returns_only_the_resolved_ip_literal() -> None:
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.1.20", 8080)),
    ]
    assert validate_resolved_addresses(records, require_private=True) == ["192.168.1.20"]

    with pytest.raises(OSError, match="only to public"):
        validate_resolved_addresses(records, require_private=False, require_public=True)

    tailscale_records = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("100.101.2.3", 443)),
    ]
    assert validate_resolved_addresses(tailscale_records, require_private=True) == ["100.101.2.3"]


def test_provider_health_status_expires_from_memory() -> None:
    from app.services import voice_transcription

    voice_transcription._PROVIDER_HEALTH["expired-test"] = {
        "status": "degraded",
        "last_failure": "transient",
        "checked_at": "2000-01-01T00:00:00+00:00",
    }

    assert "expired-test" not in voice_transcription.provider_health_snapshot()
    assert "expired-test" not in voice_transcription._PROVIDER_HEALTH


@pytest.mark.asyncio
async def test_dns_backend_connects_to_the_validated_ip_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.voice.network as network

    class Resolver:
        async def getaddrinfo(self, host: str, port: int, *, type: int):
            assert host == "speech.corp.example"
            assert port == 443
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.1.2.3", port))]

    class Delegate:
        connected_host: str | None = None

        async def connect_tcp(self, host: str, port: int, **kwargs: object) -> object:
            assert port == 443
            self.connected_host = host
            return object()

    backend = _PinnedDNSBackend(private_hosts=set(), private_only=True)
    delegate = Delegate()
    backend._delegate = delegate  # type: ignore[assignment]
    monkeypatch.setattr(network.asyncio, "get_running_loop", lambda: Resolver())

    await backend.connect_tcp("speech.corp.example", 443)

    assert delegate.connected_host == "10.1.2.3"


@pytest.mark.asyncio
async def test_local_private_only_accepts_custom_dns_hostname_for_pinned_private_validation() -> None:
    profile = VoiceSttProviderSettings(
        id="private-dns", name="Private DNS", adapter="openai_compatible",
        base_url="https://speech.corp.example/v1", models=["whisper"],
    )
    config = VoiceSttSettings(
        providers={profile.id: profile},
        chain=[VoiceSttRouteEntry(provider_id=profile.id, model_id="whisper")],
        local_private_only=True,
    )
    assert validate_chain(config) == [(profile, config.chain[0])]


@pytest.mark.asyncio
async def test_transcription_is_cancelled_when_request_disconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import voice as voice_route

    config = VoiceSttSettings()
    cancelled = False
    started = asyncio.Event()

    async def blocking_transcription(*args: object, **kwargs: object) -> None:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    class Disconnected:
        async def is_disconnected(self) -> bool:
            await started.wait()
            return True

    monkeypatch.setattr(voice_route, "transcribe_audio", blocking_transcription)
    result = await voice_route._transcribe_while_connected(Disconnected(), config)
    assert result is None
    assert cancelled is True


@pytest.mark.asyncio
async def test_explicit_provider_test_can_target_hosted_endpoint_without_enabling_hosted_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import voice as voice_route
    from app.services.voice_transcription import TranscriptionOutcome

    profile = VoiceSttProviderSettings(
        id="hosted-test", name="Hosted test", adapter="openai_compatible",
        base_url="https://speech.example.com/v1", models=["whisper"],
    )
    config = VoiceSttSettings(providers={profile.id: profile}, allow_hosted_fallback=False)
    observed: dict[str, VoiceSttSettings] = {}

    class Connected:
        async def is_disconnected(self) -> bool:
            return False

    async def fake_transcribe(test_config: VoiceSttSettings, **kwargs: object) -> TranscriptionOutcome:
        observed["config"] = test_config
        return TranscriptionOutcome(TranscriptionResult("sample words", profile.id, "whisper"), False, ())

    async def fake_read_audio(_request: object) -> tuple[bytes, str, str, dict[str, str]]:
        return b"sample", "sample.webm", "audio/webm", {"model_id": "whisper"}

    monkeypatch.setattr(voice_route, "load_runtime_settings", lambda: type("Runtime", (), {"voice_stt": config})())
    monkeypatch.setattr(voice_route, "_read_audio_form", fake_read_audio)
    monkeypatch.setattr(voice_route, "transcribe_audio", fake_transcribe)

    response = await voice_route.test_voice_provider(profile.id, Connected())

    assert response["ok"] is True
    assert observed["config"].allow_hosted_fallback is True
    assert observed["config"].chain == [VoiceSttRouteEntry(provider_id=profile.id, model_id="whisper")]


def test_hosted_provider_requires_explicit_opt_in() -> None:
    profile = VoiceSttProviderSettings(
        id="hosted", name="Hosted", adapter="openai_compatible",
        base_url="https://speech.example.com/v1", models=["whisper"],
    )
    route = VoiceSttRouteEntry(provider_id="hosted", model_id="whisper")
    config = VoiceSttSettings(providers={"hosted": profile}, chain=[route])
    with pytest.raises(ValueError, match="No enabled"):
        validate_chain(config)

    config.allow_hosted_fallback = True
    assert validate_chain(config) == [(profile, route)]


@pytest.mark.asyncio
async def test_settings_response_reports_credential_state_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import voice as voice_route

    profile = VoiceSttProviderSettings(
        id="local", name="Local", adapter="openai_compatible",
        base_url="http://127.0.0.1:8080/v1", models=["whisper"],
    )
    settings = VoiceSttSettings(providers={"local": profile})

    class Runtime(BaseModel):
        voice_stt: VoiceSttSettings

    variable = voice_route._credential_name("local")
    monkeypatch.setattr(voice_route, "load_runtime_settings", lambda: Runtime(voice_stt=settings))
    monkeypatch.setenv(variable, "do-not-return-this-key")

    response = await voice_route.get_voice_settings()

    assert response["providers"][0]["credential_configured"] is True
    assert "do-not-return-this-key" not in repr(response)
    monkeypatch.delenv(variable, raising=False)


@pytest.mark.asyncio
async def test_multipart_audio_parser_keeps_clip_in_bounded_memory() -> None:
    from starlette.requests import Request

    from app.api.routes.voice import _read_audio_form

    boundary = "voice-test-boundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\nvi\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"clip.webm\"\r\n"
        "Content-Type: audio/webm;codecs=opus\r\n\r\naudio-bytes\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({
        "type": "http", "method": "POST", "path": "/api/voice/transcribe",
        "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode()), (b"content-length", str(len(body)).encode())],
        "query_string": b"", "server": ("test", 80), "client": ("test", 1), "scheme": "http",
    }, receive)

    audio, filename, content_type, fields = await _read_audio_form(request)

    assert audio == b"audio-bytes"
    assert filename == "clip.webm"
    assert content_type.startswith("audio/webm;")
    assert "opus" in content_type
    assert fields["language"] == "vi"
