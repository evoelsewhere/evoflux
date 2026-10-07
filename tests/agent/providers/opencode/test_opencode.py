"""Tests for the OpenCode Zen / OpenCode Go providers.

Covers:
- registry: documented per-model routing (``model_transports``) for Zen and Go
- build_provider: one provider ID resolves to a different adapter per model
- Messages adapter: base URL has no doubled ``/v1``, Bearer header is sent
- Gemini adapter: Zen-only URL shape and dual auth headers
- Completions handler: ``max_tokens`` field and ``reasoning_content`` echo
- discovery: models whose protocol a plan does not serve are not listed
"""

from __future__ import annotations

import pytest

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.factory import build_provider
from app.agent.providers.model_discovery import is_agent_model_id
from app.agent.providers.opencode import (
    OpenCodeGeminiProvider,
    OpenCodeMessagesProvider,
    OpenCodeProvider,
    opencode_transport,
)
from app.agent.providers.opencode.opencode import _OpenCodeCompletionsHandler
from app.agent.providers.registry import Transport, resolve_base_url, resolve_provider
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)

ZEN = "https://opencode.ai/zen/v1"
GO = "https://opencode.ai/zen/go/v1"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "oc-test-key")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "oc-test-key")
    monkeypatch.delenv("OPENCODE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCODE_GO_BASE_URL", raising=False)


# ============================================================================
# Registry routing table
# ============================================================================


class TestRegistryRouting:
    @pytest.mark.parametrize(
        ("provider", "model", "expected"),
        [
            ("opencode", "claude-sonnet-5", Transport.ANTHROPIC),
            ("opencode", "qwen3.8-flash", Transport.ANTHROPIC),
            ("opencode", "gpt-5.5", Transport.OPENAI_RESPONSES),
            ("opencode", "gpt-6-sol", Transport.OPENAI_RESPONSES),
            ("opencode", "grok-4.7", Transport.OPENAI_RESPONSES),
            ("opencode", "muse-spark-1.3-contributor-free", Transport.OPENAI_RESPONSES),
            ("opencode", "gemini-3.5-flash", Transport.GOOGLE_GENAI),
            ("opencode", "kimi-k3", Transport.OPENAI_COMPLETIONS),
            ("opencode", "deepseek-v4-pro", Transport.OPENAI_COMPLETIONS),
            ("opencode", "big-pickle", Transport.OPENAI_COMPLETIONS),
            # ``grok-code`` is not a Grok 4 model and stays on completions.
            ("opencode", "grok-code", Transport.OPENAI_COMPLETIONS),
            ("opencode-go", "minimax-m3", Transport.ANTHROPIC),
            ("opencode-go", "qwen3.8-max", Transport.ANTHROPIC),
            ("opencode-go", "qwen3.7-plus", Transport.ANTHROPIC),
            ("opencode-go", "grok-4.6", Transport.OPENAI_RESPONSES),
            ("opencode-go", "gpt-6-luna", Transport.OPENAI_RESPONSES),
            ("opencode-go", "glm-5.3", Transport.OPENAI_COMPLETIONS),
            ("opencode-go", "kimi-k3", Transport.OPENAI_COMPLETIONS),
            ("opencode-go", "mimo-v2.5-pro", Transport.OPENAI_COMPLETIONS),
        ],
    )
    def test_documented_transport(self, provider, model, expected):
        assert opencode_transport(provider, model) is expected

    def test_zen_and_go_have_distinct_default_endpoints(self):
        zen = resolve_provider("opencode")
        go = resolve_provider("opencode-go")
        assert zen is not None and go is not None
        assert resolve_base_url(zen) == ZEN
        assert resolve_base_url(go) == GO
        # Separate credentials: saving a Go key must not connect Zen.
        assert zen.env_var == "OPENCODE_API_KEY"
        assert go.env_var == "OPENCODE_GO_API_KEY"

    def test_go_does_not_claim_gemini(self):
        go = resolve_provider("opencode-go")
        zen = resolve_provider("opencode")
        assert go is not None and zen is not None
        assert not go.speaks(Transport.GOOGLE_GENAI)
        assert zen.speaks(Transport.GOOGLE_GENAI)


