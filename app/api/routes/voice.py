from __future__ import annotations

import asyncio
import os
import hashlib
from dataclasses import asdict
from pathlib import Path
from email import policy
from email.parser import BytesParser
from contextlib import suppress
from urllib.parse import urljoin, urlparse

import httpx
from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.local_stt_runtime import LocalSttRuntimeStatusResponse
from app.cli.seed import write_env_credentials
from app.core.config import settings
from app.core.runtime_settings import (
    VoiceSttProviderSettings,
    VoiceSttSettings,
    VoiceSttRouteEntry,
    load_runtime_settings,
    save_runtime_settings,
)
from app.services.voice_transcription import (
    AllProvidersFailed,
    TranscriptionOutcome,
    clear_provider_health,
    provider_health_snapshot,
    transcribe_audio,
    is_private_endpoint,
    validate_endpoint,
    validate_profile_id,
)
from app.voice.network import create_voice_http_client
from app.voice.registry import adapter_ids
from app.services.local_stt_runtime import (
    LocalSttRuntimeError,
    cancel_install,
    check_runtime,
    dismiss_error,
    runtime_status,
    start_install,
    uninstall_runtime,
)

router = APIRouter()
_MAX_MULTIPART_OVERHEAD = 64 * 1024
_MAX_MODEL_IDS = 500


def _extract_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("The model catalog response is invalid.")
    models: list[str] = []
    seen: set[str] = set()
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        model_id = model_id.strip()
        if model_id and len(model_id) <= 200 and model_id not in seen:
            seen.add(model_id)
            models.append(model_id)
            if len(models) >= _MAX_MODEL_IDS:
                break
    return models


async def _transcribe_while_connected(
    request: Request,
    config: VoiceSttSettings,
    **kwargs,
) -> TranscriptionOutcome | None:
    task = asyncio.create_task(transcribe_audio(config, **kwargs))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
                return None
            done, _ = await asyncio.wait({task}, timeout=0.15)
            if done:
                break
        return await task
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
        raise


async def _read_audio_form(request: Request) -> tuple[bytes, str, str, dict[str, str]]:
    """Read a bounded multipart clip in memory (never through a disk-spooling UploadFile)."""
    from app.services.voice_transcription import MAX_AUDIO_BYTES

    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="Voice input requires a multipart audio upload.")
    if request.headers.get("content-length"):
        try:
            if int(request.headers["content-length"]) > MAX_AUDIO_BYTES + _MAX_MULTIPART_OVERHEAD:
                raise HTTPException(status_code=413, detail="The recording is too large (25 MB maximum).")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid request length.") from exc
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_AUDIO_BYTES + _MAX_MULTIPART_OVERHEAD:
            raise HTTPException(status_code=413, detail="The recording is too large (25 MB maximum).")
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + bytes(chunks)
    )
    audio: tuple[bytes, str, str] | None = None
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        field_name = part.get_param("name", header="content-disposition")
        if field_name == "audio" and audio is None and part.get_filename() is not None:
            audio = (
                part.get_payload(decode=True) or b"",
                Path(part.get_filename()).name or "recording.webm",
                str(part.get("Content-Type") or part.get_content_type()),
            )
        elif field_name in {"language", "model_id"} and field_name not in fields:
            raw = part.get_payload(decode=True) or b""
            fields[field_name] = raw.decode("utf-8", errors="replace")[:200]
    if audio is None:
        raise HTTPException(status_code=422, detail="The multipart request must include an audio file.")
    return audio[0], audio[1], audio[2], fields


class VoiceSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: VoiceSttSettings
    credentials: dict[str, str] = Field(default_factory=dict)
    clear_credentials: list[str] = Field(default_factory=list)


def _credential_name(profile_id: str) -> str:
    safe_id = validate_profile_id(profile_id)
    suffix = hashlib.sha256(safe_id.encode("utf-8")).hexdigest()[:8].upper()
    return f"EVOFLUX_STT_{safe_id.upper().replace('-', '_')}_{suffix}_API_KEY"


def _read_key(name: str) -> str:
    if os.getenv(name):
        return str(os.environ[name])
    env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    value = dotenv_values(env_file).get(name) if env_file.is_file() else None
    return str(value) if value else ""


def _write_secrets(credentials: dict[str, str]) -> None:
    if not credentials:
        return
    env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    write_env_credentials(env_file, credentials)
    for name, value in credentials.items():
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)


