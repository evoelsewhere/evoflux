"""ask_user — pause the task and ask the human one or more questions at once.

Presents the questions via a blocking SSE round-trip (mirrors plan-mode
approval): the frontend renders a question UI for the whole batch and POSTs
all replies together, which resolves the future this tool is awaiting.
"""

from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools.registry import Tool


class BrowserHandoffSpec(BaseModel):
    """Optional browser-native presentation for an AskUser question."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        pattern=r"^(take_over|confirm_action|provide_secret|choose_option)$"
    )
    title: str = Field(default="", max_length=120)
    action: str = Field(default="", max_length=500)
    consequence: str = Field(default="", max_length=1_000)
    target: str = Field(default="", max_length=500)


class AgentSpawnSpec(BaseModel):
    """Presentation metadata for a runtime agent-spawn confirmation."""

    model_config = ConfigDict(extra="forbid")

    blueprint: str = Field(min_length=1, max_length=100)
    default_model: str = Field(min_length=1, max_length=255)
    default_thinking_level: str | None = Field(default=None, max_length=50)


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
    #: When True the answer MUST be one of ``options`` — the reply endpoint
    #: rejects anything else with a 422. Workflow *gate* nodes set this (a
    #: gate's choices route edges, so a free-text answer would silently
    #: dead-end the branch); the ask_user tool leaves it False, where
    #: ``options`` are only soft suggestions over a free-text field.
    strict: bool = Field(default=False)
    browser_handoff: BrowserHandoffSpec | None = None
    kind: Literal["text", "agent_spawn"] = "text"
    agent_spawn: AgentSpawnSpec | None = None


class AskUserQuestionSpec(BaseModel):
    """Question fields exposed to the model-facing ``ask_user`` tool.

    ``strict`` is intentionally absent. Options from an ordinary agent are
    suggestions and the user may always type another answer. Workflow gates
    use :class:`QuestionSpec` directly when they need edge-safe strict choices.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="The question to show the user.")
    options: list[str] = Field(
        default_factory=list,
        description=(
            "Optional 2-4 short suggested answers, shown as quick-pick "
            "choices alongside a free-text field."
        ),
    )
    browser_handoff: BrowserHandoffSpec | None = None


async def _ask_user(questions: list[AskUserQuestionSpec]) -> str:
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
    soft_questions = [
        QuestionSpec(
            question=question.question,
            options=question.options,
            strict=False,
            browser_handoff=question.browser_handoff,
        )
        for question in questions
    ]
    answers = await svc.ask(soft_questions)
    logger.info("ask_user_answered session={} answers={}", svc.session_id, answers)
    return "\n".join(
        f"Q: {q.question}\nA: {a}"
        for q, a in zip(soft_questions, answers, strict=True)
    )


ask_user = Tool(
    _ask_user,
    name="ask_user",
    lead_only=True,
    # Deliberately not deferred. Asking a clarifying question is a first-turn
    # decision, and behind load_tool it cost an extra activation round before
    # the question could even be posed — so the model reliably chose plain
    # text instead, which ends the turn without ever prompting the user. Being
    # lead_only, its schema is only paid for on lead calls.
    description=(
        "Ask the user one or more clarifying questions mid-task and block "
        "until they answer all of them. Batch every question you need into "
        "one call rather than asking one at a time. Use when a task is "
        "ambiguous or has multiple reasonable interpretations, instead of "
        "guessing. Returns each question paired with the user's answer."
    ),
)
