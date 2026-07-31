from app.agent.providers.openrouter import _OpenRouterCompletionsHandler


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
