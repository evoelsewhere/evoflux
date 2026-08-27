"""Bounded in-memory delivery for durable repository-owned EASD events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Any, AsyncIterator
from uuid import UUID

_QUEUE_SIZE = 256


@dataclass(frozen=True, slots=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]
    client_id: str


_LOCK = RLock()
_SUBSCRIBERS: dict[str, set[_Subscriber]] = defaultdict(set)


def _run_id(value: str | UUID) -> str:
    return str(UUID(str(value)))


def _offer(
    queue: asyncio.Queue[dict[str, Any]],
    payload: dict[str, Any],
    run_id: str,
) -> None:
    if queue.full():
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(
            {
                "type": "easd_resync_required",
                "run_id": run_id,
                "reason": "subscriber_queue_overflow",
            }
        )
        return
    queue.put_nowait(payload)


def _publish(run_id: str, payload: dict[str, Any]) -> None:
    with _LOCK:
        subscribers = tuple(_SUBSCRIBERS.get(run_id, ()))
    stale: list[_Subscriber] = []
    for subscriber in subscribers:
        try:
            subscriber.loop.call_soon_threadsafe(
                _offer,
                subscriber.queue,
                dict(payload),
                run_id,
            )
        except RuntimeError:
            stale.append(subscriber)
    if stale:
        with _LOCK:
            live = _SUBSCRIBERS.get(run_id)
            if live is not None:
                live.difference_update(stale)
                if not live:
                    _SUBSCRIBERS.pop(run_id, None)


def publish_run_event(run_id: str | UUID, event: dict[str, Any]) -> None:
    normalized = _run_id(run_id)
    _publish(
        normalized,
        {
            "type": "easd_event",
            "run_id": normalized,
            "sequence": int(event.get("sequence") or 0),
            "repository_generation": event.get("repository_generation"),
            "event": dict(event),
        },
    )


def _presence_payload(run_id: str) -> dict[str, Any]:
    with _LOCK:
        client_ids = sorted(item.client_id for item in _SUBSCRIBERS.get(run_id, ()))
    return {
        "type": "easd_presence",
        "run_id": run_id,
        "client_ids": client_ids,
        "count": len(client_ids),
    }


def presence_snapshot(run_id: str | UUID) -> dict[str, Any]:
    return _presence_payload(_run_id(run_id))


@asynccontextmanager
async def subscribe_run(
    run_id: str | UUID,
    client_id: str,
) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
    normalized = _run_id(run_id)
    subscriber = _Subscriber(
        loop=asyncio.get_running_loop(),
        queue=asyncio.Queue(maxsize=_QUEUE_SIZE),
        client_id=client_id,
    )
    with _LOCK:
        _SUBSCRIBERS[normalized].add(subscriber)
    _publish(normalized, _presence_payload(normalized))
    try:
        yield subscriber.queue
    finally:
        with _LOCK:
            subscribers = _SUBSCRIBERS.get(normalized)
            if subscribers is not None:
                subscribers.discard(subscriber)
                if not subscribers:
                    _SUBSCRIBERS.pop(normalized, None)
        _publish(normalized, _presence_payload(normalized))


def reset_for_tests() -> None:
    with _LOCK:
        _SUBSCRIBERS.clear()


__all__ = [
    "presence_snapshot",
    "publish_run_event",
    "reset_for_tests",
    "subscribe_run",
]
