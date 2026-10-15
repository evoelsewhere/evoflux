"""Native SSE event schemas for EvoFlux streaming API.

Each event is serialised as::

    event: <type>
    data: <json>

The ``type`` field inside the JSON body mirrors the SSE ``event:`` line so
clients that parse only the ``data:`` payload can still distinguish events.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionEvent(BaseModel):
    """Emitted once at the start of a stream with the resolved session id."""

    type: Literal["session"] = "session"
    session_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThinkingEvent(BaseModel):
    """A reasoning/thinking chunk from an agent."""

    type: Literal["thinking"] = "thinking"
    agent: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageEvent(BaseModel):
    """A content chunk from an agent."""

    type: Literal["message"] = "message"
    agent: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallEvent(BaseModel):
    """First appearance of a tool call in the model delta stream.

    Emitted as soon as the LLM names a tool — before arguments are fully
    streamed and before execution begins.  Use this to show a pending tool
    card immediately.  Arguments may be absent or incomplete at this point.
    """

    type: Literal["tool_call"] = "tool_call"
    agent: str
    tool_call_id: str | None = None  # LLM-assigned call ID
    name: str  # internal function name
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolStartEvent(BaseModel):
    """Tool execution is about to begin — arguments are fully assembled.

    Emitted immediately before the tool function is called.  At this point
    the full arguments JSON is available.
    """

    type: Literal["tool_start"] = "tool_start"
    agent: str
    tool_call_id: str | None = None  # matches the tool_call event
    name: str  # internal function name
    arguments: str | None = None  # complete JSON arguments string
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolEndEvent(BaseModel):
    """Tool execution has completed."""

    type: Literal["tool_end"] = "tool_end"
    agent: str
    tool_call_id: str | None = None  # matches tool_call / tool_start
    name: str  # internal function name
    result: str | None = (
        None  # tool output (full; large results handled by ToolResultOffloadHook)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolOutputDeltaEvent(BaseModel):
    """A live output chunk emitted while a tool is still running."""

    type: Literal["tool_output_delta"] = "tool_output_delta"
    agent: str
    tool_call_id: str | None = None
    name: str
    text: str
    stream: Literal["stdout", "stderr", "combined"] = "combined"
    sequence: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsageEvent(BaseModel):
    """Token usage for a model call or turn."""

    type: Literal["usage"] = "usage"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int | None = None
    cache_write_tokens: int | None = None
    thoughts_tokens: int | None = None
    tool_use_tokens: int | None = None
    #: USD by cost component, priced from the models.dev catalog. Present on
    #: turn totals; ``None`` for providers billed by seat rather than token.
    cost: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalStatusEvent(BaseModel):
    """Latest durable goal snapshot for the session, or ``None`` when stopped."""

    type: Literal["goal_status"] = "goal_status"
    session_id: str
    goal: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SuggestedTaskEvent(BaseModel):
    """One parked suggestion changed state (raised, started, or dismissed).

    Carries the whole row rather than a delta: the dock renders from this
    without a refetch, and a client that missed an earlier event still ends
    up with the current state.
    """

    type: Literal["suggested_task"] = "suggested_task"
    session_id: str
    task: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class DoneEvent(BaseModel):
    """Stream complete."""

    type: Literal["done"] = "done"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnChangesEvent(BaseModel):
    """Files touched during the completed agent turn (Cursor-like Changes).

    Emitted just before or with turn completion so the UI can open a
    Changes review panel. ``files`` entries use workspace-relative paths.
    """

    type: Literal["turn_changes"] = "turn_changes"
    session_id: str
    additions: int = 0
    deletions: int = 0
    files: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RateLimitEvent(BaseModel):
    """Provider is rate-limited; client should retry after ``retry_after`` seconds."""

    type: Literal["rate_limit"] = "rate_limit"
    retry_after: int  # seconds until quota resets
    attempt: int  # current attempt number (1-based)
    max_attempts: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderStatusEvent(BaseModel):
    """Provider retry/exhaustion/fallback status for the active model call."""

    type: Literal["provider_status"] = "provider_status"
    agent: str
    status: Literal["retrying", "exhausted", "fallback"]
    model: str | None = None
    primary: str | None = None
    fallback: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    delay_seconds: float | None = None
    error_type: str | None = None
    status_code: int | None = None
    retry_after: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorEvent(BaseModel):
    """An unrecoverable error occurred."""

    type: Literal["error"] = "error"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentNotConfiguredEvent(BaseModel):
    """The agent is missing a provider/model — fixable from the UI.

    Emitted in place of :class:`ErrorEvent` when an agent loaded with the
    ``__PROVIDER_MODEL__`` placeholder is asked to run a turn. The
    frontend renders this as an actionable banner ("Open Settings →
    Providers to configure a model") rather than a stack-trace toast.
    """

    type: Literal["agent_not_configured"] = "agent_not_configured"
    agent: str
    message: str
    # ``action.type`` tells the frontend which CTA to render. Today only
    # ``open_settings`` is defined; new actions can be added without
    # breaking existing clients (frontend falls back to a no-op CTA).
    action: dict[str, Any] = Field(
        default_factory=lambda: {"type": "open_settings", "tab": "providers"}
    )


class AgentStatusEvent(BaseModel):
    """An agent changed lifecycle state."""

    type: Literal["agent_status"] = "agent_status"
    agent: str
    status: Literal["idle", "working", "offline", "error"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class TitleUpdateEvent(BaseModel):
    """Session title was generated and saved."""

    type: Literal["title_update"] = "title_update"
    title: str


class PermissionAskedEvent(BaseModel):
    """An agent is blocked awaiting permission to run a tool call.

    Only emitted when the tool call is actually waiting on a reply (mode
    handling is done backend-side) — the frontend should always display an
    approval UI and POST a reply to
    ``/team/{session_id}/permissions/{request_id}/reply``.
    """

    type: Literal["permission_asked"] = "permission_asked"
    request_id: str  # UUID — use as key in the reply endpoint
    session_id: str
    tool: str  # tool name (e.g. "shell", "bash")
    patterns: list[str]  # command fragments / path globs being requested
    #: What a reply of "always" would actually grant — usually broader than
    #: ``patterns`` (``git commit -m x`` approves ``git commit *``). Sent so
    #: the approval UI can say what it is about to allow instead of leaving
    #: the user to guess between this command, this tool, and forever.
    always_patterns: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PermissionRepliedEvent(BaseModel):
    """A permission request was resolved (by user or auto-allow)."""

    type: Literal["permission_replied"] = "permission_replied"
    request_id: str
    session_id: str
    reply: str  # "once" | "always" | "reject"
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionAskedEvent(BaseModel):
    """Agent is asking the user one or more clarifying questions mid-task.

    The frontend should display a question UI for the whole batch and POST
    a reply to ``/api/team/{session_id}/questions/{request_id}/reply`` with
    one answer per question, in order.

    Each item in ``questions`` has ``question`` and ``options``. Options are
    quick picks alongside a free-text fallback.
    """

    type: Literal["question_asked"] = "question_asked"
    request_id: str  # unique ID — included in the reply POST
    session_id: str
    questions: list[dict[str, Any]]  # [{question, options}, ...]
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionRepliedEvent(BaseModel):
    """An ask-user question batch was resolved (or cancelled by interrupt).

    Lets every connected client close its question UI (multi-tab dismiss).
    ``answers`` carries the user reply list when ``status`` is ``answered``;
    empty when cancelled by interrupt.
    """

    type: Literal["question_replied"] = "question_replied"
    request_id: str
    session_id: str
    status: str = "answered"  # "answered" | "cancelled"
    answers: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SummarizationStartEvent(BaseModel):
    """Context-window compaction (summarisation) has begun.

    Emitted by :class:`~app.agent.hooks.summarization.SummarizationHook`
    immediately before the summariser LLM call. The frontend renders a
    "Session compacting" divider in the active agent pane while this
    state holds.
    """

    type: Literal["summarization_start"] = "summarization_start"
    agent: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SummarizationContentEvent(BaseModel):
    """Legacy summary delta retained for wire compatibility.

    Current producers do not emit this event because generated summaries are
    internal model context rather than user-visible chat output.
    """

    type: Literal["summarization_content"] = "summarization_content"
    agent: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SummarizationEndEvent(BaseModel):
    """Compaction finished.

    ``metadata.error`` is set to ``True`` when the summariser failed —
    the frontend still transitions to "compacted" so the divider can
    clear, but may surface the error state distinctly. ``summary`` remains
    only for compatibility with older producers and is empty in new events.
    """

    type: Literal["summarization_end"] = "summarization_end"
    agent: str
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrowserSessionEvent(BaseModel):
    """Browser session state change — start, navigate, stop, etc.

    Emitted by the ``browser_use`` tool after every action that changes
    the browser session's observable state.  The frontend uses this to
    show/hide the "See Browser" button and update the BrowserViewer panel.
    """

    type: Literal["browser_session"] = "browser_session"
    agent: str
    active: bool
    action: str  # "started" | "navigated" | "stopped" | "tab_switched" | ...
    cdp_url: str | None = None
    cdp_http: str | None = None
    current_url: str | None = None
    current_title: str | None = None
    tabs: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WidgetDeltaEvent(BaseModel):
    """A live HTML chunk emitted while a widget is streaming.

    Emitted by the ``show_widget`` tool as tokens arrive. The frontend
    uses morphdom to diff and apply minimal DOM patches for smooth
    progressive rendering.
    """

    type: Literal["widget_delta"] = "widget_delta"
    agent: str
    tool_call_id: str
    html: str  # partial HTML content
    is_final: bool = False  # True when streaming complete
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── ui_block nodes (Feature B, spec §5.1) ─────────────────────────────────
# Server-side validated declarative UI blocks emitted by the ``ui_block``
# tool as one complete frame. Node models use extra="ignore"; all limits are
# enforced here so one SSE frame stays small, and unknown ``type`` values
# fail validation so the tool returns a friendly error instead of emitting
# a broken event.


class UiStatCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(max_length=80)
    value: str | int | float
    delta: str | None = Field(default=None, max_length=40)
    delta_tone: Literal["up", "down", "neutral"] = "neutral"
    hint: str | None = Field(default=None, max_length=160)


class UiStatCardsBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["stat_cards"] = "stat_cards"
    cards: list[UiStatCard] = Field(min_length=1, max_length=6)


class UiChartBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["chart"] = "chart"
    spec: dict[str, Any]  # ChartSpec (§4.1); frontend validates — see §8.3 stub rule


class UiStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(max_length=160)
    status: Literal["done", "active", "pending", "error"] = "pending"
    detail: str | None = Field(default=None, max_length=400)


class UiStepsBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["steps"] = "steps"
    steps: list[UiStep] = Field(min_length=1, max_length=12)
    description: str | None = Field(default=None, max_length=240)


class UiTableBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["table"] = "table"
    columns: list[dict[str, str]] = Field(min_length=1, max_length=12)
    rows: list[dict[str, Any]] = Field(max_length=200)


class UiKeyValueBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["key_value"] = "key_value"
    pairs: list[dict[str, str]] = Field(min_length=1, max_length=20)


class UiCalloutBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["callout"] = "callout"
    tone: Literal["info", "success", "warning", "error"] = "info"
    title: str | None = Field(default=None, max_length=120)
    body: str = Field(max_length=1000)


class UiButton(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(max_length=80)
    prompt: str = Field(max_length=500)
    style: Literal["primary", "secondary"] = "primary"


class UiButtonsBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["buttons"] = "buttons"
    buttons: list[UiButton] = Field(min_length=1, max_length=5)
    hint: str | None = Field(default=None, max_length=160)


class UiFormField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(max_length=40, pattern=r"^[a-z0-9_]{1,40}$")
    label: str = Field(max_length=80)
    kind: Literal["text", "textarea", "select", "checkbox"] = "text"
    options: list[str] = Field(default_factory=list, max_length=30)
    placeholder: str | None = Field(default=None, max_length=120)
    helper: str | None = Field(default=None, max_length=160)
    default: str | None = None


class UiFormBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["form"] = "form"
    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=240)
    fields: list[UiFormField] = Field(min_length=1, max_length=8)
    submit_label: str = Field(default="Send", max_length=40)


class UiProgressBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["progress"] = "progress"
    label: str = Field(max_length=120)
    value: int = Field(ge=0)
    max: int = Field(gt=0)
    unit: str | None = Field(default=None, max_length=20)


# Interactive "wow" blocks (flashcards / checklist / calculator). Their state
# lives in the browser; the payload only carries the starting configuration.


class UiFlashcard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    front: str = Field(min_length=1, max_length=400)
    back: str = Field(min_length=1, max_length=800)


class UiFlashcardsBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["flashcards"] = "flashcards"
    title: str | None = Field(default=None, max_length=120)
    cards: list[UiFlashcard] = Field(min_length=1, max_length=20)


class UiChecklistItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=300)
    checked: bool = False


class UiChecklistBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["checklist"] = "checklist"
    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    items: list[UiChecklistItem] = Field(min_length=1, max_length=40)


class UiCalculatorInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,29}$")
    label: str = Field(min_length=1, max_length=80)
    value: float = 0
    unit: str | None = Field(default=None, max_length=20)
    min: float | None = None
    max: float | None = None
    step: float | None = Field(default=None, gt=0)


class UiCalculatorOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(min_length=1, max_length=80)
    formula: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    decimals: int | None = Field(default=None, ge=0, le=6)


_CALCULATOR_FORMULA_TOKEN = re.compile(
    r"(?:\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*|[+\-*/()])"
)


def _formula_identifiers(formula: str, input_names: set[str]) -> set[str]:
    """Validate one calculator formula and return the input names it uses.

    The grammar is numbers, declared input names, ``+ - * / ( )`` and
    whitespace — nothing else. Function calls, ``**``, commas, quotes and
    statement separators all raise ``ValueError`` with a clear message so the
    ``ui_block`` tool reports a friendly error instead of emitting a payload
    the renderer must refuse to evaluate.
    """

    tokens: list[str] = []
    pos = 0
    while pos < len(formula):
        if formula[pos].isspace():
            pos += 1
            continue
        match = _CALCULATOR_FORMULA_TOKEN.match(formula, pos)
        if not match or match.end() == pos:
            snippet = formula[pos : pos + 12]
            raise ValueError(
                f"unsupported characters near {snippet!r}; formulas may only "
                "use numbers, input names, + - * / and ( )"
            )
        tokens.append(match.group(0))
        pos = match.end()
    if not tokens:
        raise ValueError("formula is empty")

    index = 0

    def peek() -> str | None:
        return tokens[index] if index < len(tokens) else None

    def parse_primary() -> None:
        nonlocal index
        token = peek()
        if token is None:
            raise ValueError(f"formula {formula!r} ends unexpectedly")
        if token in {"+", "-"}:  # unary sign, e.g. "-total" or "2*-3"
            index += 1
            parse_primary()
            return
        if token == "(":
            index += 1
            parse_expr()
            if peek() != ")":
                raise ValueError(f"formula {formula!r} has unbalanced parentheses")
            index += 1
        elif token[0].isdigit() or token[0] == ".":
            index += 1
        elif token[0].isalpha() or token[0] == "_":
            index += 1
            if token not in input_names:
                raise ValueError(
                    f"formula {formula!r} references unknown input {token!r}"
                )
        else:
            raise ValueError(f"formula {formula!r} has unexpected operator {token!r}")

    def parse_term() -> None:
        nonlocal index
        parse_primary()
        while peek() in {"*", "/"}:
            index += 1
            parse_primary()

    def parse_expr() -> None:
        nonlocal index
        parse_term()
        while peek() in {"+", "-"}:
            index += 1
            parse_term()

    # Leading unary + / - is handled inside parse_primary.
    parse_expr()
    if index != len(tokens):
        raise ValueError(f"formula {formula!r} has trailing tokens")
    return {token for token in tokens if token[0].isalpha() or token[0] == "_"}


class UiCalculatorBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["calculator"] = "calculator"
    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    inputs: list[UiCalculatorInput] = Field(min_length=1, max_length=12)
    outputs: list[UiCalculatorOutput] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _validate_formulas(self) -> UiCalculatorBlock:
        names = [item.name for item in self.inputs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"calculator input names must be unique: {duplicates}")
        known = set(names)
        for output in self.outputs:
            try:
                _formula_identifiers(output.formula, known)
            except ValueError as exc:
                raise ValueError(f"output {output.label!r}: {exc}") from exc
        return self


MAX_UI_BLOCK_DEPTH = 3  # layout nesting levels (root layout = 1)
MAX_UI_BLOCK_NODES = 50  # total nodes per ui_block event


class UiLayoutSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = Field(default=None, max_length=80)
    children: list[UiBlockNode] = Field(min_length=1, max_length=8)


class UiLayoutBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["layout"] = "layout"
    orientation: Literal["columns", "stack"] = "columns"
    sections: list[UiLayoutSection] = Field(min_length=1, max_length=4)


class UiCustomBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["custom"] = "custom"
    html: str = Field(min_length=1, max_length=100_000)
    height: int | None = Field(default=None, ge=64, le=2000)


UiBlockNode = Annotated[
    Union[
        UiStatCardsBlock,
        UiChartBlock,
        UiStepsBlock,
        UiTableBlock,
        UiKeyValueBlock,
        UiCalloutBlock,
        UiButtonsBlock,
        UiFormBlock,
        UiProgressBlock,
        UiFlashcardsBlock,
        UiChecklistBlock,
        UiCalculatorBlock,
        UiLayoutBlock,
        UiCustomBlock,
    ],
    Field(discriminator="type"),
]

# ``UiLayoutSection.children`` forward-references the alias above.
UiLayoutSection.model_rebuild()
UiLayoutBlock.model_rebuild()


_BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class UiBlockEvent(BaseModel):
    """Single complete frame for one ``ui_block`` tool call (not delta-streamed).

    ``metadata`` carries ``{"title": ...}`` when the tool got a title.
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["ui_block"] = "ui_block"
    agent: str
    tool_call_id: str
    blocks: list[UiBlockNode] = Field(min_length=1, max_length=6)
    is_final: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    block_id: str | None = Field(
        default=None,
        description=(
            "Optional stable identity for this UI block group; later calls "
            "with the same block_id update the group in place."
        ),
        pattern=_BLOCK_ID_RE,
    )
    replace_id: str | None = Field(
        default=None,
        description="Optional identity of an existing group to replace in place.",
        pattern=_BLOCK_ID_RE,
    )

    @model_validator(mode="after")
    def _enforce_composition_limits(self) -> UiBlockEvent:
        """Cap layout nesting depth and total node count (spec section 2.1)."""

        def walk(node: UiBlockNode, layout_depth: int) -> int:
            if isinstance(node, UiLayoutBlock):
                if layout_depth > MAX_UI_BLOCK_DEPTH:
                    raise ValueError(
                        "layout nesting deeper than "
                        f"{MAX_UI_BLOCK_DEPTH} levels is not supported"
                    )
                count = 1
                for section in node.sections:
                    for child in section.children:
                        count += walk(child, layout_depth + 1)
                return count
            return 1

        total = 0
        for block in self.blocks:
            total += walk(block, 1)
        if total > MAX_UI_BLOCK_NODES:
            raise ValueError(
                f"ui_block event exceeds {MAX_UI_BLOCK_NODES} total UI nodes "
                f"({total} provided)"
            )
        return self


MAX_VISUAL_ARTIFACT_SOURCE_BYTES = 200_000


def validate_visual_artifact_source(source_html: str) -> str:
    """Reject oversized HTML before it is persisted or sent over SSE."""
    if len(source_html.encode("utf-8")) > MAX_VISUAL_ARTIFACT_SOURCE_BYTES:
        raise ValueError("source_html exceeds 200000 UTF-8 bytes")
    return source_html


class VisualArtifactSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1, max_length=120)
    query_summary: str = Field(min_length=1, max_length=500)


