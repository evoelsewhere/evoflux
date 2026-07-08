"""Tests for the Xiaomi MiMo provider.

Covers:
- XiaomiProvider.__init__: inherits ChatCompletionsOnlyProvider
- _make_default_provider_factory: xiaomi branch reads XIAOMI_API_KEY, passes base_url
- thinking_level -> MiMo's `thinking` toggle (never `reasoning_effort`)
- reasoning_content echoed back on tool-call assistant messages (400 Param Incorrect fix)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.providers.xiaomi import XiaomiProvider

XIAOMI_API_BASE = "https://api.xiaomi.com/v1"


# ============================================================================
# XiaomiProvider class hierarchy
# ============================================================================


class TestXiaomiProviderInheritance:
    """XiaomiProvider must be a subclass of ChatCompletionsOnlyProvider."""

    def test_xiaomi_provider_is_subclass_of_chat_completions_only_provider(self):
        assert issubclass(XiaomiProvider, ChatCompletionsOnlyProvider)


# ============================================================================
# XiaomiProvider.__init__
# ============================================================================


class TestXiaomiProviderInit:
    """XiaomiProvider constructor wires base_url and delegates up the chain."""

    def _make_provider(self, **kwargs) -> XiaomiProvider:
        """Helper — patch httpx so no real network calls are made."""
        with patch("app.agent.providers.openai.openai.ResponsesHandler"):
            return XiaomiProvider(
                api_key="xiaomi-test-key",
                model="mimo-v2.5",
                base_url=XIAOMI_API_BASE,
                **kwargs,
            )

    def test_base_url_is_xiaomi(self):
        p = self._make_provider()
        assert p.base_url == XIAOMI_API_BASE

    def test_model_stored(self):
        p = self._make_provider()
        assert p.model == "mimo-v2.5"

    def test_api_key_stored(self):
        p = self._make_provider()
        assert p.api_key == "xiaomi-test-key"

    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="API key"):
            XiaomiProvider(api_key="", model="mimo-v2.5", base_url=XIAOMI_API_BASE)

    def test_thinking_level_stays_on_chat_completions(self):
        p = self._make_provider(model_kwargs={"thinking_level": "high"})
        assert p._use_responses is False

    def test_uses_xiaomi_completions_handler(self):
        from app.agent.providers.xiaomi.xiaomi import _XiaomiCompletionsHandler

        p = self._make_provider()
        assert isinstance(p._completions, _XiaomiCompletionsHandler)


# ============================================================================
# Provider factory — xiaomi branch
# ============================================================================


class TestXiaomiProviderFactory:
    """build_provider correctly builds XiaomiProvider for xiaomi: models."""

    def test_factory_calls_xiaomi_provider_with_correct_api_key_and_base_url(self):
        from app.agent.providers.factory import build_provider

        mock_provider = MagicMock()
        with patch(
            "app.agent.providers.factory.XiaomiProvider",
            return_value=mock_provider,
        ) as MockXiaomi:
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.XIAOMI_API_KEY = MagicMock()
                mock_settings.XIAOMI_API_KEY.get_secret_value.return_value = (
                    "xiaomi-secret"
                )
                mock_settings.XIAOMI_BASE_URL = ""
                build_provider("xiaomi:mimo-v2.5")

            MockXiaomi.assert_called_once()
            call_kwargs = MockXiaomi.call_args.kwargs
            assert call_kwargs.get("api_key") == "xiaomi-secret"
            assert call_kwargs.get("model") == "mimo-v2.5"
            assert call_kwargs.get("base_url") == XIAOMI_API_BASE

    def test_factory_respects_custom_base_url_env_var(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.setenv("XIAOMI_BASE_URL", "http://localhost:9000/v1")
        with patch(
            "app.agent.providers.factory.XiaomiProvider",
            return_value=MagicMock(),
        ) as MockXiaomi:
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.XIAOMI_API_KEY = MagicMock()
                mock_settings.XIAOMI_API_KEY.get_secret_value.return_value = "key"
                build_provider("xiaomi:mimo-v2.5-pro")

            assert (
                MockXiaomi.call_args.kwargs.get("base_url")
                == "http://localhost:9000/v1"
            )

    def test_factory_raises_when_xiaomi_api_key_missing(self, monkeypatch):
        from app.agent.providers.factory import build_provider

        monkeypatch.delenv("XIAOMI_API_KEY", raising=False)
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.XIAOMI_API_KEY = None
            with pytest.raises(ValueError, match="XIAOMI_API_KEY"):
                build_provider("xiaomi:mimo-v2.5")


# ============================================================================
# thinking_level -> MiMo's `thinking` toggle (never reasoning_effort)
# ============================================================================


class TestXiaomiThinking:
    """MiMo does not accept OpenAI's `reasoning_effort` field.

    The base `CompletionsHandler.customize_thinking` sends `reasoning_effort`
    whenever `thinking_level` is set — MiMo's handler must never send that
    field, and should only send `thinking: {type: disabled}` when thinking
    is explicitly turned off. MiMo reasons by default otherwise.
    """

    def _build_body(self, thinking_level: str | None = None) -> dict:
        from app.agent.schemas.chat import HumanMessage

        kwargs = {}
        if thinking_level is not None:
            kwargs["model_kwargs"] = {"thinking_level": thinking_level}
        p = XiaomiProvider(
            api_key="xiaomi-test-key",
            model="mimo-v2.5",
            base_url=XIAOMI_API_BASE,
            **kwargs,
        )
        return p._completions.build_request(
            [HumanMessage(content="hi")],
            None,
            stream=False,
            merged=p._merged_kwargs(),
        )

    def test_reasoning_effort_never_sent_when_thinking_level_high(self):
        body = self._build_body("high")
        assert "reasoning_effort" not in body
        assert "thinking" not in body

    def test_reasoning_effort_never_sent_when_thinking_level_absent(self):
        body = self._build_body()
        assert "reasoning_effort" not in body
        assert "thinking" not in body

    def test_thinking_disabled_sent_when_thinking_level_none(self):
        body = self._build_body("none")
        assert body.get("thinking") == {"type": "disabled"}
        assert "reasoning_effort" not in body

    def test_thinking_disabled_sent_when_thinking_level_off(self):
        body = self._build_body("off")
        assert body.get("thinking") == {"type": "disabled"}
        assert "reasoning_effort" not in body


# ============================================================================
# reasoning_content echoed back on tool-call assistant messages
# ============================================================================


class TestXiaomiReasoningContentEcho:
    """MiMo requires reasoning_content to be echoed back when a tool call was made.

    Documented at https://mimo.mi.com/docs/en-US/api/guidance/error-codes and
    reproduced at https://github.com/XiaomiMiMo/MiMo/issues/44: the first
    tool-calling request succeeds, but every subsequent request in that
    conversation returns 400 "Param Incorrect" unless reasoning_content is
    echoed back on the assistant's tool-call turn.
    """

    def _make_provider(self) -> XiaomiProvider:
        return XiaomiProvider(
            api_key="xiaomi-test-key", model="mimo-v2.5", base_url=XIAOMI_API_BASE
        )

    def test_reasoning_content_in_wire_body_on_tool_call_assistant_message(self):
        from app.agent.schemas.chat import (
            AssistantMessage,
            FunctionCall,
            HumanMessage,
            ToolCall,
            ToolMessage,
        )

        p = self._make_provider()
        tool_call = ToolCall(id="c1", function=FunctionCall(name="f", arguments="{}"))
        messages = [
            HumanMessage(content="hi"),
            AssistantMessage(
                content=None,
                reasoning_content="I should call the tool",
                tool_calls=[tool_call],
            ),
            ToolMessage(content="result", tool_call_id="c1"),
        ]
        body = p._completions.build_request(
            messages, None, stream=False, merged=p._merged_kwargs()
        )
        assistant_msg = body["messages"][1]
        assert assistant_msg.get("reasoning_content") == "I should call the tool"

    def test_reasoning_content_echoed_even_without_tool_calls(self):
        """Echo is not gated on tool_calls — see the orphaned-tool-call test below
        for why: gating on tool_calls silently dropped real reasoning_content
        for exactly the messages sanitize_openai_tool_pairs strips.
        """
        from app.agent.schemas.chat import AssistantMessage

        p = self._make_provider()
        messages = [
            AssistantMessage(content="answer", reasoning_content="some thoughts")
        ]
        body = p._completions.build_request(
            messages, None, stream=False, merged=p._merged_kwargs()
        )
        assert body["messages"][0].get("reasoning_content") == "some thoughts"

    def test_reasoning_content_absent_from_wire_body_when_none(self):
        from app.agent.schemas.chat import (
            AssistantMessage,
            FunctionCall,
            HumanMessage,
            ToolCall,
            ToolMessage,
        )

        p = self._make_provider()
        tool_call = ToolCall(id="c1", function=FunctionCall(name="f", arguments="{}"))
        messages = [
            HumanMessage(content="hi"),
            AssistantMessage(
                content=None, reasoning_content=None, tool_calls=[tool_call]
            ),
            ToolMessage(content="result", tool_call_id="c1"),
        ]
        body = p._completions.build_request(
            messages, None, stream=False, merged=p._merged_kwargs()
        )
        assert "reasoning_content" not in body["messages"][1]

    def test_reasoning_content_echoed_when_tool_calls_stripped_by_sanitize(self):
        """Reproduces a real production 400: an interrupted turn leaves an
        assistant message with a tool_call that never got a tool result.
        sanitize_openai_tool_pairs strips the orphaned tool_calls before this
        handler sees the message — reasoning_content must still be echoed, or
        the message ends up with nothing (content="") and MiMo rejects it:
        "messages[N] assistant must provide content, reasoning_content or
        tool_calls".
        """
        from app.agent.schemas.chat import AssistantMessage, FunctionCall, ToolCall

        p = self._make_provider()
        tool_call = ToolCall(
            id="orphan", function=FunctionCall(name="browser_use", arguments="{}")
        )
        messages = [
            AssistantMessage(
                content="",
                reasoning_content="Let me take a screenshot first.",
                tool_calls=[tool_call],
            ),
            # No matching ToolMessage for "orphan" — the turn was interrupted
            # before the tool ran.
        ]
        body = p._completions.build_request(
            messages, None, stream=False, merged=p._merged_kwargs()
        )
        wire_msg = body["messages"][0]
        assert "tool_calls" not in wire_msg  # confirms sanitize actually stripped it
        assert wire_msg.get("reasoning_content") == "Let me take a screenshot first."

    def test_fully_empty_assistant_message_gets_placeholder_content(self):
        """Belt-and-suspenders: if content, reasoning_content, and tool_calls
        are all genuinely empty, fall back to a non-empty placeholder rather
        than serialize a bare {"role": "assistant"} MiMo would reject.
        """
        from app.agent.schemas.chat import AssistantMessage

        p = self._make_provider()
        messages = [AssistantMessage(content=None, reasoning_content=None)]
        body = p._completions.build_request(
            messages, None, stream=False, merged=p._merged_kwargs()
        )
        wire_msg = body["messages"][0]
        assert wire_msg.get("content")
        assert "reasoning_content" not in wire_msg
        assert "tool_calls" not in wire_msg
