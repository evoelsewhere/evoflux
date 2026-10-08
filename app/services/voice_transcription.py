from __future__ import annotations

import asyncio
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.core.runtime_settings import (
    VoiceSttProviderSettings,
    VoiceSttRouteEntry,
    VoiceSttSettings,
)
from app.voice.errors import SttFailureKind, SttProviderError
from app.voice.registry import build_adapter, normalize_unexpected_error
from app.voice.network import create_voice_http_client
from app.voice.types import TranscriptionResult, VoiceProviderConfig

MAX_AUDIO_BYTES = 25 * 1024 * 1024
ALLOWED_AUDIO_TYPES = frozenset(
    {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/mpeg", "audio/flac", "audio/aac"}
)
_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_BLOCKED_HOSTS = {"metadata.google.internal", "metadata.azure.internal"}
_PROVIDER_HEALTH: dict[str, dict[str, str | None]] = {}
_PROVIDER_HEALTH_TTL_SECONDS = 24 * 60 * 60


def provider_health_snapshot() -> dict[str, dict[str, str | None]]:
    """Return only transient status/category/timestamp; never error bodies or clip data."""
    now = datetime.now(timezone.utc)
    snapshot: dict[str, dict[str, str | None]] = {}
    for provider_id, health in list(_PROVIDER_HEALTH.items()):
        try:
            checked_at = datetime.fromisoformat(str(health["checked_at"]))
            if (now - checked_at).total_seconds() > _PROVIDER_HEALTH_TTL_SECONDS:
                _PROVIDER_HEALTH.pop(provider_id, None)
                continue
        except (KeyError, TypeError, ValueError):
            _PROVIDER_HEALTH.pop(provider_id, None)
            continue
        snapshot[provider_id] = dict(health)
    return snapshot


def clear_provider_health(provider_id: str) -> None:
    _PROVIDER_HEALTH.pop(provider_id, None)


def _record_health(provider_id: str, *, status: str, category: str | None) -> None:
    _PROVIDER_HEALTH[provider_id] = {
        "status": status,
        "last_failure": category,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@dataclass(frozen=True, slots=True)
class TranscriptionOutcome:
    result: TranscriptionResult
    fallback_used: bool
    attempted: tuple[tuple[str, str, str], ...]


def validate_profile_id(value: str) -> str:
    cleaned = value.strip().lower()
    if not _PROFILE_ID.fullmatch(cleaned):
        raise ValueError("Provider ID must use lowercase letters, numbers, dashes or underscores.")
    return cleaned


def validate_endpoint(url: str) -> str:
    parsed = urlparse(url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter an HTTP or HTTPS endpoint without embedded credentials.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Enter an endpoint with a valid port.") from exc
    host = parsed.hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTS or host.endswith(".internal"):
        raise ValueError("Cloud metadata and internal metadata endpoints are not allowed.")
    local = host == "localhost" or host.endswith((".localhost", ".local", ".lan", ".home.arpa", ".ts.net"))
    try:
        address = ipaddress.ip_address(host)
        if address.is_link_local or address.is_unspecified or address.is_multicast:
            raise ValueError("Link-local, metadata and non-routable endpoints are not allowed.")
        tailscale_range = ipaddress.ip_network("100.64.0.0/10")
        local = address.is_loopback or address.is_private or (
            isinstance(address, ipaddress.IPv4Address) and address in tailscale_range
        )
    except ValueError as exc:
        if "not allowed" in str(exc):
            raise
    if parsed.scheme == "http" and not local:
        raise ValueError("Hosted STT endpoints must use HTTPS. HTTP is allowed for local or private endpoints.")
    return url.strip().rstrip("/")


def validate_audio(audio: bytes, content_type: str) -> None:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if not audio:
        raise ValueError("The recording is empty.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("The recording is too large (25 MB maximum).")
    if normalized not in ALLOWED_AUDIO_TYPES:
        raise ValueError("This recording format is not supported.")


def validate_chain(config: VoiceSttSettings) -> list[tuple[VoiceSttProviderSettings, VoiceSttRouteEntry]]:
    if not config.chain:
        raise ValueError("Configure a primary STT provider and model in Settings.")
    pairs: list[tuple[VoiceSttProviderSettings, VoiceSttRouteEntry]] = []
    seen: set[tuple[str, str]] = set()
    for entry in config.chain:
        key = (entry.provider_id, entry.model_id)
        if key in seen:
            continue
        seen.add(key)
        profile = config.providers.get(entry.provider_id)
        if not profile or not profile.enabled or entry.model_id not in profile.models:
            continue
        if profile.adapter == "local_faster_whisper":
            if profile.base_url:
                raise ValueError("The managed Local STT provider does not use a network endpoint.")
            private_endpoint = True
        else:
            validate_endpoint(profile.base_url)
            private_endpoint = is_private_endpoint(profile.base_url)
        if not config.local_private_only and not private_endpoint and not config.allow_hosted_fallback:
            continue
        pairs.append((profile, entry))
    if not pairs:
        raise ValueError("No enabled STT provider/model pairs are available in the configured chain.")
    return pairs


def is_private_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    if host.endswith((".local", ".lan", ".home.arpa", ".ts.net")):
        return True
    try:
        addr = ipaddress.ip_address(host)
        cgnat = ipaddress.ip_network("100.64.0.0/10")
        return addr.is_private or addr.is_loopback or (isinstance(addr, ipaddress.IPv4Address) and addr in cgnat)
    except ValueError:
        return False


async def transcribe_audio(
    config: VoiceSttSettings,
    *,
    audio: bytes,
    filename: str,
    content_type: str,
    language: str | None,
    get_api_key,
    client: httpx.AsyncClient | None = None,
) -> TranscriptionOutcome:
    validate_audio(audio, content_type)
    pairs = validate_chain(config)
    own_client = client is None
    private_hosts = {
        (urlparse(profile.base_url).hostname or "").lower()
        for profile, _ in pairs
        if is_private_endpoint(profile.base_url)
    }
    http_client = client or create_voice_http_client(
        private_hosts=private_hosts,
        private_only=config.local_private_only or not config.allow_hosted_fallback,
    )
    failures: list[tuple[str, str, str]] = []
    deadline = asyncio.get_running_loop().time() + 120.0
    try:
        for profile, route in pairs:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                failures.append((profile.id, route.model_id, "deadline"))
                break
            api_key = get_api_key(profile.id)
            adapter = build_adapter(profile.adapter, http_client)
            voice_profile = VoiceProviderConfig(
                id=profile.id,
                name=profile.name,
                adapter=profile.adapter,
                base_url=profile.base_url,
                models=profile.models,
                locale=profile.locale,
                timeout_seconds=min(45.0, remaining),
            )
            for attempt in range(2):
                try:
                    result = await adapter.transcribe(
                        voice_profile,
                        model_id=route.model_id,
                        api_key=api_key,
                        audio=audio,
                        filename=filename,
                        content_type=content_type,
                        language=language,
                    )
                    if not result.text:
                        raise normalize_unexpected_error(profile.id, route.model_id)
                    _record_health(profile.id, status="healthy", category=None)
                    return TranscriptionOutcome(result, bool(failures), tuple(failures))
                except SttProviderError as exc:
                    failures.append((profile.id, route.model_id, exc.kind.value))
                    status = "needs_attention" if exc.kind is SttFailureKind.AUTHENTICATION else "degraded"
                    _record_health(profile.id, status=status, category=exc.kind.value)
                    if exc.kind is SttFailureKind.TRANSIENT and attempt == 0:
                        remaining = deadline - asyncio.get_running_loop().time()
                        delay = min(max(exc.failure.retry_after_seconds or 0.2, 0.0), 2.0, remaining)
                        if delay > 0:
                            await asyncio.sleep(delay)
                            continue
                    if exc.kind is SttFailureKind.INVALID_REQUEST:
                        raise AllProvidersFailed(
                            "A configured provider rejected the request. Review its model and options.",
                            tuple(failures),
                        ) from exc
                    break
                except Exception:
                    failures.append((profile.id, route.model_id, SttFailureKind.UNKNOWN.value))
                    break
        summary = "; ".join(f"{provider}/{model}: {kind}" for provider, model, kind in failures)
        raise AllProvidersFailed(summary, tuple(failures))
    finally:
        if own_client:
            await http_client.aclose()


class AllProvidersFailed(Exception):
    def __init__(self, safe_summary: str, failures: tuple[tuple[str, str, str], ...]):
        self.safe_summary = safe_summary or "No STT provider could transcribe this recording."
        self.failures = failures
        super().__init__("No configured STT provider could transcribe this recording.")
