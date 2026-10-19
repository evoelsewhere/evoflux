"""Deterministic dispatch for trusted declarative plugin and Settings hooks."""

from __future__ import annotations

import time
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.agent.plugins.hook_contract import (
    HookEvent,
    HookFailurePolicy,
    HookRegistration,
    HookSettingsPolicy,
)
from app.agent.plugins.hook_resolution import (
    EventDecision,
    HookOutcome,
    resolve_event_hooks,
    merge_hook_outputs,
)
from app.agent.plugins.hook_runner import (
    HookExecutionError,
    HookExecutionResult,
    HookIsolationBackend,
    HookIsolationUnavailable,
    run_hook,
)


@dataclass(frozen=True, slots=True)
class HookDispatchResult:
    decision: EventDecision
    statuses: Mapping[str, str]


def _status_key(registration: HookRegistration) -> str:
    return (
        f"{registration.plugin_id or registration.source.value}:{registration.hook_id}"
    )


def _root_key(registration: HookRegistration) -> tuple[str, str | None, str]:
    return (registration.source.value, registration.plugin_id, registration.hook_id)


def _matches(registration: HookRegistration, event_input: dict) -> bool:
    matcher = registration.definition.matcher if registration.definition else None
    if matcher is None:
        return True
    return all(
        event_input.get(field) == expected
        for field, expected in matcher.model_dump(exclude_none=True).items()
    )


async def dispatch_hooks(
    event: HookEvent,
    event_input: dict,
    *,
    settings_policy: HookSettingsPolicy,
    settings_registrations: Sequence[HookRegistration],
    plugin_registrations: Sequence[HookRegistration],
    plugin_roots: Mapping[tuple[str, str | None, str], Path],
    backend: HookIsolationBackend | None = None,
    cancellation_token: asyncio.Event | None = None,
) -> HookDispatchResult:
    """Resolve and run the event's eligible hooks in stable order.

    A missing isolation backend never executes a hook. Failure policy controls
    whether that blocked/failed hook is ignored or turns into a sticky denial.
    Telemetry records identifiers and outcomes only, without event data/output.
    """

    effective = resolve_event_hooks(
        event,
        settings_policy,
        settings_registrations=settings_registrations,
        plugin_registrations=plugin_registrations,
    )
    statuses = {
        _status_key(status.registration): status.status for status in effective.statuses
    }
    outcomes: list[HookOutcome] = []
    forced_denial = False
    forced_denial_reason: str | None = None

    for registration in effective.ordered:
        if not _matches(registration, event_input):
            statuses[_status_key(registration)] = "matcher_not_matched"
            continue
        if registration.definition is None:
            # Legacy in-process adapters require a separate compatibility
            # bridge. Never call their handler from this declarative runner.
            statuses[_status_key(registration)] = "unsupported_legacy_adapter"
            continue
        root = plugin_roots.get(_root_key(registration))
        started = time.monotonic()
        try:
            if root is None:
                raise HookExecutionError("hook package root is unavailable")
            result: HookExecutionResult = await run_hook(
                registration,
                event_input,
                plugin_root=root,
                backend=backend,
                cancellation_token=cancellation_token,
            )
            outcomes.append(HookOutcome(registration, result.output))
            statuses[_status_key(registration)] = "active"
            logger.info(
                "plugin_hook_event hook_id={} source={} event={} outcome=success duration_ms={}",
                registration.hook_id,
                registration.source.value,
                event.value,
                int((time.monotonic() - started) * 1000),
            )
        except HookIsolationUnavailable:
            statuses[_status_key(registration)] = "blocked_isolation_unavailable"
            # Isolation is a core security invariant. A hook's fail-open policy
            # cannot turn missing containment into permission to continue.
            forced_denial = True
            forced_denial_reason = "hook isolation is unavailable"
            logger.warning(
                "plugin_hook_event hook_id={} source={} event={} outcome=isolation_unavailable duration_ms={}",
                registration.hook_id,
                registration.source.value,
                event.value,
                int((time.monotonic() - started) * 1000),
            )
        except (HookExecutionError, OSError, ValueError):
            statuses[_status_key(registration)] = "failed"
            forced_denial = (
                forced_denial
                or registration.definition.failure_policy
                is HookFailurePolicy.FAIL_CLOSED
            )
            logger.warning(
                "plugin_hook_event hook_id={} source={} event={} outcome=failed duration_ms={}",
                registration.hook_id,
                registration.source.value,
                event.value,
                int((time.monotonic() - started) * 1000),
            )

    decision = merge_hook_outputs(event, outcomes)
    if forced_denial and not decision.denied:
        decision = EventDecision(
            event=event,
            denied=True,
            reason=forced_denial_reason or "hook execution failed",
            values=decision.values,
        )
    return HookDispatchResult(decision=decision, statuses=statuses)


__all__ = ["HookDispatchResult", "dispatch_hooks"]
