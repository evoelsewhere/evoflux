"""Native SSE event schemas for EvoFlux streaming API.

Each event is serialised as::

    event: <type>
    data: <json>

The ``type`` field inside the JSON body mirrors the SSE ``event:`` line so
clients that parse only the ``data:`` payload can still distinguish events.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalStatusEvent(BaseModel):
    """Latest durable goal snapshot for the session, or ``None`` when stopped."""

    type: Literal["goal_status"] = "goal_status"
    session_id: str
    goal: dict[str, Any] | None = None
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

    Each item in ``questions`` has ``question``, ``options``, and ``strict``.
    Ordinary agent questions use non-strict options as quick picks alongside
    a free-text fallback. Internal workflow gates are strict because their
    declared choices route graph edges, so the frontend must only offer those
    choices.
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


class PlanApprovalRequestedEvent(BaseModel):
    """Agent has authored a plan and requests user review.

    The frontend should display a plan-review UI and POST a reply to
    ``/api/team/{session_id}/plan/reply`` with the ``request_id`` in the
    body and a ``decision`` of ``approved``, ``rejected`` or ``revise``
    (``revise`` carries free-text ``feedback`` back to the agent).

    ``plan`` is the agent-authored markdown plan document. Each step in
    ``steps`` has ``tool``, ``args`` (JSON-serialisable dict), and
    ``summary`` (one-line description for the user). Optional ``path`` and
    ``diff_stat`` fields are included when the step mutates a known file.
    """

    type: Literal["plan_approval_requested"] = "plan_approval_requested"
    request_id: str  # unique ID — included in the reply POST
    session_id: str  # agent session that owns the plan
    plan: str = ""  # markdown plan document authored by the agent
    steps: list[dict[str, Any]]  # [{tool, args, summary, path?, diff_stat?}, ...]
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanApprovalRepliedEvent(BaseModel):
    """A plan-approval request was resolved (or cancelled by interrupt).

    Lets every connected client close its plan-review UI and stops the
    stream store from replaying the pending request on reconnect.
    """

    type: Literal["plan_approval_replied"] = "plan_approval_replied"
    request_id: str
    session_id: str
    decision: str  # "approved" | "rejected" | "revise" | "cancelled"
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
