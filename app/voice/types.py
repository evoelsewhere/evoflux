from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VoiceProviderConfig:
    id: str
    name: str
    adapter: str
    base_url: str
    models: list[str] = field(default_factory=list)
    locale: str | None = None
    enabled: bool = True
    timeout_seconds: float = 45.0


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    provider_id: str
    model_id: str


class SttAdapter(Protocol):
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
    ) -> TranscriptionResult: ...
