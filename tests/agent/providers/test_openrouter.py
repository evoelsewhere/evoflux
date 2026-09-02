from app.agent.providers.openrouter import _OpenRouterCompletionsHandler
from app.agent.schemas.chat import HumanMessage, SystemMessage


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


def test_openrouter_anthropic_marks_cache_breakpoints_on_content_blocks() -> None:
    handler = _OpenRouterCompletionsHandler(
        "anthropic/claude-sonnet-4.6",
        "https://openrouter.ai/api/v1",
        {"Authorization": "Bearer test"},
    )

    body = handler.build_request(
        [SystemMessage(content="be concise"), HumanMessage(content="hi")],
        None,
        True,
        {},
    )

    assert "cache_control" not in body
    system_content = body["messages"][0]["content"]
    assert system_content[-1]["cache_control"] == {"type": "ephemeral"}
    last_content = body["messages"][-1]["content"]
    assert last_content[-1]["cache_control"] == {"type": "ephemeral"}


def test_openrouter_non_anthropic_model_has_no_cache_control() -> None:
    body = _handler().build_request([HumanMessage(content="hi")], None, True, {})

    assert "cache_control" not in body
    assert body["messages"][-1]["content"] == "hi"
