"""ask_user — pause the task and ask the human one or more questions at once.

Presents the questions via a blocking SSE round-trip (mirrors plan-mode
approval): the frontend renders a question UI for the whole batch and POSTs
all replies together, which resolves the future this tool is awaiting.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.tools.registry import Tool


def normalize_question_options(options: list[str]) -> list[str]:
    """Drop blanks and duplicates while preserving the first spelling.

    A duplicated choice reaches the user as two identical buttons for one
    answer: selecting either lights both, and when a two-way question renders
    the same label twice the second branch becomes unreachable except through
    free text. Comparison ignores case and surrounding whitespace so
    "In-memory only" and "in-memory only " collapse.
    """

    seen: set[str] = set()
    unique: list[str] = []
    for option in options:
        label = option.strip()
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(label)
    return unique


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
    browser_handoff: BrowserHandoffSpec | None = None
    kind: Literal["text", "agent_spawn"] = "text"
    agent_spawn: AgentSpawnSpec | None = None

    @field_validator("options")
    @classmethod
    def _unique_options(cls, value: list[str]) -> list[str]:
        return normalize_question_options(value)


class AskUserQuestionSpec(BaseModel):
    """Question fields exposed to the model-facing ``ask_user`` tool.

    Options are suggestions and the user may always type another answer.
    Internal question kinds (``agent_spawn``) stay on :class:`QuestionSpec`.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="The question to show the user.")
    options: list[str] = Field(
        default_factory=list,
        description=(
            "Optional 2-4 short suggested answers, shown as quick-pick "
            "choices alongside a free-text field. Every option must be a "
            "distinct answer: a repeated choice renders as two identical "
            "buttons for one answer, and a two-way question whose branches "
            "read the same leaves the second unreachable."
        ),
    )
    browser_handoff: BrowserHandoffSpec | None = None

    @field_validator("options")
    @classmethod
    def _unique_options(cls, value: list[str]) -> list[str]:
        return normalize_question_options(value)


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
    soft_questions = [
        QuestionSpec(
            question=question.question,
            options=question.options,
            browser_handoff=question.browser_handoff,
        )
        for question in questions
    ]
    answers = await svc.ask(soft_questions)
    return "\n".join(
        f"Q: {q.question}\nA: {a}" for q, a in zip(soft_questions, answers, strict=True)
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