class Scene3DNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    geometry: Literal["box", "sphere", "cylinder", "torus"]
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    color: Literal[
        "accent", "foreground", "muted", "success", "warning", "danger", "info"
    ]
    label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _validate_transform_bounds(self) -> Scene3DNode:
        if any(value < -100 or value > 100 for value in self.position):
            raise ValueError("3D position values must be in [-100, 100]")
        if any(value < -6.2832 or value > 6.2832 for value in self.rotation):
            raise ValueError("3D rotation values must be in [-6.2832, 6.2832]")
        if any(value < 0.01 or value > 100 for value in self.scale):
            raise ValueError("3D scale values must be in [0.01, 100]")
        return self


class Scene3DSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[Scene3DNode] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_unique_node_ids(self) -> Scene3DSpec:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("3D scene node ids must be unique")
        return self


class VisualArtifactEvent(BaseModel):
    """Validated complete payload for a rich dashboard, motion, or 3D artifact."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["visual_artifact"] = "visual_artifact"
    agent: str
    tool_call_id: str
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    kind: Literal["dashboard", "motion", "scene3d"]
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(max_length=500)
    source_html: str | None = Field(default=None, min_length=1)
    scene: Scene3DSpec | None = None
    sources: list[VisualArtifactSourceRef] = Field(default_factory=list, max_length=12)
    duration_ms: int | None = Field(default=None, ge=1, le=120_000)
    is_final: Literal[True] = True

    @model_validator(mode="after")
    def _validate_payload_for_kind(self) -> VisualArtifactEvent:
        if self.kind in {"dashboard", "motion"}:
            if self.source_html is None or self.scene is not None:
                raise ValueError("dashboard and motion require source_html only")
            validate_visual_artifact_source(self.source_html)
        elif self.scene is None or self.source_html is not None:
            raise ValueError("scene3d requires scene and forbids source_html")
        if self.kind == "motion" and self.duration_ms is None:
            raise ValueError("motion requires duration_ms")
        if self.kind != "motion" and self.duration_ms is not None:
            raise ValueError("duration_ms is only valid for motion")
        if self.kind != "dashboard" and self.sources:
            raise ValueError("sources are only valid for dashboard artifacts")
        return self
