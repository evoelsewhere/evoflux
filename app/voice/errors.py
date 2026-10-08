from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class SttFailureKind(StrEnum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SttFailure:
    """Sanitized failure category used for routing and safe UI feedback."""

    kind: SttFailureKind
    safe_message: str
    status_code: int | None = None
    retry_after_seconds: float | None = None


class SttProviderError(Exception):
    """A provider-scoped failure that never carries upstream response bodies."""

    def __init__(
        self,
        failure: SttFailure,
        *,
        provider_id: str,
        model_id: str,
    ) -> None:
        self.failure = failure
        self.kind = failure.kind
        self.safe_message = failure.safe_message
        self.status_code = failure.status_code
        self.provider_id = provider_id
        self.model_id = model_id
        super().__init__(failure.safe_message)


_MODEL_MISSING = re.compile(
    r"(?:model.{0,40}(?:not found|does not exist|unavailable|unknown)|"
    r"(?:unknown|invalid) model)",
    re.IGNORECASE,
)
_AUDIO_INVALID = re.compile(
    r"(?:unsupported|invalid|unrecognized).{0,40}(?:audio|media|file|format)|"
    r"(?:audio|media|file|format).{0,40}(?:unsupported|invalid|unrecognized)",
    re.IGNORECASE,
)


def classify_stt_http_error(
    status_code: int,
    body: str = "",
    *,
    retry_after_seconds: float | None = None,
) -> SttFailure:
    """Map upstream HTTP failures without exposing their response bodies."""
    normalized_body = body[:2048]

    if status_code in {401, 403}:
        return SttFailure(
            SttFailureKind.AUTHENTICATION,
            "The STT provider rejected its credentials. Update or test this provider in Settings.",
            status_code,
        )
    if status_code in {402, 429}:
        return SttFailure(
            SttFailureKind.RATE_LIMIT,
            "The STT provider quota or rate limit was reached.",
            status_code,
            retry_after_seconds,
        )
    if status_code in {408, 425} or status_code >= 500:
        return SttFailure(
            SttFailureKind.TRANSIENT,
            "The STT provider is temporarily unavailable.",
            status_code,
            retry_after_seconds,
        )
    if status_code == 404 or (
        400 <= status_code < 500 and _MODEL_MISSING.search(normalized_body)
    ):
        return SttFailure(
            SttFailureKind.MODEL_UNAVAILABLE,
            "The configured STT model or endpoint was not found.",
            status_code,
        )
    if status_code in {400, 413, 415, 422} and _AUDIO_INVALID.search(normalized_body):
        return SttFailure(
            SttFailureKind.UNSUPPORTED_AUDIO,
            "The STT provider does not accept this audio format.",
            status_code,
        )
    if 400 <= status_code < 500:
        return SttFailure(
            SttFailureKind.INVALID_REQUEST,
            "The STT provider rejected this transcription request.",
            status_code,
        )
    return SttFailure(
        SttFailureKind.UNKNOWN,
        "The STT provider returned an unexpected response.",
        status_code,
    )
