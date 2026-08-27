"""QwenCloud provider contract tests (AC-1 through AC-5)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app.agent.providers.capabilities import get_capabilities
from app.agent.providers.model_metadata import (
    get_model_features,
    get_model_limits,
    get_model_thinking_levels,
)
from app.agent.providers.openai import OpenAIProvider
from app.agent.providers.qwencloud import QWENCLOUD_API_BASE, QwenCloudProvider
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)


def _provider(
    *,
    model: str = "qwen3.8-max",
    base_url: str = QWENCLOUD_API_BASE,
    model_kwargs: dict[str, object] | None = None,
) -> QwenCloudProvider:
    return QwenCloudProvider(
        api_key="sk-ws-test",
        model=model,
        base_url=base_url,
        model_kwargs=model_kwargs,
    )


def test_qwencloud_provider_identity_and_default_endpoint() -> None:
    provider = _provider()

    assert isinstance(provider, OpenAIProvider)
    assert provider.base_url == QWENCLOUD_API_BASE
    assert QWENCLOUD_API_BASE == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )


def test_qwencloud_provider_accepts_plan_base_url() -> None:
    base_url = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/"

    assert _provider(base_url=base_url).base_url == base_url.rstrip("/")


def test_qwencloud_active_effort_routes_to_responses_api() -> None:
    assert _provider(model_kwargs={"thinking_level": "xhigh"})._use_responses is True


def test_qwencloud_explicit_chat_completions_override_is_honored() -> None:
    provider = _provider(
        model_kwargs={"thinking_level": "high", "responses_api": False}
    )

    assert provider._use_responses is False


def test_chat_request_preserves_reasoning_content_across_tool_turn() -> None:
    provider = _provider(model_kwargs={"responses_api": False})
    messages = [
        HumanMessage(content="Use the tool"),
        AssistantMessage(
            reasoning_content="I should inspect the workspace.",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=FunctionCall(name="inspect", arguments='{"path":"."}'),
                )
            ],
        ),
        ToolMessage(tool_call_id="call_1", content="result"),
    ]

    body = provider._completions.build_request(
        messages,
        tools=None,
        stream=False,
        merged=provider._merged_kwargs(),
    )

    assert body["messages"][1]["reasoning_content"] == (
        "I should inspect the workspace."
    )
    assert body["preserve_thinking"] is True
    assert body["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert body["messages"][2]["tool_call_id"] == "call_1"


def test_chat_request_preserves_reasoning_on_completed_assistant_turn() -> None:
    provider = _provider(model_kwargs={"responses_api": False})

    body = provider._completions.build_request(
        [AssistantMessage(content="Answer", reasoning_content="Private trace")],
        tools=None,
        stream=False,
        merged=provider._merged_kwargs(),
    )

    assert body["messages"][0] == {
        "role": "assistant",
        "content": "Answer",
        "reasoning_content": "Private trace",
    }
    assert body["preserve_thinking"] is True


@pytest.mark.parametrize("level", ["none", "off"])
def test_chat_request_explicit_off_disables_thinking(level: str) -> None:
    provider = _provider(model_kwargs={"thinking_level": level, "responses_api": False})

    body = provider._completions.build_request(
        [HumanMessage(content="hi")],
        tools=None,
        stream=False,
        merged=provider._merged_kwargs(),
    )

    assert body["enable_thinking"] is False
    assert "reasoning_effort" not in body


def test_chat_request_named_effort_uses_qwen_wire_field() -> None:
    provider = _provider(
        model_kwargs={"thinking_level": "xhigh", "responses_api": False}
    )

    body = provider._completions.build_request(
        [HumanMessage(content="hi")],
        tools=None,
        stream=False,
        merged=provider._merged_kwargs(),
    )

    assert body["reasoning_effort"] == "xhigh"
    assert body["enable_thinking"] is True


def test_responses_request_disables_server_storage_and_sets_effort() -> None:
    provider = _provider(model_kwargs={"thinking_level": "medium"})

    body = provider._responses.build_request(
        [HumanMessage(content="hi")],
        tools=None,
        stream=True,
        merged=provider._merged_kwargs(),
    )

    assert body["store"] is False
    assert body["reasoning"] == {"effort": "medium"}
    assert body["stream"] is True


def test_responses_non_streaming_reasoning_text_is_normalized() -> None:
    provider = _provider(model_kwargs={"thinking_level": "medium"})

    message = provider._responses.parse_response(
        {
            "id": "resp_qwen",
            "output": [
                {
                    "type": "reasoning",
                    "content": [{"type": "reasoning_text", "text": "Work it out."}],
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Done."}],
                },
            ],
            "usage": {
                "input_tokens": 4,
                "output_tokens": 6,
                "total_tokens": 10,
            },
        }
    )

    assert message.reasoning_content == "Work it out."
    assert message.content == "Done."


@pytest.mark.asyncio
async def test_responses_stream_normalizes_reasoning_and_output_call_id() -> None:
    provider = _provider(model_kwargs={"thinking_level": "medium"})

    class FakeResponse:
        async def aiter_lines(self):
            events = [
                {
                    "type": "response.created",
                    "response": {"id": "resp_qwen"},
                },
                {
                    "type": "response.reasoning_text.delta",
                    "delta": "Need a tool.",
                },
                {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "function_call",
                        "id": "fc_item_1",
                        "call_id": "call_1",
                        "name": "inspect",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_item_1",
                    "delta": '{"path":',
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_item_1",
                    "delta": '"."}',
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_item_1",
                    "arguments": '{"path":"."}',
                },
            ]
            for event in events:
                yield f"data: {json.dumps(event)}"
            yield "data: [DONE]"

    chunks = [
        chunk async for chunk in provider._responses._parse_stream(FakeResponse())
    ]

    assert chunks[0].choices[0].delta.reasoning_content == "Need a tool."
    tool_chunks = [
        chunk.choices[0].delta.tool_calls[0]
        for chunk in chunks[1:]
        if chunk.choices and chunk.choices[0].delta.tool_calls
    ]
    assert [tool.id for tool in tool_chunks] == ["call_1", "call_1", "call_1"]
    assert tool_chunks[0].function is not None
    assert tool_chunks[0].function.arguments == '{"path":'
    assert tool_chunks[1].function is not None
    assert tool_chunks[1].function.arguments == '"."}'
    assert tool_chunks[2].function is not None
    assert tool_chunks[2].function.name == "inspect"


def test_qwen38_uses_max_completion_tokens() -> None:
    provider = QwenCloudProvider(
        api_key="sk-ws-test",
        model="qwen3.8-max",
        max_tokens=4096,
        model_kwargs={"responses_api": False},
    )

    body = provider._completions.build_request(
        [HumanMessage(content="hi")],
        tools=None,
        stream=False,
        merged=provider._merged_kwargs(),
    )

    assert body["max_completion_tokens"] == 4096
    assert "max_tokens" not in body


def test_older_qwen_models_keep_legacy_max_tokens() -> None:
    provider = QwenCloudProvider(
        api_key="sk-ws-test",
        model="qwen3-coder-plus",
        max_tokens=4096,
        model_kwargs={"responses_api": False},
    )

    body = provider._completions.build_request(
        [HumanMessage(content="hi")],
        tools=None,
        stream=False,
        merged=provider._merged_kwargs(),
    )

    assert body["max_tokens"] == 4096
    assert "max_completion_tokens" not in body


def test_chat_response_normalizes_reasoning_tools_and_usage() -> None:
    provider = _provider(model_kwargs={"responses_api": False})

    message = provider._completions.parse_response(
        {
            "id": "chatcmpl_qwen",
            "created": 1,
            "model": "qwen3.8-max",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "reasoning_content": "Need a tool.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "inspect",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        }
    )

    assert message.reasoning_content == "Need a tool."
    assert message.tool_calls is not None
    assert message.tool_calls[0].function.name == "inspect"
    assert message.extra is not None
    assert message.extra["usage"]["thoughts"] == 3


def test_factory_builds_qwencloud_with_default_endpoint() -> None:
    from app.agent.providers.factory import build_provider

    with patch(
        "app.agent.providers.factory.QwenCloudProvider",
        return_value=MagicMock(),
    ) as mock_qwencloud:
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = SecretStr("sk-ws-factory")
            mock_settings.DASHSCOPE_BASE_URL = ""
            build_provider(
                "qwencloud:qwen3.8-max",
                model_kwargs={"thinking_level": "xhigh"},
            )

    assert mock_qwencloud.call_args.kwargs == {
        "api_key": "sk-ws-factory",
        "model": "qwen3.8-max",
        "base_url": QWENCLOUD_API_BASE,
        "model_kwargs": {"thinking_level": "xhigh"},
    }


def test_factory_uses_qwencloud_base_url_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers.factory import build_provider

    plan_url = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    monkeypatch.setenv("DASHSCOPE_BASE_URL", plan_url)
    with patch(
        "app.agent.providers.factory.QwenCloudProvider",
        return_value=MagicMock(),
    ) as mock_qwencloud:
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = SecretStr("sk-sp-plan")
            mock_settings.DASHSCOPE_BASE_URL = ""
            build_provider("qwencloud:qwen3.8-flash")

    assert mock_qwencloud.call_args.kwargs["base_url"] == plan_url


def test_factory_requires_qwencloud_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.providers.factory import build_provider

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.DASHSCOPE_API_KEY = None
        mock_settings.DASHSCOPE_BASE_URL = ""
        with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
            build_provider("qwencloud:qwen3.8-max")


def test_qwencloud_catalog_and_cli_contract() -> None:
    from app.agent.providers.catalog import find
    from app.cli.commands.init import _PROVIDER_KEY_VAR, _PROVIDER_MODELS

    entry = find("qwencloud")

    assert entry is not None
    assert entry["env_var"] == "DASHSCOPE_API_KEY"
    assert entry["models_dev_provider_id"] == "alibaba"
    assert entry["credentials"][1]["name"] == "DASHSCOPE_BASE_URL"
    assert entry["credentials"][1]["secret"] is False
    assert _PROVIDER_KEY_VAR["qwencloud"] == "DASHSCOPE_API_KEY"
    assert "qwen3.8-max" in _PROVIDER_MODELS["qwencloud"]


def test_qwencloud_settings_fields() -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.DASHSCOPE_API_KEY is None
    assert settings.DASHSCOPE_BASE_URL == QWENCLOUD_API_BASE


def test_qwencloud_qwen38_max_metadata_and_effective_thinking() -> None:
    assert get_capabilities("qwencloud:qwen3.8-max").input.vision is True
    assert get_model_features("qwencloud:qwen3.8-max").tool_call is True
    assert get_model_limits("qwencloud:qwen3.8-max").context_length == 1_000_000
    assert get_model_thinking_levels("qwencloud:qwen3.8-max") == (
        "none",
        "low",
        "medium",
        "xhigh",
    )


def test_qwencloud_preview_alias_reuses_production_metadata() -> None:
    assert get_model_limits("qwencloud:qwen3.8-max-preview") == get_model_limits(
        "qwencloud:qwen3.8-max"
    )
