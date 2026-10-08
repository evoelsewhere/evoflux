import pytest

from app.voice.errors import SttFailureKind, classify_stt_http_error


@pytest.mark.parametrize(
    ("status_code", "body", "expected"),
    [
        (401, "invalid api key", SttFailureKind.AUTHENTICATION),
        (403, "credential expired", SttFailureKind.AUTHENTICATION),
        (429, "quota exceeded", SttFailureKind.RATE_LIMIT),
        (408, "request timeout", SttFailureKind.TRANSIENT),
        (503, "temporarily unavailable secret-value-123", SttFailureKind.TRANSIENT),
        (404, "model not found", SttFailureKind.MODEL_UNAVAILABLE),
        (400, "unknown model: retired-model", SttFailureKind.MODEL_UNAVAILABLE),
        (415, "unsupported audio format", SttFailureKind.UNSUPPORTED_AUDIO),
        (422, "invalid audio payload", SttFailureKind.UNSUPPORTED_AUDIO),
        (400, "invalid parameter: temperature", SttFailureKind.INVALID_REQUEST),
    ],
)
def test_classifies_provider_http_errors_for_fallback_policy(
    status_code: int, body: str, expected: SttFailureKind
) -> None:
    failure = classify_stt_http_error(status_code, body)

    assert failure.kind is expected
    assert failure.status_code == status_code
    assert failure.safe_message
    assert "secret-value-123" not in failure.safe_message


def test_unknown_server_errors_remain_transient() -> None:
    failure = classify_stt_http_error(502, "internal server detail")

    assert failure.kind is SttFailureKind.TRANSIENT
    assert "internal server detail" not in failure.safe_message
