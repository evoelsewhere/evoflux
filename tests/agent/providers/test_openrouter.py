from app.agent.providers.openrouter import _OpenRouterCompletionsHandler
from app.agent.schemas.chat import HumanMessage


def _handler() -> _OpenRouterCompletionsHandler:
    return _OpenRouterCompletionsHandler(
        "openai/gpt-5",
        "https://openrouter.ai/api/v1",
        {"Authorization": "Bearer test"},
    )


def test_openrouter_effort_uses_normalized_reasoning_object() -> None:
    body: dict = {}
    _handler().customize_thinking({"thinking_level": "high"}, body)
    assert body == {"reasoning": {"effort": "high"}}


def test_openrouter_none_explicitly_disables_reasoning() -> None:
    body: dict = {}
    _handler().customize_thinking({"thinking_level": "none"}, body)
    assert body == {"reasoning": {"enabled": False}}


def test_openrouter_forwards_session_affinity() -> None:
    body = _handler().build_request(
        [HumanMessage(content="hi")],
        None,
        True,
        {"session_id": "opaque-session"},
    )

    assert body["session_id"] == "opaque-session"


def test_openrouter_anthropic_enables_automatic_cache() -> None:
    handler = _OpenRouterCompletionsHandler(
        "anthropic/claude-sonnet-4.6",
        "https://openrouter.ai/api/v1",
        {"Authorization": "Bearer test"},
    )

    body = handler.build_request([HumanMessage(content="hi")], None, True, {})

    assert body["cache_control"] == {"type": "ephemeral"}