@router.get("/settings")
async def get_voice_settings() -> dict[str, object]:
    config = load_runtime_settings().voice_stt
    profiles = []
    for profile in config.providers.values():
        item = profile.model_dump(mode="json")
        item["credential_configured"] = bool(_read_key(_credential_name(profile.id)))
        item["health"] = provider_health_snapshot().get(profile.id)
        profiles.append(item)
    return {
        "providers": profiles,
        "chain": [entry.model_dump(mode="json") for entry in config.chain],
        "allow_hosted_fallback": config.allow_hosted_fallback,
        "local_private_only": config.local_private_only,
        "adapters": list(adapter_ids()),
    }


@router.put("/settings")
async def put_voice_settings(body: VoiceSettingsRequest) -> dict[str, object]:
    config = body.config
    if len(config.providers) > 12 or len(config.chain) > 24:
        raise HTTPException(status_code=422, detail="Voice settings support up to 12 provider profiles and 24 ordered model routes.")
    normalized: dict[str, VoiceSttProviderSettings] = {}
    secret_updates: dict[str, str] = {}
    previous = load_runtime_settings().voice_stt
    for key, profile in config.providers.items():
        try:
            profile_id = validate_profile_id(key)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if profile.id != profile_id:
            raise HTTPException(status_code=422, detail="Provider ID must match its profile key.")
        if profile.adapter not in adapter_ids():
            raise HTTPException(status_code=422, detail="Unsupported STT adapter.")
        supplied_key = body.credentials.get(profile_id)
        if profile.adapter == "local_faster_whisper":
            if profile.base_url:
                raise HTTPException(status_code=422, detail="The managed Local STT provider does not use an endpoint.")
            if supplied_key:
                raise HTTPException(status_code=422, detail="The managed Local STT provider does not use an API key.")
            endpoint = ""
        else:
            if profile.base_url.strip():
                try:
                    endpoint = validate_endpoint(profile.base_url)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            else:
                endpoint = ""
        models = list(dict.fromkeys(model.strip() for model in profile.models if model.strip()))
        normalized[profile_id] = profile.model_copy(update={"base_url": endpoint, "models": models})
        old_profile = previous.providers.get(profile_id)
        if profile.adapter == "local_faster_whisper" and old_profile and old_profile.adapter != profile.adapter:
            secret_updates[_credential_name(profile_id)] = ""
        if supplied_key:
            secret_updates[_credential_name(profile_id)] = supplied_key
    config = config.model_copy(update={"providers": normalized})
    for entry in config.chain:
        profile = normalized.get(entry.provider_id)
        if not profile or entry.model_id not in profile.models:
            raise HTTPException(status_code=422, detail="Each routing entry must reference a configured provider and model.")
        if profile.adapter != "local_faster_whisper" and not profile.base_url:
            raise HTTPException(status_code=422, detail="Configure an endpoint before adding this provider to the routing chain.")
    clear_ids = set(body.clear_credentials)
    clear_ids.update(set(previous.providers) - set(normalized))
    for profile_id in clear_ids:
        clear_provider_health(profile_id)
        try:
            secret_updates[_credential_name(profile_id)] = ""
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    _write_secrets(secret_updates)
    runtime = load_runtime_settings()
    runtime.voice_stt = config
    save_runtime_settings(runtime)
    return await get_voice_settings()


