"""Seeding helpers for the observability contract tests.

The committed JSONL under ``fixtures/spans/`` is a scrubbed, synthetic OTel
export anchored at ``ANCHOR``. Every endpoint reads a window relative to the
backend's clock, so ``seed`` shifts all timestamps (and the hourly file names)
by a whole number of hours until the anchor sits one hour before the current
hour. Expected values in the tests are derived from ``Seeded.ms``, never from
the wall clock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "spans"
ANCHOR = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
HOUR_NS = 3_600 * 1_000_000_000


@dataclass(frozen=True)
class Seeded:
    shift: timedelta

    def ms(self, original: datetime) -> int:
        """UNIX epoch ms of a fixture instant after the shift."""
        return int((original + self.shift).timestamp() * 1000)

    def at(self, hours: int = 0, minutes: int = 0, seconds: int = 0) -> datetime:
        """A fixture instant relative to the anchor, as ``gen`` laid it out."""
        return ANCHOR + timedelta(hours=hours, minutes=minutes, seconds=seconds)

    def day(self, original: datetime) -> str:
        return (original + self.shift).strftime("%Y-%m-%d")

    def hour_bucket(self, original: datetime) -> str:
        return (original + self.shift).strftime("%Y-%m-%dT%H:00:00Z")


def spans_dir(tmp_path: Path) -> Path:
    return tmp_path / "state" / "otel" / "spans"


def whole_hour_shift(now: datetime | None = None) -> timedelta:
    now = now or datetime.now(timezone.utc)
    floor = now.replace(minute=0, second=0, microsecond=0)
    return floor - timedelta(hours=1) - ANCHOR


def seed(tmp_path: Path, only: list[str] | None = None) -> Seeded:
    """Copy the fixture JSONL into the backend's state dir, shifted to ``now``."""
    shift = whole_hour_shift()
    shift_ns = int(shift.total_seconds()) * 1_000_000_000
    target = spans_dir(tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(FIXTURE_DIR.glob("*.jsonl")):
        if only is not None and source.stem not in only:
            continue
        stem = datetime.strptime(source.stem, "%Y-%m-%d-%H").replace(
            tzinfo=timezone.utc
        )
        lines = []
        for raw in source.read_text(encoding="utf-8").splitlines():
            span = json.loads(raw)
            span["start_time"] += shift_ns
            if span["end_time"] is not None:
                span["end_time"] += shift_ns
            lines.append(json.dumps(span, separators=(",", ":")))
        name = (stem + shift).strftime("%Y-%m-%d-%H") + ".jsonl"
        (target / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Seeded(shift)


def span(
    *,
    name: str,
    end: datetime,
    duration_ms: float,
    status: str = "OK",
    attributes: dict | None = None,
    trace_id: str = "0x" + "f" * 32,
    span_id: str = "0x" + "e" * 16,
    parent_id: str | None = None,
    kind: str = "INTERNAL",
) -> dict:
    end_ns = int(end.timestamp()) * 1_000_000_000
    return {
        "name": name,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_id": parent_id,
        "kind": kind,
        "start_time": end_ns - int(duration_ms * 1_000_000),
        "end_time": end_ns,
        "duration_ms": duration_ms,
        "status": status,
        "attributes": attributes or {},
        "events": [],
        "resource": {"service.name": "EvoFlux"},
    }


def write_partition(tmp_path: Path, when: datetime, spans: list[dict]) -> Path:
    """Write ``spans`` as the hourly partition holding ``when`` (UTC)."""
    target = spans_dir(tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    path = target / (when.strftime("%Y-%m-%d-%H") + ".jsonl")
    path.write_text(
        "".join(json.dumps(s, separators=(",", ":")) + "\n" for s in spans),
        encoding="utf-8",
    )
    return path
