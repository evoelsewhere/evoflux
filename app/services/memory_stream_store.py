"""In-memory SSE stream store.

Design
------
- _state: dict[session_id, TurnState]  — accumulated turn blob (reconnect replay)
- _subscribers: dict[session_id, list[asyncio.Queue]]  — live fan-out to SSE clients
- each TurnState journals replayable wire frames in producer order
- _cleanup tasks expire state after STREAM_TTL seconds

Single-process only — no cross-worker fan-out.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal, cast

from loguru import logger

from app.agent.schemas.events import (
    AgentNotConfiguredEvent,
    AgentStatusEvent,
    MessageEvent,
    SummarizationEndEvent,
    SummarizationStartEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from app.services._tool_state import match_tool_end, match_tool_start
from app.services.stream_envelope import StreamEnvelope

STREAM_TTL = 3600  # 1 hour

# Sentinel placed on subscriber queues when the turn finishes
_SENTINEL = object()

_NON_REPLAYABLE_EVENT_TYPES = frozenset(
    {
        # Persisted chat/team events are restored from the DB before SSE
        # attaches. Replaying them would create duplicate activity blocks.
        "inbox",
        "delegation",
        "handoff",
        # Internal model context must never reach the transcript.
        "summarization_content",
        # Reconnect must not repeat an operating-system side effect.
        "desktop_notification",
    }
)
_GATE_REPLY_TO_REQUEST = {
    "permission_replied": "permission_asked",
    "plan_approval_replied": "plan_approval_requested",
    "question_replied": "question_asked",
}
_GATE_REQUEST_EVENT_TYPES = frozenset(_GATE_REPLY_TO_REQUEST.values())
_AGENT_CONTENT_EVENT_TYPES = frozenset(
    {
        "message",
        "thinking",
        "tool_call",
        "tool_start",
        "tool_output_delta",
        "tool_end",
        "widget_delta",
        "provider_status",
    }
)


@dataclass(frozen=True, slots=True)
class _ReplayEvent:
    """One immutable wire frame plus metadata used for journal pruning."""

    event: str
    data: str
    agent: str = ""

    @classmethod
    def from_envelope(
        cls,
        envelope: StreamEnvelope,
        *,
        wire: dict[str, str] | None = None,
    ) -> _ReplayEvent:
        encoded = wire if wire is not None else envelope.to_wire()
        return cls(
            event=encoded["event"],
            data=encoded["data"],
            agent=envelope.agent,
        )

    def to_wire(self) -> dict[str, str]:
        return {"event": self.event, "data": self.data}


@dataclass(slots=True)
class _ReplaySnapshot:
    """Detached ordered journal plus legacy state at one subscriber cutoff."""

    events: tuple[_ReplayEvent, ...] = ()
    content: dict[str, str] = field(default_factory=dict)
    thinking: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    agent_statuses: dict[str, str] = field(default_factory=dict)
    agent_errors: dict[str, dict[str, Any]] = field(default_factory=dict)
    summarization: dict[str, dict[str, Any]] = field(default_factory=dict)
    goal_status: dict[str, Any] | None = None
    agent_not_configured: dict[str, Any] | None = None
    browser_session: dict[str, Any] | None = None
    plan_approval: dict[str, Any] | None = None
    question_asked: dict[str, Any] | None = None
    permission_asked: dict[str, Any] | None = None


class _TurnState:
    """Accumulated state for one in-flight turn."""

    __slots__ = (
        "is_streaming",
        "content",
        "thinking",
        "tool_calls",
        "agent_statuses",
        "agent_errors",
        "summarization",
        "usage",
        "goal_status",
        "error",
        "agent_not_configured",
        "browser_session",
        "plan_approval",
        "question_asked",
        "permission_asked",
        "replay_events",
        "subscribers",
        "_lock",
        "_cleanup_handle",
    )

    def __init__(self) -> None:
        self.is_streaming: bool = True
        # Me per-agent accumulators support persistence commits, content
        # queries, and the legacy replay fallback. A single blob was ambiguous
        # in team turns where multiple agents stream text.
        self.content: dict[str, str] = {}
        self.thinking: dict[str, str] = {}
        self.tool_calls: list[dict[str, Any]] = []
        # Me last-known lifecycle state per agent for state queries and legacy
        # replay. The ordered journal retains every status transition.
        self.agent_statuses: dict[str, str] = {}
        self.agent_errors: dict[str, dict[str, Any]] = {}
        # Me in-flight summarisation state per agent. Only lifecycle state is
        # retained: summary text is internal model context and is never
        # replayed into the user-visible transcript.
        # Cleared on a fresh ``init_turn`` (next turn) — the assistant
        # message persistence path doesn't apply here because summaries are
        # stored as DB rows and rehydrated separately on session load.
        self.summarization: dict[str, dict[str, Any]] = {}
        self.usage: dict | None = None
        # Latest durable goal snapshot. Preserve it across hidden goal turns so
        # an SSE reconnect between model calls can rebuild the progress row.
        self.goal_status: dict[str, Any] | None = None
        self.error: str | None = None
        self.agent_not_configured: dict[str, Any] | None = None
        # Latest browser session state for the next-turn baseline. The ordered
        # journal separately retains each within-turn browser transition.
        self.browser_session: dict[str, Any] | None = None
        # Pending plan-approval request for reconnect replay.  The agent
        # stays blocked on its future while the user reviews, so a page
        # refresh must be able to rediscover the pending plan.  Cleared by
        # ``plan_approval_replied``.
        self.plan_approval: dict[str, Any] | None = None
        # Pending ask-user / permission requests for reconnect replay.
        # Forge/Coding restore these only from SSE (no REST poll on attach),
        # so a mid-turn refresh must re-emit them like plan_approval.
        # Cleared by ``question_replied`` / ``permission_replied``.
        self.question_asked: dict[str, Any] | None = None
        self.permission_asked: dict[str, Any] | None = None
        # Original replayable wire frames in producer order. Accumulators
        # above remain useful for commit/state queries; this journal owns SSE
        # chronology on reconnect.
        self.replay_events: list[_ReplayEvent] = []
        # Me keep list of queues — one per SSE client
        self.subscribers: list[asyncio.Queue] = []
        # Serialises an attach cutoff with event accumulation + fan-out. The
        # critical sections deliberately contain no blocking I/O.
        self._lock = asyncio.Lock()
        self._cleanup_handle: asyncio.TimerHandle | None = None

    def reset_for_next_turn(self) -> None:
        self.is_streaming = True
        self.content = {}
        self.thinking = {}
        self.tool_calls = []
        self.agent_statuses = {}
        self.agent_errors = {}
        self.summarization = {}
        self.usage = None
        self.error = None
        self.agent_not_configured = None
        self.plan_approval = None
        self.question_asked = None
        self.permission_asked = None
        self.replay_events = []
        # Goal/browser state intentionally survives hidden turn boundaries.
        # Seed it as a baseline for future reconnects before new-turn events.
        if self.goal_status is not None:
            self.replay_events.append(
                _ReplayEvent.from_envelope(
                    StreamEnvelope.from_parts("goal_status", self.goal_status)
                )
            )
        if self.browser_session is not None:
            self.replay_events.append(
                _ReplayEvent.from_envelope(
                    StreamEnvelope.from_parts("browser_session", self.browser_session)
                )
            )
        # Preserve browser_session across turns — the browser may still be
        # active and the next turn needs to know about it.


def _take_replay_snapshot(state: _TurnState) -> _ReplaySnapshot:
    """Copy every accumulator read by ``attach`` while its cutoff is locked."""
    if state.replay_events:
        # Journal frames are frozen strings, so copying the tuple is enough;
        # avoid duplicating potentially large content/tool accumulators.
        return _ReplaySnapshot(events=tuple(state.replay_events))
    return _ReplaySnapshot(
        content=deepcopy(state.content),
        thinking=deepcopy(state.thinking),
        tool_calls=deepcopy(state.tool_calls),
        agent_statuses=deepcopy(state.agent_statuses),
        agent_errors=deepcopy(state.agent_errors),
        summarization=deepcopy(state.summarization),
        goal_status=deepcopy(state.goal_status),
        agent_not_configured=deepcopy(state.agent_not_configured),
        browser_session=deepcopy(state.browser_session),
        plan_approval=deepcopy(state.plan_approval),
        question_asked=deepcopy(state.question_asked),
        permission_asked=deepcopy(state.permission_asked),
    )


# Me store all active turns here
_turns: dict[str, _TurnState] = {}


def _cancel_cleanup(state: _TurnState) -> None:
    if state._cleanup_handle is not None:
        state._cleanup_handle.cancel()
        state._cleanup_handle = None


def _schedule_cleanup(session_id: str, state: _TurnState) -> None:
    """Schedule automatic expiry after STREAM_TTL seconds."""
    _cancel_cleanup(state)
    loop = asyncio.get_event_loop()
    state._cleanup_handle = loop.call_later(STREAM_TTL, _turns.pop, session_id, None)


# ── Write side ────────────────────────────────────────────────────────────────


async def init_turn(session_id: str, *, keep_subscribers: bool = False) -> None:
    """Initialise a fresh state blob for a new turn."""
    try:
        # Me cancel old cleanup if session reused
        old = _turns.get(session_id)
        if old is not None:
            _cancel_cleanup(old)
            if keep_subscribers:
                old.reset_for_next_turn()
                _schedule_cleanup(session_id, old)
                return
            # Me drain old subscribers so they unblock
            for q in old.subscribers:
                try:
                    q.put_nowait(_SENTINEL)
                except asyncio.QueueFull:
                    pass

        state = _TurnState()
        # Preserve browser_session across turns — the browser may still be
        # active when a new turn starts.
        if old is not None and old.browser_session is not None:
            state.browser_session = old.browser_session
            state.replay_events.append(
                _ReplayEvent.from_envelope(
                    StreamEnvelope.from_parts("browser_session", state.browser_session)
                )
            )
        _turns[session_id] = state
        _schedule_cleanup(session_id, state)
    except Exception as exc:
        logger.warning(
            "memory_store_init_turn_failed session_id={} error={}",
            session_id,
            exc,
        )


async def push_event(session_id: str, envelope: StreamEnvelope) -> None:
    """Update state and fan-out event to all live subscribers.

    ``envelope`` must be a :class:`StreamEnvelope` — raw dicts are rejected
    at the type boundary.  Producers build envelopes via
    :meth:`StreamEnvelope.from_event` (for typed ``*Event`` payloads) or
    :meth:`StreamEnvelope.from_parts` (for ad-hoc lifecycle events).
    """
    try:
        while True:
            state = _turns.get(session_id)
            if state is None:
                return
            async with state._lock:
                # ``init_turn`` may replace a state while this writer waits
                # for an attach snapshot. Retry against the current turn so
                # the event is not written to a detached state.
                if _turns.get(session_id) is not state:
                    continue
                _push_event_locked(session_id, state, envelope)
                return
    except Exception as exc:
        logger.warning(
            "memory_store_push_failed session_id={} error={}",
            session_id,
            exc,
        )


def _record_replay_event_locked(
    state: _TurnState,
    envelope: StreamEnvelope,
    wire: dict[str, str],
) -> None:
    """Append one replay frame, pruning state that must not survive reconnect."""
    event_type = envelope.event
    if event_type in _NON_REPLAYABLE_EVENT_TYPES or event_type == "done":
        return

    request_event = _GATE_REPLY_TO_REQUEST.get(event_type)
    if request_event is not None:
        state.replay_events = [
            entry for entry in state.replay_events if entry.event != request_event
        ]
        # A reconnect after resolution needs neither side of the gate. An
        # attach whose cutoff came first already has the request snapshot and
        # receives this reply from its live queue.
        return

    if event_type in _GATE_REQUEST_EVENT_TYPES:
        # Each gate kind has one pending slot. A replacement supersedes the
        # older request exactly like the accumulator fields below.
        state.replay_events = [
            entry for entry in state.replay_events if entry.event != event_type
        ]

    replay_envelope = envelope
    if event_type == "summarization_start":
        replay_envelope = StreamEnvelope.from_event(
            SummarizationStartEvent(agent=envelope.agent)
        )
        wire = replay_envelope.to_wire()
    elif event_type == "summarization_end":
        entry = state.summarization.get(envelope.agent, {})
        replay_envelope = StreamEnvelope.from_event(
            SummarizationEndEvent(
                agent=envelope.agent,
                metadata={"error": True} if entry.get("error") else {},
            )
        )
        wire = replay_envelope.to_wire()

    state.replay_events.append(_ReplayEvent.from_envelope(replay_envelope, wire=wire))


def _push_event_locked(
    session_id: str,
    state: _TurnState,
    envelope: StreamEnvelope,
) -> None:
    """Apply and fan out one event while ``state._lock`` is held."""
    try:
        event_type = envelope.event
        data = envelope.data

        # Me update state blob
        if event_type == "message" and data.get("text"):
            agent = envelope.agent
            state.content[agent] = state.content.get(agent, "") + data["text"]

        elif event_type == "thinking" and data.get("text"):
            agent = envelope.agent
            state.thinking[agent] = state.thinking.get(agent, "") + data["text"]

        elif event_type == "tool_call":
            state.tool_calls.append(
                {
                    "tool_call_id": data.get("tool_call_id"),
                    "name": data.get("name", ""),
                    "arguments": None,
                    "agent": envelope.agent,
                    "started": False,
                    "done": False,
                }
            )

        elif event_type == "tool_start":
            match_tool_start(
                state.tool_calls,
                data.get("tool_call_id"),
                data.get("name", ""),
                arguments=data.get("arguments"),
            )

        elif event_type == "tool_end":
            match_tool_end(
                state.tool_calls,
                data.get("tool_call_id"),
                data.get("name", ""),
                data.get("result"),
                data.get("metadata"),
            )

        elif event_type == "usage":
            state.usage = data

        elif event_type == "goal_status":
            state.goal_status = data

        elif event_type == "error":
            state.error = data.get("message", "error")

        elif event_type == "done":
            state.is_streaming = False

        elif event_type == "agent_not_configured":
            state.agent_not_configured = data

        # Me inbox events are DB-persisted by _persist_inbox BEFORE being
        # emitted here, so the DB is always authoritative.  No replay state
        # is kept — live subscribers still receive the event via the fan-out
        # below.

        elif event_type == "agent_status":
            agent = envelope.agent
            status = data.get("status", "")
            if agent and status:
                state.agent_statuses[agent] = status
                if status == "error":
                    state.agent_errors[agent] = data.get("metadata", {})
                else:
                    state.agent_errors.pop(agent, None)

        elif event_type == "summarization_start":
            agent = envelope.agent
            if agent:
                state.summarization[agent] = {
                    "done": False,
                    "error": False,
                }

        elif event_type == "summarization_content":
            # Backward compatibility for an old producer: accept the event,
            # but do not retain or fan out internal summary text.
            pass

        elif event_type == "summarization_end":
            agent = envelope.agent
            if agent:
                entry = state.summarization.setdefault(
                    agent, {"done": False, "error": False}
                )
                entry["done"] = True
                meta = data.get("metadata") or {}
                if isinstance(meta, dict) and meta.get("error"):
                    entry["error"] = True

        elif event_type == "browser_session":
            # Store the latest state for cross-turn seeding. The replay journal
            # below still retains every within-turn browser transition.
            state.browser_session = data

        elif event_type == "plan_approval_requested":
            # The agent blocks on this until the user replies — keep the
            # request so a reconnect can rediscover the pending plan.
            state.plan_approval = data

        elif event_type == "plan_approval_replied":
            state.plan_approval = None

        elif event_type == "question_asked":
            # Same reconnect contract as plan_approval — agent stays blocked.
            state.question_asked = data

        elif event_type == "question_replied":
            state.question_asked = None

        elif event_type == "permission_asked":
            state.permission_asked = data

        elif event_type == "permission_replied":
            state.permission_asked = None

        # Me refresh TTL on every write
        _schedule_cleanup(session_id, state)

        # Older workers may still publish summary deltas during a rolling
        # upgrade. Suppress them at the stream boundary as well as in the UI.
        if event_type == "summarization_content":
            return

        # Me fan-out to all live SSE clients.
        #
        # If a subscriber queue fills up, a slow/paused client (backgrounded
        # browser tab, stalled socket) is dropping events. Silently removing
        # the queue leaves the client's SSE coroutine blocked forever and
        # its live view stuck on the last delivered event (tool_call stays
        # "executing", `done` never arrives, etc.). To recover cleanly we
        # push a sentinel so `attach()` exits → the SSE coroutine yields →
        # the client's `onDone` fires → it reloads state from the DB.
        wire = envelope.to_wire()
        _record_replay_event_locked(state, envelope, wire)
        dead: list[asyncio.Queue] = []
        for q in state.subscribers:
            try:
                q.put_nowait(wire)
            except asyncio.QueueFull:
                logger.warning(
                    "sse_subscriber_queue_full session_id={} event_type={} "
                    "dropping_client qsize={}",
                    session_id,
                    event_type,
                    q.qsize(),
                )
                # Me drain the oldest event to make room for the sentinel —
                # the client was going to miss it anyway, this is strictly
                # better than leaving the coroutine hung.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(_SENTINEL)
                except asyncio.QueueFull:
                    pass
                dead.append(q)
        for q in dead:
            try:
                state.subscribers.remove(q)
            except ValueError:
                pass

    except Exception as exc:
        logger.warning(
            "memory_store_push_failed session_id={} error={}",
            session_id,
            exc,
        )


async def commit_agent_content(session_id: str, agent: str) -> None:
    """Drop ``content[agent]``, ``thinking[agent]`` and any ``tool_calls``
    owned by *agent* from the state blob.

    Called by the checkpointer after an assistant message is persisted to
    the DB — once durable, a mid-turn reconnect must not replay it (the
    frontend loads the message from DB, replay would produce duplicates).
    """
    while True:
        state = _turns.get(session_id)
        if state is None:
            return
        async with state._lock:
            if _turns.get(session_id) is not state:
                continue
            state.content.pop(agent, None)
            state.thinking.pop(agent, None)
            # Me drop tool_calls owned by this agent.  AssistantMessage rows
            # embed their tool_calls as part of the assistant payload, so once
            # durable they and their ordered deltas must leave replay too.
            state.tool_calls = [
                tc for tc in state.tool_calls if tc.get("agent") != agent
            ]
            state.replay_events = [
                entry
                for entry in state.replay_events
                if not (
                    entry.agent == agent and entry.event in _AGENT_CONTENT_EVENT_TYPES
                )
            ]
            return


async def mark_done(session_id: str) -> None:
    """Flip is_streaming=False and unblock all subscribers."""
    try:
        state = _turns.get(session_id)
        if state is None:
            return
        state.is_streaming = False
        _schedule_cleanup(session_id, state)
        # Me send sentinel to all subscribers so they exit
        for q in list(state.subscribers):
            try:
                q.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass
    except Exception as exc:
        logger.warning(
            "memory_store_mark_done_failed session_id={} error={}",
            session_id,
            exc,
        )


async def clear(session_id: str) -> None:
    """Delete state for this session."""
    try:
        state = _turns.pop(session_id, None)
        if state is not None:
            _cancel_cleanup(state)
    except Exception as exc:
        logger.warning(
            "memory_store_clear_failed session_id={} error={}",
            session_id,
            exc,
        )


# ── Read side ─────────────────────────────────────────────────────────────────


async def is_done(session_id: str) -> bool:
    state = _turns.get(session_id)
    if state is None:
        return True
    return not state.is_streaming


def running_session_ids() -> set[str]:
    """Return session ids that currently have an in-flight stream turn."""
    return {session_id for session_id, state in _turns.items() if state.is_streaming}


def accumulated_content(session_id: str) -> dict[str, str]:
    """Return a detached snapshot of assistant text accumulated for one turn."""
    state = _turns.get(session_id)
    return dict(state.content) if state is not None else {}


def _legacy_replay_events(snapshot: _ReplaySnapshot) -> list[dict[str, str]]:
    """Rebuild replay for pre-journal state retained during rolling upgrades."""
    events: list[dict[str, str]] = []
    for agent, status in snapshot.agent_statuses.items():
        if not agent or status not in ("idle", "working", "offline", "error"):
            continue
        events.append(
            StreamEnvelope.from_event(
                AgentStatusEvent(
                    agent=agent,
                    status=cast(
                        Literal["idle", "working", "offline", "error"],
                        status,
                    ),
                    metadata=snapshot.agent_errors.get(agent, {}),
                )
            ).to_wire()
        )

    if snapshot.agent_not_configured is not None:
        events.append(
            StreamEnvelope.from_event(
                AgentNotConfiguredEvent.model_validate(snapshot.agent_not_configured)
            ).to_wire()
        )

    if snapshot.goal_status is not None:
        events.append(
            StreamEnvelope.from_parts(
                event="goal_status", data=snapshot.goal_status
            ).to_wire()
        )

    for agent, entry in snapshot.summarization.items():
        if not agent:
            continue
        events.append(
            StreamEnvelope.from_event(SummarizationStartEvent(agent=agent)).to_wire()
        )
        if entry.get("done"):
            events.append(
                StreamEnvelope.from_event(
                    SummarizationEndEvent(
                        agent=agent,
                        metadata={"error": True} if entry.get("error") else {},
                    )
                ).to_wire()
            )

    if snapshot.browser_session is not None:
        events.append(
            StreamEnvelope.from_parts(
                event="browser_session", data=snapshot.browser_session
            ).to_wire()
        )

    if snapshot.plan_approval is not None:
        events.append(
            StreamEnvelope.from_parts(
                event="plan_approval_requested", data=snapshot.plan_approval
            ).to_wire()
        )

    if snapshot.permission_asked is not None:
        events.append(
            StreamEnvelope.from_parts(
                event="permission_asked", data=snapshot.permission_asked
            ).to_wire()
        )

    if snapshot.question_asked is not None:
        events.append(
            StreamEnvelope.from_parts(
                event="question_asked", data=snapshot.question_asked
            ).to_wire()
        )

    for agent, text in snapshot.thinking.items():
        if text:
            events.append(
                StreamEnvelope.from_event(
                    ThinkingEvent(agent=agent, text=text)
                ).to_wire()
            )

    for tool_call in snapshot.tool_calls:
        events.append(
            StreamEnvelope.from_event(
                ToolCallEvent(
                    agent=tool_call.get("agent", ""),
                    tool_call_id=tool_call.get("tool_call_id"),
                    name=tool_call["name"],
                )
            ).to_wire()
        )
        if tool_call.get("started"):
            events.append(
                StreamEnvelope.from_event(
                    ToolStartEvent(
                        agent=tool_call.get("agent", ""),
                        tool_call_id=tool_call.get("tool_call_id"),
                        name=tool_call["name"],
                        arguments=tool_call.get("arguments"),
                    )
                ).to_wire()
            )
        if tool_call.get("done"):
            events.append(
                StreamEnvelope.from_event(
                    ToolEndEvent(
                        agent=tool_call.get("agent", ""),
                        tool_call_id=tool_call.get("tool_call_id"),
                        name=tool_call["name"],
                        result=tool_call.get("result"),
                        metadata=tool_call.get("metadata") or {},
                    )
                ).to_wire()
            )

    for agent, text in snapshot.content.items():
        if text:
            events.append(
                StreamEnvelope.from_event(
                    MessageEvent(agent=agent, text=text)
                ).to_wire()
            )
    return events


async def attach(session_id: str) -> AsyncGenerator[dict[str, str], None]:
    """Yield events in SSE wire shape for the current in-flight turn.

    Each yielded value is ``{"event": str, "data": str}`` — ready to hand to
    ``sse_starlette``.  Internally we build typed ``*Event`` models and
    :class:`StreamEnvelope` wrappers, then call ``to_wire()`` at the yield
    boundary so the on-the-wire shape is guaranteed consistent.

    Reconnect protocol:
    1. Lock the current streaming state (DB is authoritative once done).
    2. Register a subscriber queue and capture a detached replay snapshot in
       the same critical section. This instant is the replay/live cutoff.
    3. Replay journal frames in original producer order. Only pre-journal
       in-memory state falls back to the legacy synthetic reconstruction.
    4. Yield live events from queue until sentinel arrives.
    """
    try:
        # maxsize=2048 gives ~4× headroom over the previous 512 for long
        # tool-heavy turns on healthy-but-slightly-lagging clients. A full
        # queue still triggers the drop-and-sentinel recovery in push_event()
        # so a genuinely stuck subscriber can't leak memory unboundedly.
        q: asyncio.Queue = asyncio.Queue(maxsize=2048)
        while True:
            state = _turns.get(session_id)
            if state is None:
                return
            async with state._lock:
                # The turn can be replaced while lock acquisition is pending.
                # Retry so the queue always belongs to the current state.
                if _turns.get(session_id) is not state:
                    continue
                if not state.is_streaming:
                    return
                state.subscribers.append(q)
                snapshot = _take_replay_snapshot(state)
                break

        try:
            replay_events = (
                [entry.to_wire() for entry in snapshot.events]
                if snapshot.events
                else _legacy_replay_events(snapshot)
            )
            for replay_event in replay_events:
                yield replay_event

            # Me drain live events until sentinel.  Items on the queue are
            # already in wire shape (populated by push_event via to_wire()).
            while True:
                item = await q.get()
                if item is _SENTINEL:
                    break
                yield item

        finally:
            async with state._lock:
                try:
                    state.subscribers.remove(q)
                except ValueError:
                    pass

    except Exception as exc:
        logger.warning(
            "memory_store_attach_failed session_id={} error={}",
            session_id,
            exc,
        )


async def close() -> None:
    """Clear all state (called on server shutdown)."""
    _turns.clear()