# ============================================================================
# Factory: one provider ID, three adapters
# ============================================================================


class TestFactoryRouting:
    def test_claude_uses_messages_adapter(self):
        p = build_provider("opencode:claude-sonnet-5")
        assert isinstance(p, OpenCodeMessagesProvider)
        assert isinstance(p, AnthropicProvider)
        assert p.provider_name == "opencode"

    def test_gpt_uses_responses_endpoint(self):
        p = build_provider("opencode:gpt-5.5")
        assert isinstance(p, OpenCodeProvider)
        assert p._use_responses is True
        assert p.base_url == ZEN

    def test_responses_models_ignore_explicit_completions_flag(self):
        p = build_provider("opencode:gpt-5.5", {"responses_api": False})
        assert p._use_responses is True

    def test_open_models_stay_on_completions_even_with_thinking(self):
        p = build_provider("opencode-go:kimi-k3", {"thinking_level": "high"})
        assert isinstance(p, OpenCodeProvider)
        assert p._use_responses is False
        assert p.base_url == GO

    def test_gemini_uses_google_adapter_on_zen(self):
        p = build_provider("opencode:gemini-3.5-flash")
        assert isinstance(p, OpenCodeGeminiProvider)
        assert p._build_url("streamGenerateContent") == (
            f"{ZEN}/models/gemini-3.5-flash:streamGenerateContent"
        )

    def test_go_minimax_uses_messages_adapter_on_go_host(self):
        p = build_provider("opencode-go:minimax-m3")
        assert isinstance(p, OpenCodeMessagesProvider)
        assert p.base_url == "https://opencode.ai/zen/go"
        assert p.provider_name == "opencode-go"

    def test_base_url_env_overrides_each_plan_independently(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_GO_BASE_URL", "https://proxy.example/go/v1")
        assert build_provider("opencode-go:kimi-k3").base_url == (
            "https://proxy.example/go/v1"
        )
        assert build_provider("opencode:kimi-k3").base_url == ZEN

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY")
        from app.core.config import settings

        if getattr(settings, "OPENCODE_API_KEY", None):
            pytest.skip("OPENCODE_API_KEY configured through settings")
        with pytest.raises(ValueError, match="API key"):
            build_provider("opencode:kimi-k3")

    def test_each_plan_reads_only_its_own_key(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "zen-key")
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
        assert build_provider("opencode:kimi-k3").api_key == "zen-key"
        assert build_provider("opencode-go:kimi-k3").api_key == "go-key"

    def test_go_key_alone_does_not_connect_zen(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY")
        from app.core.config import settings

        if getattr(settings, "OPENCODE_API_KEY", None):
            pytest.skip("OPENCODE_API_KEY configured through settings")
        with pytest.raises(ValueError, match="API key"):
            build_provider("opencode:claude-sonnet-5")
        assert build_provider("opencode-go:kimi-k3").api_key == "oc-test-key"

    def test_zen_key_alone_does_not_connect_go(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_GO_API_KEY")
        from app.core.config import settings

        if getattr(settings, "OPENCODE_GO_API_KEY", None):
            pytest.skip("OPENCODE_GO_API_KEY configured through settings")
        with pytest.raises(ValueError, match="API key"):
            build_provider("opencode-go:kimi-k3")


# ============================================================================
# Messages / Gemini adapter wire details
# ============================================================================


class TestMessagesAdapter:
    def test_endpoint_has_single_v1(self):
        p = build_provider("opencode:claude-sonnet-5")
        assert (
            f"{p.base_url}{p._messages_path}" == "https://opencode.ai/zen/v1/messages"
        )
        go = build_provider("opencode-go:minimax-m3")
        assert f"{go.base_url}{go._messages_path}" == (
            "https://opencode.ai/zen/go/v1/messages"
        )

    def test_sends_both_native_and_bearer_auth(self):
        p = build_provider("opencode:claude-sonnet-5")
        assert p.headers["x-api-key"] == "oc-test-key"
        assert p.headers["Authorization"] == "Bearer oc-test-key"
        assert "anthropic-version" in p.headers


class TestGeminiAdapter:
    def test_sends_both_native_and_bearer_auth(self):
        p = build_provider("opencode:gemini-3.5-flash")
        headers = p._auth_headers()
        assert headers["x-goog-api-key"] == "oc-test-key"
        assert headers["Authorization"] == "Bearer oc-test-key"


# ============================================================================
# Completions handler quirks
# ============================================================================


class TestCompletionsHandler:
    def _tool_turn(self) -> list:
        call = ToolCall(id="c1", function=FunctionCall(name="f", arguments="{}"))
        return [
            HumanMessage(content="hi"),
            AssistantMessage(
                content=None, reasoning_content="call the tool", tool_calls=[call]
            ),
            ToolMessage(content="result", tool_call_id="c1"),
        ]

    def test_uses_opencode_handler(self):
        p = build_provider("opencode-go:kimi-k3")
        assert isinstance(p._completions, _OpenCodeCompletionsHandler)
        assert p._completions.provider_id == "opencode-go"

    def test_sends_max_tokens_not_max_completion_tokens(self):
        p = build_provider("opencode-go:glm-5.3", {"max_tokens": 512})
        body = p._completions.build_request(
            [HumanMessage(content="hi")], None, False, p._merged_kwargs()
        )
        assert body["max_tokens"] == 512
        assert "max_completion_tokens" not in body

    @pytest.mark.parametrize(
        "ref",
        [
            "opencode-go:deepseek-v4-pro",
            "opencode:kimi-k3",
            "opencode:mimo-v2.5-free",
        ],
    )
    def test_reasoning_content_echoed_for_interleaved_models(self, ref):
        p = build_provider(ref)
        body = p._completions.build_request(
            self._tool_turn(), None, False, p._merged_kwargs()
        )
        assistant = [m for m in body["messages"] if m["role"] == "assistant"]
        assert assistant[0]["reasoning_content"] == "call the tool"

    def test_reasoning_content_not_sent_to_models_that_do_not_need_it(self):
        p = build_provider("opencode:qwen3-coder")
        assert p._echo_reasoning is False
        body = p._completions.build_request(
            self._tool_turn(), None, False, p._merged_kwargs()
        )
        assert all("reasoning_content" not in m for m in body["messages"])

    def test_echo_survives_an_empty_assistant_turn_in_history(self):
        """The base conversion drops contentless turns; the echo must realign."""
        p = build_provider("opencode-go:deepseek-v4-pro")
        messages = [
            HumanMessage(content="a"),
            AssistantMessage(content=None, reasoning_content="dropped"),
            HumanMessage(content="b"),
            AssistantMessage(content="done", reasoning_content="kept"),
        ]
        body = p._completions.build_request(messages, None, False, p._merged_kwargs())
        assistant = [m for m in body["messages"] if m["role"] == "assistant"]
        assert [m["content"] for m in assistant] == ["done"]
        assert assistant[0]["reasoning_content"] == "kept"


# ============================================================================
# Discovery
# ============================================================================


class TestClientHeaders:
    """OpenCode's gateways expect their own client's tagging headers."""

    SESSION = "evoflux-v1:abc123"

    def _merged(self, p, **extra):
        return p._merged_kwargs(cache_probe_scope=self.SESSION, **extra)

    def _assert_tagged(self, headers: dict[str, str]) -> None:
        assert headers["x-opencode-session"] == self.SESSION
        assert headers["x-opencode-session-id"] == self.SESSION
        assert headers["x-opencode-client"] == "evoflux"
        assert headers["User-Agent"].startswith("EvoFlux/")
        assert len(headers["x-opencode-request"]) == 32
        # No header may be sent with an empty value.
        assert all(value for value in headers.values())

    def test_completions_requests_are_tagged(self):
        p = build_provider("opencode-go:kimi-k3")
        self._assert_tagged(p._completions._request_headers(self._merged(p)))

    def test_responses_requests_are_tagged(self):
        p = build_provider("opencode:gpt-5.5")
        headers = p._responses._request_headers(self._merged(p))
        self._assert_tagged(headers)
        assert headers["Authorization"] == "Bearer oc-test-key"

    def test_messages_requests_are_tagged(self):
        p = build_provider("opencode:claude-sonnet-5")
        headers = p._request_headers(self._merged(p))
        self._assert_tagged(headers)
        assert headers["x-api-key"] == "oc-test-key"

    def test_gemini_requests_are_tagged(self):
        p = build_provider("opencode:gemini-3.5-flash")
        p._call_context = self._merged(p)
        headers = p._auth_headers()
        self._assert_tagged(headers)
        assert headers["x-goog-api-key"] == "oc-test-key"

    def test_session_is_always_sent_because_the_gateway_requires_it(self):
        """No conversation (title generation, memory passes) is not "no session"."""
        p = build_provider("opencode:kimi-k3")
        headers = p._completions._request_headers(p._merged_kwargs())
        assert headers["x-opencode-session"].startswith("evoflux-v1:")
        assert headers["x-opencode-session-id"] == headers["x-opencode-session"]
        assert headers["x-opencode-client"] == "evoflux"
        assert all(value for value in headers.values())

    def test_fallback_session_is_stable_per_provider_and_unique_across_them(self):
        a = build_provider("opencode:kimi-k3")
        b = build_provider("opencode:kimi-k3")
        first = a._completions._request_headers(a._merged_kwargs())
        second = a._completions._request_headers(a._merged_kwargs())
        other = b._completions._request_headers(b._merged_kwargs())
        assert first["x-opencode-session"] == second["x-opencode-session"]
        assert first["x-opencode-session"] != other["x-opencode-session"]

    def test_conversation_key_wins_over_the_fallback(self):
        p = build_provider("opencode:kimi-k3")
        headers = p._completions._request_headers(self._merged(p))
        assert headers["x-opencode-session"] == self.SESSION

    @pytest.mark.parametrize(
        "ref",
        ["opencode:claude-sonnet-5", "opencode:gpt-5.5", "opencode:gemini-3.5-flash"],
    )
    def test_every_adapter_sends_a_session_without_a_conversation(self, ref):
        p = build_provider(ref)
        if ref.endswith("gemini-3.5-flash"):
            headers = p._auth_headers()
        elif hasattr(p, "_responses") and p._use_responses:
            headers = p._responses._request_headers(p._merged_kwargs())
        else:
            headers = p._request_headers(p._merged_kwargs())
        assert headers["x-opencode-session"].startswith("evoflux-v1:")

    def test_request_id_is_unique_per_call(self):
        p = build_provider("opencode:kimi-k3")
        merged = self._merged(p)
        first = p._completions._request_headers(merged)["x-opencode-request"]
        second = p._completions._request_headers(merged)["x-opencode-request"]
        assert first != second

    def test_raw_session_id_is_never_sent(self):
        p = build_provider("opencode:kimi-k3")
        headers = p._completions._request_headers(
            p._merged_kwargs(cache_probe_scope="evoflux-v1:deadbeef")
        )
        assert headers["x-opencode-session"].startswith("evoflux-v1:")


class TestAnonymousFreeTier:
    """OpenCode's client uses the public key for ``$0`` Zen models only."""

    @pytest.fixture(autouse=True)
    def _no_key(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
        from app.core.config import settings

        if getattr(settings, "OPENCODE_API_KEY", None):
            pytest.skip("OPENCODE_API_KEY configured through settings")

    def test_free_zen_model_builds_with_public_key(self):
        p = build_provider("opencode:big-pickle")
        assert p.api_key == "public"

    def test_paid_zen_model_still_requires_a_key(self):
        with pytest.raises(ValueError, match="API key"):
            build_provider("opencode:claude-sonnet-5")

    def test_go_has_no_anonymous_tier(self):
        from app.core.config import settings

        if getattr(settings, "OPENCODE_GO_API_KEY", None):
            pytest.skip("OPENCODE_GO_API_KEY configured through settings")
        with pytest.raises(ValueError, match="API key"):
            build_provider("opencode-go:longcat-2.5-preview-free")

    def test_configured_key_wins_over_public(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "oc-real")
        assert build_provider("opencode:big-pickle").api_key == "oc-real"


class TestDiscoveryFilter:
    def test_gemini_listed_on_zen(self):
        assert is_agent_model_id("opencode", "gemini-3.5-flash") is True

    def test_claude_listed_on_zen(self):
        assert is_agent_model_id("opencode", "claude-sonnet-5") is True
