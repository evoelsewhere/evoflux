from __future__ import annotations

import base64
import asyncio
import json
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import httpx

from app.voice.errors import (
    SttFailure,
    SttFailureKind,
    SttProviderError,
    classify_stt_http_error,
)
from app.voice.types import TranscriptionResult, VoiceProviderConfig
from app.services.local_stt_runtime.manifest import MODEL_ID
from app.services.local_stt_runtime.worker_client import LocalWorkerError, worker


class _HttpAdapter:
    adapter_name = ""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    def _error(self, provider: VoiceProviderConfig, model_id: str, response: httpx.Response) -> SttProviderError:
        retry_after = self._retry_after(response.headers.get("retry-after"))
        failure = classify_stt_http_error(
            response.status_code,
            response.text,
            retry_after_seconds=retry_after,
        )
        return SttProviderError(failure, provider_id=provider.id, model_id=model_id)

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def _result(self, provider: VoiceProviderConfig, model_id: str, text: Any) -> TranscriptionResult:
        if not isinstance(text, str):
            text = ""
        return TranscriptionResult(text=text.strip(), provider_id=provider.id, model_id=model_id)

    async def _post(self, provider: VoiceProviderConfig, url: str, **kwargs: Any) -> httpx.Response:
        model_id = str(kwargs.pop("model_id", ""))
        try:
            response = await self.client.post(url, timeout=provider.timeout_seconds, **kwargs)
        except httpx.TimeoutException as exc:
            raise SttProviderError(
                SttFailure(SttFailureKind.TRANSIENT, "The STT provider timed out."),
                provider_id=provider.id,
                model_id=model_id,
            ) from exc
        except httpx.RequestError as exc:
            raise SttProviderError(
                SttFailure(SttFailureKind.TRANSIENT, "The STT provider could not be reached."),
                provider_id=provider.id,
                model_id=model_id,
            ) from exc
        return response


class OpenAICompatibleAdapter(_HttpAdapter):
    async def transcribe(self, provider: VoiceProviderConfig, *, model_id: str, api_key: str | None, audio: bytes, filename: str, content_type: str, language: str | None) -> TranscriptionResult:
        base = provider.base_url.rstrip("/") + "/"
        url = urljoin(base, "audio/transcriptions")
        data: dict[str, str] = {"model": model_id}
        if language:
            data["language"] = language
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = await self._post(
            provider,
            url,
            files={"file": (filename, audio, content_type)},
            data=data,
            headers=headers,
            model_id=model_id,
        )
        if not response.is_success:
            raise self._error(provider, model_id, response)
        try:
            payload = response.json()
            text = payload.get("text") if isinstance(payload, dict) else None
        except ValueError:
            text = response.text if response.headers.get("content-type", "").startswith("text/plain") else None
        return self._result(provider, model_id, text)


