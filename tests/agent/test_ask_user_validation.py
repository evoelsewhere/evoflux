"""Gate-reply validation: a strict question (workflow gate) rejects an answer
that isn't one of its declared choices, and enforces one answer per question.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.ask_user import AskUserService
from app.agent.tools.builtin.ask_user import QuestionSpec


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
