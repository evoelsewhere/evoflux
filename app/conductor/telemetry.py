"""Durable, privacy-bounded telemetry queues for Conductor delivery."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from app.conductor.client import redact_telemetry
from app.conductor.constants.telemetry import (
    TELEMETRY_BATCH_SIZE,
    TELEMETRY_OUTBOX_DIRECTORY,
    TELEMETRY_OUTBOX_FILENAME,
    TELEMETRY_OUTBOX_MAX_EVENTS,
    TELEMETRY_REQUIRED_STRING_FIELDS,
    TelemetryField,
)
from app.core.config import settings

if TYPE_CHECKING:
    from app.conductor.client import ConductorClient

_LOCK = threading.Lock()
_MAX_QUEUE_EVENTS = 10_000
logger = logging.getLogger(__name__)


class TelemetryOutbox:
    """Persist the legacy bounded event queue used by agent telemetry hooks."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_events: int = TELEMETRY_OUTBOX_MAX_EVENTS,
    ) -> None:
        self._configured_path = path
        self._max_events = max(1, max_events)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._configured_path or (
            Path(settings.EVOFLUX_STATE_DIR)
            / TELEMETRY_OUTBOX_DIRECTORY
            / TELEMETRY_OUTBOX_FILENAME
        )

    def enqueue(self, event: dict[str, Any]) -> bool:
        clean = redact_telemetry(event)
        if not _valid_event(clean):
            logger.warning("conductor_telemetry_event_rejected")
            return False
        with self._lock:
            events = self._read()
            events.append(clean)
            if len(events) > self._max_events:
                events = events[-self._max_events :]
            return self._write(events)

    def peek(
        self,
        installation_id: str,
        *,
        limit: int = TELEMETRY_BATCH_SIZE,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(event)
                for event in self._read()
                if event.get(TelemetryField.INSTALLATION_ID) == installation_id
            ][: max(1, limit)]

    def acknowledge(self, event_ids: set[str]) -> None:
        if not event_ids:
            return
        with self._lock:
            remaining = [
                event
                for event in self._read()
                if event.get(TelemetryField.EVENT_ID) not in event_ids
            ]
            self._write(remaining)

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                logger.warning("conductor_telemetry_outbox_clear_failed")

    def count(self) -> int:
        with self._lock:
            return len(self._read())

    def _read(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError):
            logger.warning("conductor_telemetry_outbox_read_failed")
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _write(self, events: list[dict[str, Any]]) -> bool:
        path = self.path
        temp_path = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(events, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp_path, path)
            return True
        except OSError:
            logger.warning("conductor_telemetry_outbox_write_failed")
            return False


def _valid_event(event: dict[str, Any]) -> bool:
    return all(
        isinstance(event.get(field), str) and bool(event[field])
        for field in TELEMETRY_REQUIRED_STRING_FIELDS
    )


telemetry_outbox = TelemetryOutbox()


def _queue_path() -> Path:
    return Path(settings.EVOFLUX_STATE_DIR) / "conductor" / "usage-queue.jsonl"


def clear_usage() -> None:
    """Discard queued managed-skill events when a connection is removed."""

    with _LOCK:
        _queue_path().unlink(missing_ok=True)


def _managed_metadata(skill_name: str) -> dict[str, object] | None:
    root = Path(settings.SKILLS_DIR).resolve()
    metadata = (root / skill_name / ".evoflux.json").resolve()
    if not metadata.is_relative_to(root):
        return None
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("managed_by") != "conductor":
        return None
    return payload


def record_skill_usage(
    skill_name: str,
    *,
    source: Literal["manual", "implicit", "configured"],
    mode: Literal["work", "coding"],
    outcome: Literal["success", "failure", "cancelled"] = "success",
    duration_ms: int = 0,
    failure_category: str | None = None,
    session_id: str | None = None,
) -> None:
    """Append one content-free event when the skill is Conductor-managed."""

    metadata = _managed_metadata(skill_name)
    if metadata is None:
        return
    resource_id = metadata.get("resource_id")
    resource_version = metadata.get("resource_version")
    if not isinstance(resource_id, str) or not isinstance(resource_version, str):
        return
    event = {
        "event_id": str(uuid.uuid4()),
        "resource_id": resource_id,
        "resource_version": resource_version,
        "session_id": session_id[:120] if session_id else None,
        "invocation_source": source,
        "runtime_mode": mode,
        "failure_category": failure_category[:80] if failure_category else None,
        "outcome": outcome,
        "duration_ms": max(0, duration_ms),
        "tokens_in": 0,
        "tokens_out": 0,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    path = _queue_path()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            pass
        if len(existing) >= _MAX_QUEUE_EVENTS:
            existing = existing[-(_MAX_QUEUE_EVENTS - 1) :]
            _atomic_lines(path, existing)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False))
            handle.write("\n")


async def flush_usage(client: ConductorClient) -> int:
    path = _queue_path()
    with _LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return 0
        batch_lines = lines[:100]
    events: list[dict[str, object]] = []
    for line in batch_lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    if not events:
        with _LOCK:
            _atomic_lines(path, lines[len(batch_lines) :])
        return 0
    await client.report_resource_usage(events)
    with _LOCK:
        try:
            current = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return len(events)
        _atomic_lines(path, current[len(batch_lines) :])
    return len(events)


def _atomic_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if lines:
                handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