@router.get("/providers/{provider_id}/models")
async def list_voice_provider_models(provider_id: str) -> dict[str, list[str]]:
    try:
        provider_id = validate_profile_id(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = load_runtime_settings().voice_stt.providers.get(provider_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Choose a saved provider profile first.")
    if profile.adapter != "openai_compatible":
        raise HTTPException(status_code=422, detail="Model discovery is supported for OpenAI-compatible endpoints.")
    if not profile.base_url.strip():
        raise HTTPException(status_code=422, detail="Configure this provider endpoint before loading models.")
    try:
        endpoint = validate_endpoint(profile.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    api_key = _read_key(_credential_name(provider_id))
    hostname = (urlparse(endpoint).hostname or "").lower()
    client = create_voice_http_client(
        private_hosts={hostname} if hostname and is_private_endpoint(endpoint) else set(),
        private_only=False,
    )
    try:
        response = await client.get(
            urljoin(endpoint.rstrip("/") + "/", "models"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach the configured provider model catalog.") from exc
    finally:
        await client.aclose()

    if not response.is_success:
        raise HTTPException(status_code=502, detail=f"The configured provider rejected model discovery (HTTP {response.status_code}).")
    try:
        models = _extract_model_ids(response.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="The provider returned an invalid model catalog.") from exc
    return {"models": models}


@router.post("/transcribe", response_model=None)
async def transcribe(request: Request) -> dict[str, object] | Response:
    payload, filename, content_type, fields = await _read_audio_form(request)
    config = load_runtime_settings().voice_stt
    try:
        outcome = await _transcribe_while_connected(
            request,
            config,
            audio=payload,
            filename=filename,
            content_type=content_type,
            language=fields.get("language", "")[:32] or None,
            get_api_key=lambda provider_id: _read_key(_credential_name(provider_id)),
        )
        if outcome is None:
            return Response(status_code=204)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AllProvidersFailed as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": "No configured STT provider could transcribe this recording.", "providers": [
                {"provider_id": provider, "model_id": model, "category": category}
                for provider, model, category in exc.failures
            ]},
        ) from exc
    return {
        "text": outcome.result.text,
        "provider_id": outcome.result.provider_id,
        "model_id": outcome.result.model_id,
        "fallback_used": outcome.fallback_used,
        "attempted": [
            {"provider_id": provider, "model_id": model, "category": category}
            for provider, model, category in outcome.attempted
        ],
    }




@router.post("/providers/{provider_id}/test", response_model=None)
async def test_voice_provider(
    provider_id: str,
    request: Request,
) -> dict[str, object] | Response:
    """Test one provider using only a sample explicitly recorded by the user."""
    try:
        provider_id = validate_profile_id(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    config = load_runtime_settings().voice_stt
    payload, filename, content_type, fields = await _read_audio_form(request)
    model_id = fields.get("model_id", "")
    if not model_id or len(model_id) > 200:
        raise HTTPException(status_code=422, detail="Choose a model ID for the provider test.")
    profile = config.providers.get(provider_id)
    if not profile or model_id not in profile.models:
        raise HTTPException(status_code=404, detail="Choose a saved provider and model before testing.")
    test_config = config.model_copy(update={
        "providers": {provider_id: profile},
        "chain": [VoiceSttRouteEntry(provider_id=provider_id, model_id=model_id)],
        # Recording and submitting a sample here is the user's explicit
        # one-shot provider test; normal transcription remains opt-in gated.
        "allow_hosted_fallback": config.allow_hosted_fallback or not config.local_private_only,
    })
    try:
        outcome = await _transcribe_while_connected(
            request,
            test_config,
            audio=payload,
            filename=filename,
            content_type=content_type,
            language=profile.locale,
            get_api_key=lambda current_id: _read_key(_credential_name(current_id)),
        )
        if outcome is None:
            return Response(status_code=204)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AllProvidersFailed as exc:
        raise HTTPException(status_code=502, detail={
            "message": "The selected STT provider test failed.",
            "providers": [{"provider_id": provider, "model_id": model, "category": category} for provider, model, category in exc.failures],
        }) from exc
    return {"ok": True, "provider_id": outcome.result.provider_id, "model_id": outcome.result.model_id, "text": outcome.result.text}


def _local_runtime_response() -> LocalSttRuntimeStatusResponse:
    return LocalSttRuntimeStatusResponse.model_validate(asdict(runtime_status()))


@router.get("/runtime/status", response_model=LocalSttRuntimeStatusResponse)
async def get_local_stt_runtime_status() -> LocalSttRuntimeStatusResponse:
    return await asyncio.to_thread(_local_runtime_response)


@router.post("/runtime/install", response_model=LocalSttRuntimeStatusResponse)
async def install_local_stt_runtime() -> LocalSttRuntimeStatusResponse:
    from app.services.local_stt_runtime.worker_client import worker

    await worker.close()
    try:
        start_install()
    except LocalSttRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await asyncio.to_thread(_local_runtime_response)


@router.post("/runtime/install/cancel", response_model=LocalSttRuntimeStatusResponse)
async def cancel_local_stt_runtime_install() -> LocalSttRuntimeStatusResponse:
    try:
        cancel_install()
    except LocalSttRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await asyncio.to_thread(_local_runtime_response)


@router.post("/runtime/install/dismiss", status_code=204)
async def dismiss_local_stt_runtime_error() -> None:
    dismiss_error()


@router.post("/runtime/check", response_model=LocalSttRuntimeStatusResponse)
async def check_local_stt_runtime() -> LocalSttRuntimeStatusResponse:
    from app.services.local_stt_runtime.worker_client import worker

    await worker.close()
    try:
        status = await asyncio.to_thread(check_runtime)
    except LocalSttRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LocalSttRuntimeStatusResponse.model_validate(asdict(status))


@router.delete("/runtime", status_code=204)
async def uninstall_local_stt_runtime() -> None:
    from app.services.local_stt_runtime.worker_client import worker

    await worker.close()
    try:
        await asyncio.to_thread(uninstall_runtime)
    except (OSError, LocalSttRuntimeError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Local STT files could not be fully removed. Retry from Settings → Voice input.",
        ) from exc
