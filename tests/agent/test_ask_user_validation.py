"""Gate-reply validation: a strict question (workflow gate) rejects an answer
that isn't one of its declared choices, and enforces one answer per question.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.ask_user import AskUserService
from app.agent.tools.builtin.ask_user import (
    AskUserQuestionSpec,
    QuestionSpec,
    _ask_user,
    ask_user,
)


@pytest.mark.asyncio
async def test_validate_answers_enforces_strict_choices_and_arity():
    svc = AskUserService("sess-1")
    task = asyncio.create_task(
        svc.ask(
            [
                QuestionSpec(
                    question="Cut over?", options=["cutover", "hold"], strict=True
                )
            ]
        )
    )
    await asyncio.sleep(0)  # let ask() register the pending request
    request_id = next(iter(svc._pending))

    # Off-menu answer to a strict gate -> rejected (would strand the run).
    assert svc.validate_answers(request_id, ["maybe"]) is not None
    # Wrong number of answers -> rejected.
    assert svc.validate_answers(request_id, ["cutover", "extra"]) is not None
    # A declared choice -> accepted.
    assert svc.validate_answers(request_id, ["cutover"]) is None

    svc.reply(request_id, ["cutover"])
    assert await task == ["cutover"]


@pytest.mark.asyncio
async def test_validate_answers_allows_free_text_when_not_strict():
    svc = AskUserService("sess-2")
    task = asyncio.create_task(
        svc.ask([QuestionSpec(question="Name?", options=["a", "b"], strict=False)])
    )
    await asyncio.sleep(0)
    request_id = next(iter(svc._pending))

    # ask_user suggestions are soft: a free-text answer is fine.
    assert svc.validate_answers(request_id, ["something else"]) is None

    svc.reply(request_id, ["something else"])
    await task


@pytest.mark.asyncio
async def test_model_facing_ask_user_options_are_always_soft(monkeypatch):
    captured: list[QuestionSpec] = []

    class _Service:
        session_id = "sess-tool"

        async def ask(self, questions: list[QuestionSpec]) -> list[str]:
            captured.extend(questions)
            return ["a different answer"]

    monkeypatch.setattr(
        "app.agent.ask_user.get_ask_user_service",
        lambda: _Service(),
    )

    result = await _ask_user(
        [AskUserQuestionSpec(question="Choose?", options=["one", "two"])]
    )

    assert captured[0].strict is False
    assert result == "Q: Choose?\nA: a different answer"
    question_items = ask_user.definition["function"]["parameters"]["properties"][
        "questions"
    ]["items"]["properties"]
    assert "strict" not in question_items


def test_browser_handoff_metadata_is_typed_and_secret_free():
    question = QuestionSpec.model_validate(
        {
            "question": "Complete sign-in, then continue.",
            "options": ["completed", "cancelled"],
            "strict": True,
            "browser_handoff": {
                "kind": "provide_secret",
                "title": "Sign in",
                "target": "Password field",
            },
        }
    )
    assert question.browser_handoff is not None
    assert question.browser_handoff.kind == "provide_secret"
    assert "value" not in question.browser_handoff.model_dump()
