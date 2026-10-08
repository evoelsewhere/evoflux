from __future__ import annotations

from collections.abc import Callable

import httpx

from app.voice.errors import SttFailure, SttFailureKind, SttProviderError
from app.voice.providers import (
    AzureSpeechAdapter,
    DeepgramAdapter,
    GoogleCloudSpeechAdapter,
    LocalFasterWhisperAdapter,
    OpenAICompatibleAdapter,
)
from app.voice.types import SttAdapter

AdapterFactory = Callable[[httpx.AsyncClient], SttAdapter]

_BUILT_INS: dict[str, AdapterFactory] = {
    "openai_compatible": OpenAICompatibleAdapter,
    "deepgram": DeepgramAdapter,
    "azure_speech": AzureSpeechAdapter,
    "google_cloud": GoogleCloudSpeechAdapter,
    "local_faster_whisper": LocalFasterWhisperAdapter,
}


def adapter_ids() -> tuple[str, ...]:
    return tuple(_BUILT_INS)


def build_adapter(adapter_id: str, client: httpx.AsyncClient) -> SttAdapter:
    factory = _BUILT_INS.get(adapter_id)
    if factory is None:
        raise ValueError(f"Unsupported STT adapter: {adapter_id}")
    return factory(client)


def normalize_unexpected_error(provider_id: str, model_id: str) -> SttProviderError:
    return SttProviderError(
        SttFailure(SttFailureKind.UNKNOWN, "The STT provider returned an unexpected response."),
        provider_id=provider_id,
        model_id=model_id,
    )
