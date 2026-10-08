import base64
import json

import httpx
import pytest

from app.voice.providers import (
    AzureSpeechAdapter,
    DeepgramAdapter,
    GoogleCloudSpeechAdapter,
    OpenAICompatibleAdapter,
)
from app.voice.types import VoiceProviderConfig


AUDIO = b"recorded-audio-bytes"


def provider(adapter: str, base_url: str, **kwargs: object) -> VoiceProviderConfig:
    return VoiceProviderConfig(
        id="voice-test",
        name="Voice test",
        adapter=adapter,
        base_url=base_url,
        models=["speech-model"],
        **kwargs,
    )


@pytest.mark.asyncio
async def test_openai_compatible_adapter_sends_multipart_and_reads_text() -> None:
    observed: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("authorization")
        observed["body"] = request.content
        return httpx.Response(200, json={"text": "hello from local whisper"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await OpenAICompatibleAdapter(client).transcribe(
            provider("openai_compatible", "http://127.0.0.1:8080/v1"),
            model_id="speech-model",
            api_key="local-key",
            audio=AUDIO,
            filename="clip.webm",
            content_type="audio/webm",
            language="vi",
        )

    assert result.text == "hello from local whisper"
    assert observed["url"] == "http://127.0.0.1:8080/v1/audio/transcriptions"
    assert observed["authorization"] == "Bearer local-key"
    body = observed["body"]
    assert isinstance(body, bytes)
    assert b"name=\"model\"" in body and b"speech-model" in body
    assert b"name=\"language\"" in body and b"vi" in body
    assert AUDIO in body


@pytest.mark.asyncio
async def test_deepgram_adapter_maps_nested_transcript() -> None:
    observed: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("authorization")
        observed["body"] = request.content
        return httpx.Response(
            200,
            json={
                "results": {
                    "channels": [
                        {"alternatives": [{"transcript": "deepgram result"}]}
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await DeepgramAdapter(client).transcribe(
            provider("deepgram", "https://api.deepgram.com"),
            model_id="nova-3",
            api_key="dg-key",
            audio=AUDIO,
            filename="clip.webm",
            content_type="audio/webm",
            language="en",
        )

    assert result.text == "deepgram result"
    assert str(observed["url"]).startswith("https://api.deepgram.com/v1/listen?")
    assert "model=nova-3" in str(observed["url"])
    assert observed["authorization"] == "Token dg-key"
    assert observed["body"] == AUDIO


@pytest.mark.asyncio
async def test_azure_adapter_sends_definition_and_maps_combined_phrase() -> None:
    observed: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Ocp-Apim-Subscription-Key")
        observed["body"] = request.content
        return httpx.Response(200, json={"combinedPhrases": [{"text": "azure result"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await AzureSpeechAdapter(client).transcribe(
            provider(
                "azure_speech",
                "https://westus.api.cognitive.microsoft.com",
                locale="vi-VN",
            ),
            model_id="speech-model",
            api_key="azure-key",
            audio=AUDIO,
            filename="clip.webm",
            content_type="audio/webm",
            language=None,
        )

    assert result.text == "azure result"
    assert "transcriptions:transcribe" in str(observed["url"])
    assert observed["authorization"] == "azure-key"
    body = observed["body"]
    assert isinstance(body, bytes)
    assert b"name=\"audio\"" in body and AUDIO in body
    assert b"vi-VN" in body


@pytest.mark.asyncio
async def test_google_adapter_uses_adc_and_maps_results(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class Credentials:
        token = "adc-access-token"
        valid = False

        def refresh(self, request: object) -> None:
            observed["refreshed"] = True

    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda **kwargs: (Credentials(), "test-project"))

    def handle(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("authorization")
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"alternatives": [{"transcript": "google result"}]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await GoogleCloudSpeechAdapter(client).transcribe(
            provider("google_cloud", "https://speech.googleapis.com/v1", locale="vi-VN"),
            model_id="long",
            api_key=None,
            audio=AUDIO,
            filename="clip.wav",
            content_type="audio/wav",
            language=None,
        )

    assert result.text == "google result"
    assert observed["authorization"] == "Bearer adc-access-token"
    payload = observed["payload"]
    assert isinstance(payload, dict)
    assert payload["audio"]["content"] == base64.b64encode(AUDIO).decode("ascii")
    assert payload["config"]["languageCode"] == "vi-VN"
    assert observed["refreshed"] is True
