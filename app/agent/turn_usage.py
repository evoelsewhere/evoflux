"""Turn-scoped usage aggregation across primary and auxiliary model calls."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping
from uuid import UUID

from app.agent.schemas.chat import Usage

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass(slots=True)
class _UsageTotals:
    input: int = 0
    output: int = 0
    cache: int = 0
    cache_write: int = 0
    thoughts: int = 0
    tool_use: int = 0
    calls: int = 0
    models: set[str] = field(default_factory=set)
    #: USD by cost component, summed per call. A turn is priced call by
    #: call because rates are per model, and a turn that escalated from a
    #: cheap model to an expensive one cannot be priced from its totals.
    cost: dict[str, float] = field(default_factory=dict)

    def add(
        self,
        usage: Mapping[str, int],
        model_id: str | None,
        cost: Mapping[str, float] | None = None,
    ) -> None:
        self.input += usage["input"]
        self.output += usage["output"]
        self.cache += usage["cache"]
        self.cache_write += usage["cache_write"]
        self.thoughts += usage["thoughts"]
        self.tool_use += usage["tool_use"]
        self.calls += 1
        if model_id:
            self.models.add(model_id)
        if cost:
            for component, amount in cost.items():
                self.cost[component] = self.cost.get(component, 0.0) + amount

    def snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "input": self.input,
            "output": self.output,
            "cache": self.cache,
            "cache_write": self.cache_write,
            "calls": self.calls,
        }
        if self.thoughts:
            result["thoughts"] = self.thoughts
        if self.tool_use:
            result["tool_use"] = self.tool_use
        if self.models:
            result["models"] = sorted(self.models)
        if self.cost:
            result["cost"] = {
                component: round(amount, 6) for component, amount in self.cost.items()
            }
        return result


@dataclass(slots=True)
class TurnUsageTracker:
    """Mutable accumulator inherited by auxiliary tasks through contextvars."""

    session_id: str
    agent_name: str
    total: _UsageTotals = field(default_factory=_UsageTotals)
    phases: dict[str, _UsageTotals] = field(default_factory=dict)
    publish_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def record(
        self,
        usage: Usage | Mapping[str, Any],
        *,
        phase: str,
        model_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized = _normalize_usage(usage)
        if normalized is None:
            return None
        from app.agent.usage import estimate_cost

        cost = estimate_cost(
            model_id,
            input_tokens=normalized["input"],
            output_tokens=normalized["output"],
            cached_tokens=normalized["cache"],
            cache_write_tokens=normalized["cache_write"],
            thoughts_tokens=normalized["thoughts"],
        )
        self.total.add(normalized, model_id, cost)
        self.phases.setdefault(phase, _UsageTotals()).add(normalized, model_id, cost)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.total.snapshot(),
            "phases": {
                name: totals.snapshot() for name, totals in sorted(self.phases.items())
            },
        }


_current_tracker: ContextVar[TurnUsageTracker | None] = ContextVar(
    "evoflux_turn_usage_tracker",
    default=None,
)


def begin_turn_usage(session_id: str, agent_name: str) -> Token:
    """Bind a fresh tracker to the current agent activation."""

    return _current_tracker.set(TurnUsageTracker(session_id, agent_name))


def end_turn_usage(token: Token) -> None:
    """Restore the prior tracker after an activation finishes."""

    _current_tracker.reset(token)


def current_turn_usage_snapshot() -> dict[str, Any] | None:
    tracker = _current_tracker.get()
    if tracker is None or tracker.total.calls == 0:
        return None
    return tracker.snapshot()


async def record_turn_usage(
    usage: Usage | Mapping[str, Any] | None,
    *,
    phase: str,
    model_id: str | None = None,
) -> dict[str, Any] | None:
    """Add one completed model call and publish the updated turn total."""

    tracker = _current_tracker.get()
    if tracker is None or usage is None:
        return None
    # Title generation runs concurrently with the primary stream. Keep
    # aggregate publications ordered so a slower, smaller snapshot can never
    # overwrite a newer total in the frontend.
    async with tracker.publish_lock:
        snapshot = tracker.record(usage, phase=phase, model_id=model_id)
        if snapshot is None:
            return None

        from app.agent.schemas.events import UsageEvent
        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        await stream_store.push_event(
            tracker.session_id,
            StreamEnvelope.from_event(
                UsageEvent(
                    prompt_tokens=snapshot["input"],
                    completion_tokens=snapshot["output"],
                    total_tokens=snapshot["input"] + snapshot["output"],
                    cached_tokens=snapshot["cache"],
                    cache_write_tokens=snapshot["cache_write"],
                    thoughts_tokens=snapshot.get("thoughts"),
                    tool_use_tokens=snapshot.get("tool_use"),
                    metadata={
                        "turn_total": True,
                        "agent": tracker.agent_name,
                        "calls": snapshot["calls"],
                        "phases": snapshot["phases"],
                        "models": snapshot.get("models"),
                    },
                    cost=snapshot.get("cost"),
                )
            ),
        )
        return snapshot


async def persist_turn_usage_snapshot(
    db: AsyncSession,
    session_id: UUID,
    snapshot: Mapping[str, Any] | None,
) -> bool:
    """Store a late auxiliary total on the newest visible assistant row."""

    if not snapshot:
        return False
    from sqlmodel import col, select

    from app.models.chat import SessionMessage

    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == session_id)
        .where(col(SessionMessage.role) == "assistant")
        .where(col(SessionMessage.is_summary).is_(False))
        .order_by(col(SessionMessage.created_at).desc(), col(SessionMessage.id).desc())
        .limit(1)
    )
    row = (await db.exec(stmt)).first()
    if row is None:
        return False
    row.extra = {**(row.extra or {}), "turn_usage": dict(snapshot)}
    db.add(row)
    return True


def _normalize_usage(
    usage: Usage | Mapping[str, Any],
) -> dict[str, int] | None:
    if isinstance(usage, Usage):
        values: Mapping[str, Any] = {
            "input": usage.prompt_tokens,
            "output": usage.completion_tokens,
            "cache": usage.cached_tokens,
            "cache_write": usage.cache_write_tokens,
            "thoughts": usage.thoughts_tokens,
            "tool_use": usage.tool_use_tokens,
        }
    else:
        values = usage

    def token_value(primary: str, fallback: str | None = None) -> int:
        value = values.get(primary)
        if value is None and fallback is not None:
            value = values.get(fallback)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    normalized = {
        "input": max(0, token_value("input", "prompt_tokens")),
        "output": max(0, token_value("output", "completion_tokens")),
        "cache": max(0, token_value("cache", "cached_tokens")),
        "cache_write": max(0, token_value("cache_write", "cache_write_tokens")),
        "thoughts": max(0, token_value("thoughts", "thoughts_tokens")),
        "tool_use": max(0, token_value("tool_use", "tool_use_tokens")),
    }
    if not any(normalized.values()):
        return None
    return normalized


__all__ = [
    "TurnUsageTracker",
    "begin_turn_usage",
    "current_turn_usage_snapshot",
    "end_turn_usage",
    "persist_turn_usage_snapshot",
    "record_turn_usage",
]
