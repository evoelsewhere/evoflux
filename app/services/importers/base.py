"""Shared data types for the import pipeline.

Every parser produces an :class:`ImportBundle` containing zero or more
:class:`ImportItem` entries.  The orchestrator in
:mod:`app.services.import_service` consumes these bundles, presents them for
review, and writes the accepted items through existing EvoFlux services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# ── Item kinds ────────────────────────────────────────────────────────────────

ImportItemKind = Literal[
    "session",
    "agent",
    "skill",
    "plugin",
    "mcp_server",
    "memory_fact",
    "knowledge",
    "custom_instruction",
    "setting",
    "scheduled_task",
]

# ── Known source identifiers ─────────────────────────────────────────────────

ImportSource = Literal[
    "claude_web",
    "claude_code",
    "chatgpt",
    "codex",
    "cursor",
    "generic",
]

# ── Conflict resolution actions ──────────────────────────────────────────────

ConflictAction = Literal["import", "skip", "replace", "rename"]

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class ImportItem:
    """One importable unit produced by a source parser."""

    kind: ImportItemKind
    source: str
    source_id: str
    data: dict[str, Any]
    label: str
    conflicts: list[str] = field(default_factory=list)
    action: ConflictAction = "import"


@dataclass
class ImportBundle:
    """Complete parsed result from one import detection."""

    source: str
    detected_format: str
    items: list[ImportItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportResult:
    """Outcome of executing an import."""

    imported: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
