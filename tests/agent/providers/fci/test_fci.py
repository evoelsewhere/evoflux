"""Contract tests for FPT AI Marketplace (FCI)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from app.agent.providers.fci import FCIProvider
from app.agent.providers.fci.fci import (
    FCI_API_BASE,
    _FCICompletionsHandler,
    _FCIResponsesHandler,
)
from app.agent.providers.openai import OpenAIProvider
from app.agent.schemas.chat import HumanMessage


def _provider(**kwargs) -> FCIProvider:
    return FCIProvider(api_key="fci-test-key", model="gpt-oss-120b", **kwargs)


def test_fci_is_a_responses_capable_openai_provider() -> None:
    assert issubclass(FCIProvider, OpenAIProvider)
    assert _provider()._use_responses is True


def test_fci_can_explicitly_force_chat_completions() -> None:
    provider = _provider(model_kwargs={"responses_api": False})
    assert provider._use_responses is False
    assert isinstance(provider._completions, _FCICompletionsHandler)


def test_fci_defaults_to_public_marketplace_base_url() -> None:
    assert _provider().base_url == FCI_API_BASE


@pytest.mark.parametrize(
    "configured",
    [
        "https://mkp-api.fptcloud.com",
        "https://mkp-api.fptcloud.com/",
        "  https://mkp-api.fptcloud.com  ",
    ],
)
def test_fci_normalizes_legacy_public_root_to_v1(configured: str) -> None:
    assert _provider(base_url=configured).base_url == FCI_API_BASE


def test_fci_preserves_dedicated_gateway_path() -> None:
    provider = _provider(base_url="https://dedicated.example.com/inference/v2/")

    assert provider.base_url == "https://dedicated.example.com/inference/v2"


def test_fci_responses_request_uses_only_supported_controls() -> None:
    provider = _provider()
    assert isinstance(provider._responses, _FCIResponsesHandler)
    body = provider._responses.build_request(
        [HumanMessage(content="run it")],
        [
            {
                "type": "function",
                "function": {
                    "name": "run_task",
                    "description": "Run one task",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        ],
        stream=True,
        merged={
            "thinking_level": "high",
            "prompt_cache_key": "unsupported-openai-field",
            "temperature": 0.2,
            "top_p": 0.8,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "response_format": {"type": "json_object"},
        },
    )

    assert "reasoning" not in body
    assert "prompt_cache_key" not in body
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.8
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is False
    assert body["text"] == {"format": {"type": "json_object"}}
    assert body["tools"][0]["strict"] is True


def test_fci_harmony_models_coerce_forced_tool_choice_to_auto() -> None:
    provider = _provider()
    body = provider._responses.build_request(
        [HumanMessage(content="run it")],
        None,
        stream=False,
        merged={
            "tool_choice": {"type": "function", "name": "run_task"},
        },
    )

    assert body["tool_choice"] == "auto"


def test_fci_chat_request_matches_marketplace_contract() -> None:
    provider = _provider(model_kwargs={"responses_api": False})
    body = provider._completions.build_request(
        [HumanMessage(content="ping")],
        [
            {
                "type": "function",
                "function": {
                    "name": "run_task",
                    "description": "Run one task",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        stream=True,
        merged={
            "max_tokens": 10,
            "thinking_level": "high",
            "top_k": 40,
            "presence_penalty": 0,
        },
    )

    assert body["max_tokens"] == 10
    assert "max_completion_tokens" not in body
    assert "stream_options" not in body
    assert "reasoning_effort" not in body
    assert body["top_k"] == 40
    assert body["presence_penalty"] == 0
    assert body["tools"][0]["function"]["name"] == "run_task"


def test_fci_unwraps_documented_chat_response_envelope() -> None:
    provider = _provider(model_kwargs={"responses_api": False})
    result = provider._completions.parse_response(
        {
            "code": 200,
            "message": "Chat completion successful",
            "data": {
                "id": "chatcmpl-fci",
                "created": 1_750_390_044,
                "model": "gpt-oss-120b",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        }
    )

    assert result.content == "pong"


def test_fci_accepts_legacy_content_only_stream_chunks() -> None:
    provider = _provider(model_kwargs={"responses_api": False})
    payload = provider._completions.normalize_stream_payload({"content": "hello"})

    assert payload["model"] == "gpt-oss-120b"
    assert payload["choices"][0]["delta"]["content"] == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_fci_default_chat_uses_responses_function_calling() -> None:
    route = respx.post(f"{FCI_API_BASE}/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp-fci",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "run_task",
                        "arguments": '{"path":"README.md"}',
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
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
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ],
        max_tokens=128,
    )

    assert route.called
    assert result.tool_calls is not None
    assert result.tool_calls[0].id == "call-1"
    assert result.tool_calls[0].function.name == "run_task"
    request = route.calls[0].request
    assert b'"max_output_tokens":128' in request.content
    assert b'"type":"function","name":"run_task"' in request.content


@pytest.mark.asyncio
@respx.mock
async def test_fci_streams_responses_function_calls_for_agent_loop() -> None:
    sse = "\n".join(
        [
            "event: response.created",
            'data: {"type":"response.created","response":{"id":"resp-fci"}}',
            "event: response.output_item.added",
            'data: {"type":"response.output_item.added","item":{"id":"fc-1","type":"function_call","name":"run_task"}}',
            "event: response.function_call_arguments.done",
            'data: {"type":"response.function_call_arguments.done","item_id":"fc-1","arguments":"{\\"path\\":\\"README.md\\"}"}',
            "event: response.completed",
            'data: {"type":"response.completed","response":{"id":"resp-fci","usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}}',
            "data: [DONE]",
            "",
        ]
    )
    route = respx.post(f"{FCI_API_BASE}/responses").mock(
        return_value=httpx.Response(
            200,
            text=sse,
            headers={"content-type": "text/event-stream"},
        )
    )
    provider = _provider()

    chunks = [
        chunk
        async for chunk in provider.stream(
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
    ]

    assert route.called
    tool_delta = chunks[0].choices[0].delta.tool_calls
    assert tool_delta is not None
    assert tool_delta[0].id == "fc-1"
    assert tool_delta[0].function.name == "run_task"
    assert tool_delta[0].function.arguments == '{"path":"README.md"}'
    assert chunks[1].usage is not None
    assert chunks[1].usage.total_tokens == 15


@pytest.mark.asyncio
@respx.mock
async def test_fci_forced_chat_posts_to_chat_endpoint_and_unwraps() -> None:
    route = respx.post(f"{FCI_API_BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 200,
                "message": "Chat completion successful",
                "data": {
                    "id": "chatcmpl-fci",
                    "model": "gpt-oss-120b",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "pong"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            },
        )
    )
    provider = _provider(model_kwargs={"responses_api": False})

    result = await provider.chat([HumanMessage(content="ping")], max_tokens=1)

    assert route.called
    assert result.content == "pong"
    assert b'"max_tokens":1' in route.calls[0].request.content


def test_factory_uses_fci_public_base_url_when_setting_is_blank() -> None:
    from app.agent.providers.factory import build_provider

    with patch(
        "app.agent.providers.factory.FCIProvider", return_value=MagicMock()
    ) as mock_fci:
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.FCI_API_KEY = MagicMock()
            mock_settings.FCI_API_KEY.get_secret_value.return_value = "secret"
            mock_settings.FCI_BASE_URL = ""
            build_provider("fci:gpt-oss-120b")

    assert mock_fci.call_args.kwargs["base_url"] == FCI_API_BASE


class _FCIModelsResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "code": 200,
            "message": "Models listed",
            "data": {
                "data": [
                    {
                        "id": "agent-model",
                        "context_length": 262144,
                        "top_provider": {"max_completion_tokens": 32768},
                        "architecture": {
                            "input_modalities": ["image", "text"],
                            "output_modalities": ["text"],
                        },
                        "supported_parameters": ["tools", "temperature"],
                    },
                    {
                        "id": "Qwen2.5-VL-7B-Instruct",
                        "architecture": {
                            "input_modalities": ["image", "text"],
                            "output_modalities": ["text"],
                        },
                        "supported_parameters": ["temperature"],
                    },
                ]
            },
        }


class _FCIModelsClient:
    calls: list[tuple[str, dict[str, str]]] = []

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, headers: dict[str, str]):
        type(self).calls.append((url, headers))
        return _FCIModelsResponse()


@pytest.mark.asyncio
async def test_fci_discovery_unwraps_envelope_and_requires_live_tools(
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
        get_model_limits,
        get_model_thinking_levels,
    )

    entry = find("fci")
    assert entry is not None
    _FCIModelsClient.calls = []
    monkeypatch.setattr(model_discovery.httpx, "AsyncClient", _FCIModelsClient)

    try:
        models = await model_discovery.discover_provider_models(
            entry,
            overrides={
                "FCI_API_KEY": "secret",
                "FCI_BASE_URL": "https://mkp-api.fptcloud.com",
            },
        )
        limits = get_model_limits("fci:agent-model")
        capabilities = get_capabilities("fci:agent-model")
        thinking_levels = get_model_thinking_levels("fci:agent-model")
    finally:
        clear_runtime_model_metadata()
        clear_runtime_model_capabilities()

    assert models == ["agent-model"]
    assert limits.context_length == 262144
    assert limits.max_completion_tokens == 32768
    assert capabilities.input.vision is True
    assert capabilities.output.text is True
    assert thinking_levels == ()
    assert _FCIModelsClient.calls == [
        (
            f"{FCI_API_BASE}/models",
            {"Authorization": "Bearer secret"},
        )
    ]
