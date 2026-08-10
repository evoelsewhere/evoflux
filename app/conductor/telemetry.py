"""Privacy-safe, bounded telemetry outbox for Conductor delivery."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

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

logger = logging.getLogger(__name__)


class TelemetryOutbox:
    """Persist a bounded queue so agent turns never wait for the network."""

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
