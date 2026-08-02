"""Contract tests for Kimi Code's OpenAI-compatible API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from app.agent.providers.kimi import KIMI_CODE_API_BASE, KimiCodeProvider
from app.agent.providers.kimi.kimi import _KimiCodeCompletionsHandler
from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.schemas.chat import HumanMessage, ImageUrlBlock


def _provider(model: str = "kimi-for-coding", **kwargs) -> KimiCodeProvider:
    return KimiCodeProvider(
        api_key="kimi-test-key",
        model=model,
        **kwargs,
    )


def test_kimi_uses_dedicated_chat_completions_provider() -> None:
    provider = _provider()

    assert isinstance(provider, ChatCompletionsOnlyProvider)
    assert isinstance(provider._completions, _KimiCodeCompletionsHandler)
    assert provider._use_responses is False


@pytest.mark.parametrize(
    "configured",
    [
        "",
        "https://api.kimi.ai",
        "https://api.kimi.ai/v1/",
        "https://api.kimi.com/coding/v1/",
    ],
)
def test_kimi_normalizes_defaults_and_legacy_urls(configured: str) -> None:
    assert _provider(base_url=configured).base_url == KIMI_CODE_API_BASE


def test_kimi_preserves_custom_gateway_url() -> None:
    provider = _provider(base_url="https://router.example.com/kimi/v1/")

    assert provider.base_url == "https://router.example.com/kimi/v1"


def test_k3_request_uses_fixed_sampling_and_exact_effort_mapping() -> None:
    provider = _provider(
        "k3",
        temperature=0.4,
        top_p=0.8,
        model_kwargs={
            "thinking_level": "medium",
            "prompt_cache_key": "openai-only",
        },
    )
    body = provider._completions.build_request(
        [HumanMessage(content="inspect")],
        None,
        stream=True,
        merged=provider._merged_kwargs(max_tokens=512),
    )

    assert body["reasoning_effort"] == "high"
    assert body["max_completion_tokens"] == 512
    assert body["stream_options"] == {"include_usage": True}
    assert "max_tokens" not in body
    assert "temperature" not in body
    assert "top_p" not in body
    assert "prompt_cache_key" not in body


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("low", "low"),
        ("minimal", "low"),
        ("high", "high"),
        ("xhigh", "max"),
        ("ultra", "max"),
        ("max", "max"),
    ],
)
def test_k3_maps_supported_effort_aliases(requested: str, expected: str) -> None:
    provider = _provider("k3", model_kwargs={"thinking_level": requested})
    body = provider._completions.build_request(
        [HumanMessage(content="inspect")], None, False, provider._merged_kwargs()
    )

    assert body["reasoning_effort"] == expected


def test_k3_can_explicitly_disable_thinking_with_documented_shape() -> None:
    provider = _provider("k3", model_kwargs={"thinking_level": "none"})
    body = provider._completions.build_request(
        [HumanMessage(content="inspect")], None, False, provider._merged_kwargs()
    )

    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_k27_ignores_stale_effort_and_keeps_provider_default_thinking() -> None:
    provider = _provider(model_kwargs={"thinking_level": "max"})
    body = provider._completions.build_request(
        [HumanMessage(content="inspect")], None, False, provider._merged_kwargs()
    )

    assert "reasoning_effort" not in body
    assert "thinking" not in body


def test_kimi_vision_uses_openai_image_url_content() -> None:
    provider = _provider()
    body = provider._completions.build_request(
        [
            HumanMessage(
                parts=[
                    ImageUrlBlock(url="https://example.com/screenshot.png"),
                ]
            )
        ],
        None,
        False,
        provider._merged_kwargs(),
    )

    assert body["messages"][0]["content"] == [
        {
            "type": "image_url",
            "image_url": {"url": "https://example.com/screenshot.png"},
        }
    ]


@pytest.mark.asyncio
@respx.mock
async def test_kimi_parses_function_call_for_agent_loop() -> None:
    route = respx.post(f"{KIMI_CODE_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-kimi",
                "created": 1,
                "model": "kimi-for-coding",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "I should use the tool.",
                            "tool_calls": [
                                {
                                    "id": "tool-1",
                                    "type": "function",
                                    "function": {
                                        "name": "run_task",
                                        "arguments": '{"path":"README.md"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )
    )
    provider = _provider()

    result = await provider.chat(
        [HumanMessage(content="Inspect README")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "run_task",
                    "description": "Run one task",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert route.called
    assert result.reasoning_content == "I should use the tool."
    assert result.tool_calls is not None
    assert result.tool_calls[0].function.name == "run_task"


def test_factory_builds_dedicated_kimi_provider() -> None:
    from app.agent.providers.factory import build_provider

    with patch(
        "app.agent.providers.factory.KimiCodeProvider", return_value=MagicMock()
    ) as mock_kimi:
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.MOONSHOT_API_KEY = MagicMock()
            mock_settings.MOONSHOT_API_KEY.get_secret_value.return_value = "secret"
            mock_settings.MOONSHOT_BASE_URL = ""
            build_provider("kimi:kimi-for-coding")

    assert mock_kimi.call_args.kwargs["base_url"] == KIMI_CODE_API_BASE


class _KimiModelsResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "data": [
                {
                    "id": "k3",
                    "context_length": 1048576,
                    "architecture": {
                        "input_modalities": ["text", "image", "video"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": ["tools", "reasoning_effort"],
                },
                {
                    "id": "k3-256k",
                    "context_length": 262144,
                    "architecture": {
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": ["tools", "reasoning_effort"],
                },
                {
                    "id": "kimi-for-coding",
                    "context_length": 262144,
                    "architecture": {
                        "input_modalities": ["text", "image", "video"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": ["tools"],
                },
            ]
        }


class _KimiModelsClient:
    calls: list[str] = []

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, headers: dict[str, str]):
        type(self).calls.append(url)
        return _KimiModelsResponse()


@pytest.mark.asyncio
async def test_kimi_discovery_normalizes_url_and_effective_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers import model_discovery
    from app.agent.providers.capabilities import (
        clear_runtime_model_capabilities,
        get_capabilities,
    )
    from app.agent.providers.catalog import find
    from app.agent.providers.model_metadata import (
        clear_runtime_model_metadata,
        get_effective_model_thinking,
        get_model_limits,
    )

    entry = find("kimi")
    assert entry is not None
    _KimiModelsClient.calls = []
    monkeypatch.delenv("KIMI_CODE_K3_CONTEXT_WINDOW", raising=False)
    monkeypatch.setattr(model_discovery.httpx, "AsyncClient", _KimiModelsClient)

    try:
        models = await model_discovery.discover_provider_models(
            entry,
            overrides={
                "MOONSHOT_API_KEY": "secret",
                "MOONSHOT_BASE_URL": "https://api.kimi.ai/v1",
            },
        )
        k3_limits = get_model_limits("kimi:k3")
        k3_caps = get_capabilities("kimi:k3")
        k3_thinking = get_effective_model_thinking("kimi:k3")
    finally:
        clear_runtime_model_metadata()
        clear_runtime_model_capabilities()

    assert models == ["k3", "k3-256k", "kimi-for-coding"]
    assert _KimiModelsClient.calls == [f"{KIMI_CODE_API_BASE}/models"]
    assert k3_limits.context_length == 262144
    assert k3_caps.input.vision is True
    assert k3_caps.input.video is False
    assert k3_thinking.levels == ("low", "high", "max")
    assert k3_thinking.default_level == "high"


def test_k3_one_million_context_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers.model_metadata import get_model_limits

    monkeypatch.setenv("KIMI_CODE_K3_CONTEXT_WINDOW", "1048576")

    assert get_model_limits("kimi:k3").context_length == 1048576