class DeepgramAdapter(_HttpAdapter):
    async def transcribe(self, provider: VoiceProviderConfig, *, model_id: str, api_key: str | None, audio: bytes, filename: str, content_type: str, language: str | None) -> TranscriptionResult:
        params = {"model": model_id, "smart_format": "true"}
        if language:
            params["language"] = language
        headers = {"Authorization": f"Token {api_key}"} if api_key else {}
        headers["Content-Type"] = content_type
        response = await self._post(provider, provider.base_url.rstrip("/") + "/v1/listen", params=params, content=audio, headers=headers, model_id=model_id)
        if not response.is_success:
            raise self._error(provider, model_id, response)
        try:
            payload = response.json()
            text = payload["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SttProviderError(SttFailure(SttFailureKind.INVALID_RESPONSE, "The STT provider returned an invalid response."), provider_id=provider.id, model_id=model_id) from exc
        return self._result(provider, model_id, text)


class AzureSpeechAdapter(_HttpAdapter):
    async def transcribe(self, provider: VoiceProviderConfig, *, model_id: str, api_key: str | None, audio: bytes, filename: str, content_type: str, language: str | None) -> TranscriptionResult:
        locale = language or provider.locale or "en-US"
        url = provider.base_url.rstrip("/") + "/speechtotext/transcriptions:transcribe"
        params = {"api-version": "2024-11-15", "model": model_id}
        definition = {"locales": [locale], "profanityFilterMode": "None"}
        headers = {"Ocp-Apim-Subscription-Key": api_key} if api_key else {}
        response = await self._post(provider, url, params=params, data={"definition": json.dumps(definition)}, files={"audio": (filename, audio, content_type)}, headers=headers, model_id=model_id)
        if not response.is_success:
            raise self._error(provider, model_id, response)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("invalid JSON root")
            phrases = payload.get("combinedPhrases") or payload.get("phrases") or []
            text = " ".join(phrase["text"] for phrase in phrases)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SttProviderError(SttFailure(SttFailureKind.INVALID_RESPONSE, "The STT provider returned an invalid response."), provider_id=provider.id, model_id=model_id) from exc
        return self._result(provider, model_id, text)


class GoogleCloudSpeechAdapter(_HttpAdapter):
    async def transcribe(self, provider: VoiceProviderConfig, *, model_id: str, api_key: str | None, audio: bytes, filename: str, content_type: str, language: str | None) -> TranscriptionResult:
        try:
            token = await asyncio.to_thread(self._adc_token)
        except Exception as exc:
            raise SttProviderError(SttFailure(SttFailureKind.AUTHENTICATION, "Google Cloud credentials are unavailable. Configure Application Default Credentials."), provider_id=provider.id, model_id=model_id) from exc

        language_code = language or provider.locale or "en-US"
        try:
            encoding = self._google_encoding(content_type)
        except ValueError as exc:
            raise SttProviderError(SttFailure(SttFailureKind.UNSUPPORTED_AUDIO, "Google Cloud Speech does not accept this audio format."), provider_id=provider.id, model_id=model_id) from exc
        payload = {
            "config": {"encoding": encoding, "languageCode": language_code, "model": model_id},
            "audio": {"content": base64.b64encode(audio).decode("ascii")},
        }
        headers = {"Authorization": f"Bearer {token}"}
        response = await self._post(provider, provider.base_url.rstrip("/") + "/speech:recognize", json=payload, headers=headers, model_id=model_id)
        if not response.is_success:
            raise self._error(provider, model_id, response)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("invalid JSON root")
            results = payload.get("results", [])
            text = " ".join(item["alternatives"][0]["transcript"] for item in results)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SttProviderError(SttFailure(SttFailureKind.INVALID_RESPONSE, "The STT provider returned an invalid response."), provider_id=provider.id, model_id=model_id) from exc
        return self._result(provider, model_id, text)

    @staticmethod
    def _adc_token() -> str:
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not credentials.valid or not credentials.token:
            credentials.refresh(Request())
        return str(credentials.token or "")

    @staticmethod
    def _google_encoding(content_type: str) -> str:
        mime = content_type.split(";", 1)[0].lower()
        encodings = {
            "audio/wav": "LINEAR16",
            "audio/x-wav": "LINEAR16",
            "audio/flac": "FLAC",
            "audio/ogg": "OGG_OPUS",
            "audio/webm": "WEBM_OPUS",
            "audio/mpeg": "MP3",
        }
        try:
            return encodings[mime]
        except KeyError as exc:
            raise ValueError("Unsupported Google Speech audio encoding") from exc


class LocalFasterWhisperAdapter(_HttpAdapter):
    """CPU-only local provider backed by the opt-in managed model runtime."""

    async def transcribe(
        self,
        provider: VoiceProviderConfig,
        *,
        model_id: str,
        api_key: str | None,
        audio: bytes,
        filename: str,
        content_type: str,
        language: str | None,
    ) -> TranscriptionResult:
        del api_key
        if model_id != MODEL_ID:
            raise SttProviderError(
                SttFailure(SttFailureKind.MODEL_UNAVAILABLE, "The selected local speech model is unavailable."),
                provider_id=provider.id,
                model_id=model_id,
            )
        try:
            text = await worker.transcribe(
                audio=audio,
                filename=filename,
                content_type=content_type,
                language=language or provider.locale,
                timeout_seconds=provider.timeout_seconds,
            )
        except LocalWorkerError as exc:
            if exc.category in {"runtime_unavailable", "model_load_failed"}:
                kind = SttFailureKind.MODEL_UNAVAILABLE
                message = "Install or repair Local STT in Settings → Voice input."
            elif exc.category == "invalid_audio":
                kind = SttFailureKind.UNSUPPORTED_AUDIO
                message = "The local speech model could not read this recording format."
            elif exc.category == "timeout":
                kind = SttFailureKind.TRANSIENT
                message = "Local speech recognition took too long. Try a shorter recording."
            else:
                kind = SttFailureKind.UNKNOWN
                message = "Local speech recognition failed. Check the installed model in Settings."
            raise SttProviderError(
                SttFailure(kind, message),
                provider_id=provider.id,
                model_id=model_id,
            ) from exc
        return self._result(provider, model_id, text)
