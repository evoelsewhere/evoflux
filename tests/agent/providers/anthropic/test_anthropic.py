from __future__ import annotations

from pydantic import SecretStr

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.anthropic.anthropic import (
    _split_messages,
    _usage_from_anthropic,
)
from app.agent.schemas.chat import (
    AssistantMessage,
    HumanMessage,
    ImageDataBlock,
    SystemMessage,
    TextBlock,
    ToolMessage,
)


def test_anthropic_provider_requires_api_key() -> None:
    try:
        AnthropicProvider(api_key="", model="claude-sonnet-4-6")
    except ValueError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_anthropic_provider_accepts_secret_str() -> None:
    provider = AnthropicProvider(
        api_key=SecretStr("sk-ant-test"),
        model="claude-sonnet-4-6",
    )

    assert provider.api_key == "sk-ant-test"
    assert provider.base_url == "https://api.anthropic.com"


def test_anthropic_provider_accepts_custom_timeout() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4-6",
        timeout=None,
    )

    assert provider._timeout is None


def test_anthropic_payload_converts_system_tools_and_thinking() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4-6",
        model_kwargs={"thinking_level": "low", "max_tokens": 4096},
    )

    payload = provider._payload(
        [
            SystemMessage(content="be concise"),
            HumanMessage(content="hi"),
            AssistantMessage(content=None, tool_calls=[]),
            ToolMessage(tool_call_id="toolu_1", content="ok"),
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Lookup a value.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        provider._merged_kwargs(),
    )

    assert payload["system"] == [
        {
            "type": "text",
            "text": "be concise",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert payload["output_config"] == {"effort": "low"}
    assert "cache_control" not in payload


def test_anthropic_payload_splits_system_at_cache_boundary() -> None:
    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-4-6")

    payload = provider._payload(
        [
            SystemMessage(content="stable head||volatile tail"),
            HumanMessage(content="hi"),
        ],
        None,
        {**provider._merged_kwargs(), "cache_boundary": len("stable head||")},
    )

    assert payload["system"] == [
        {
            "type": "text",
            "text": "stable head||",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "volatile tail"},
    ]


def test_anthropic_payload_ignores_out_of_range_cache_boundary() -> None:
    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-4-6")

    payload = provider._payload(
        [SystemMessage(content="be concise")],
        None,
        {**provider._merged_kwargs(), "cache_boundary": 999},
    )

    assert payload["system"] == [
        {
            "type": "text",
            "text": "be concise",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_anthropic_payload_marks_cache_breakpoint_on_last_tool() -> None:
    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-4-6")

    payload = provider._payload(
        [HumanMessage(content="hi")],
        [
            {
                "type": "function",
                "function": {"name": "read", "parameters": {"type": "object"}},
            },
            {
                "type": "function",
                "function": {"name": "write", "parameters": {"type": "object"}},
            },
        ],
        provider._merged_kwargs(),
    )

    assert "cache_control" not in payload["tools"][0]
    assert payload["tools"][1]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_payload_marks_cache_breakpoint_on_last_message() -> None:
    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-4-6")

    payload = provider._payload(
        [
            HumanMessage(content="first"),
            AssistantMessage(content="ack", tool_calls=None),
            ToolMessage(tool_call_id="toolu_1", content="result"),
        ],
        None,
        provider._merged_kwargs(),
    )

    assert "cache_control" not in payload["messages"][0]["content"]
    last = payload["messages"][-1]["content"]
    assert last[-1]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_payload_allows_explicit_cache_opt_out() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4-6",
        model_kwargs={"cache_control": None},
    )

    payload = provider._payload(
        [SystemMessage(content="be concise"), HumanMessage(content="hi")],
        [
            {
                "type": "function",
                "function": {"name": "read", "parameters": {"type": "object"}},
            }
        ],
        provider._merged_kwargs(),
    )

    assert "cache_control" not in payload
    assert payload["system"] == "be concise"
    assert "cache_control" not in payload["tools"][0]
    assert payload["messages"][-1]["content"] == "hi"


def test_anthropic_usage_normalizes_read_write_and_total_input() -> None:
    usage = _usage_from_anthropic(
        {
            "input_tokens": 100,
            "cache_creation_input_tokens": 1_000,
            "cache_read_input_tokens": 900,
            "output_tokens": 10,
        }
    )

    assert usage is not None
    assert usage.prompt_tokens == 2_000
    assert usage.cached_tokens == 900
    assert usage.cache_write_tokens == 1_000
    assert usage.completion_tokens == 10
    assert usage.total_tokens == 2_010


def test_anthropic_non_stream_response_preserves_cache_usage() -> None:
    provider = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-4-6")
    provider.bind_provider_name("anthropic")

    result = provider._parse_response(
        {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 1_000,
                "cache_read_input_tokens": 900,
                "output_tokens": 10,
            },
        }
    )

    assert result.extra is not None
    assert result.extra["usage"]["input"] == 2_000
    assert result.extra["usage"]["cache"] == 900
    assert result.extra["usage"]["cache_write"] == 1_000


def test_anthropic_payload_uses_adaptive_thinking_for_claude_opus_4_7() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-opus-4-7",
        model_kwargs={"thinking_level": "medium", "max_tokens": 4096},
    )

    payload = provider._payload(
        [HumanMessage(content="hi")],
        None,
        provider._merged_kwargs(),
    )

    assert payload["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert payload["output_config"] == {"effort": "medium"}
    assert "budget_tokens" not in payload["thinking"]


def test_anthropic_payload_uses_manual_thinking_for_older_models() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4-5",
        model_kwargs={"thinking_level": "low", "max_tokens": 4096},
    )

    payload = provider._payload(
        [HumanMessage(content="hi")],
        None,
        provider._merged_kwargs(),
    )

    assert payload["thinking"] == {
        "type": "enabled",
        "budget_tokens": 1024,
        "display": "summarized",
    }
    assert "output_config" not in payload


def test_anthropic_payload_omits_incompatible_sampling_when_thinking() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4",
        model_kwargs={
            "thinking_level": "low",
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": 4096,
        },
    )

    payload = provider._payload(
        [HumanMessage(content="hi")],
        None,
        provider._merged_kwargs(),
    )

    assert payload["thinking"] == {
        "type": "enabled",
        "budget_tokens": 1024,
        "display": "summarized",
    }
    assert "temperature" not in payload
    assert "top_p" not in payload


def test_anthropic_payload_allows_supported_top_p_when_thinking() -> None:
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-sonnet-4",
        model_kwargs={
            "thinking_level": "low",
            "temperature": 0.2,
            "top_p": 0.95,
            "max_tokens": 4096,
        },
    )

    payload = provider._payload(
        [HumanMessage(content="hi")],
        None,
        provider._merged_kwargs(),
    )

    assert "temperature" not in payload
    assert payload["top_p"] == 0.95


def test_anthropic_human_message_preserves_image_parts() -> None:
    _, messages = _split_messages(
        [
            HumanMessage(
                content="inspect attached",
                parts=[
                    TextBlock(text="[Attached image]"),
                    ImageDataBlock(data="aW1n", media_type="image/png"),
                ],
            )
        ]
    )

    assert messages == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "[Attached image]"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "aW1n",
                    },
                },
            ],
        }
    ]


def test_anthropic_tool_result_preserves_image_parts() -> None:
    _, messages = _split_messages(
        [
            ToolMessage(
                tool_call_id="toolu_image",
                content="[Image]",
                parts=[ImageDataBlock(data="aW1n", media_type="image/png")],
            )
        ]
    )

    result = messages[0]["content"][0]
    assert result["type"] == "tool_result"
    assert result["content"][0]["source"]["media_type"] == "image/png"
