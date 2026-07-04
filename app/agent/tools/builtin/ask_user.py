"""ask_user — pause the task and ask the human one or more questions at once.

Presents the questions via a blocking SSE round-trip (mirrors plan-mode
approval): the frontend renders a question UI for the whole batch and POSTs
all replies together, which resolves the future this tool is awaiting.
"""

from __future__ import annotations

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.tools.registry import Tool


class QuestionSpec(BaseModel):
    """One question in a batch passed to ``ask_user``."""

    question: str = Field(description="The question to show the user.")
    options: list[str] = Field(
        default_factory=list,
        description=(
            "Optional 2-4 short suggested answers, shown as quick-pick "
            "choices alongside a free-text field. Omit for open-ended "
            "questions where suggesting options wouldn't help."
        ),
    )


async def _ask_user(questions: list[QuestionSpec]) -> str:
    """Ask the user one or more clarifying questions and wait for their answers.

    Use this whenever a task is ambiguous, underspecified, or has more than
    one reasonable interpretation — instead of guessing, ask. Prefer this
    over silently picking an assumption for anything that would be
    expensive or awkward to redo (irreversible actions, large refactors,
    a choice between genuinely different approaches).

    Batch every question you currently need into a single call instead of
    calling this tool repeatedly — the user answers them all at once.

    Blocks until the user answers all questions, then returns them paired
    with the user's answers so you can continue the task.

    Args:
        questions: One or more questions to ask in a single batch. Each has
            a ``question`` and optional ``options`` (2-4 quick-pick choices;
            the user can still type a free-text answer instead).
    """
    from app.agent.ask_user import get_ask_user_service

    svc = get_ask_user_service()
    logger.info(
        "ask_user_question session={} questions={}",
        svc.session_id,
        [q.question for q in questions],
    )
    answers = await svc.ask(questions)
    logger.info("ask_user_answered session={} answers={}", svc.session_id, answers)
    return "\n".join(
        f"Q: {q.question}\nA: {a}" for q, a in zip(questions, answers, strict=True)
    )


ask_user = Tool(
    _ask_user,
    name="ask_user",
    description=(
        "Ask the user one or more clarifying questions mid-task and block "
        "until they answer all of them. Batch every question you need into "
        "one call rather than asking one at a time. Use when a task is "
        "ambiguous or has multiple reasonable interpretations, instead of "
        "guessing. Returns each question paired with the user's answer."
    ),
)
