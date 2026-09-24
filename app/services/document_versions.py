"""Version history for the Office documents in a session workspace.

Every settled save of a ``.pptx``/``.docx``/``.xlsx`` becomes a version, so a
user can step an agent's edits back and forward (undo/redo) or roll a file
back to any earlier version from the document viewer. History is per file and
independent of the conversation: it never rewinds chat or other files.

Storage lives outside the workspace, under
``EVOFLUX_STATE_DIR/document-versions/<session>/<path key>/``: a JSON
manifest plus content-addressed blobs, so identical versions share bytes.
The history is linear like an editor's: undo/redo move ``head``; a new save
made while ``head`` is behind the newest version drops the versions after it.

Versions are recorded when the viewer asks for a file's history (catching
changes made while nobody watched), at checkpoints the client takes before
sending an edit request, and by a workspace watcher registered for the
session the first time its history is used. A deck still being built live
is skipped until it is finished, and files read mid-write (not a complete
ZIP package) are ignored until the next save.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.services.document_preview.live_deck import deck_is_live_for_any

VERSIONED_SUFFIXES = frozenset({".pptx", ".docx", ".xlsx"})
MAX_VERSIONS = 50
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_LABEL_CHARS = 200

_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()
# Labels for the next recorded change of a file, set by a checkpoint taken
# right before an edit request: ``(session_id, path) -> label``.
_pending_labels: dict[tuple[str, str], str] = {}
_watched: set[tuple[str, str]] = set()


class DocumentVersionError(Exception):
    """A history operation that cannot be carried out (missing version…)."""


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: str
    sha256: str
    size: int
    created_at: float
    label: str = ""
    source: str = "change"


@dataclass(slots=True)
class DocumentHistory:
    path: str
    versions: list[DocumentVersion] = field(default_factory=list)
    head: str | None = None

    @property
    def head_index(self) -> int:
        for index, version in enumerate(self.versions):
            if version.id == self.head:
                return index
        return len(self.versions) - 1

    @property
    def can_undo(self) -> bool:
        return self.head_index > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self.head_index < len(self.versions) - 1


def is_versioned(rel_path: str) -> bool:
    name = Path(rel_path).name
    # ``~$deck.pptx`` is an Office lock file, not a document.
    return Path(name).suffix.lower() in VERSIONED_SUFFIXES and not name.startswith("~$")


def _history_dir(session_id: str, rel_path: str) -> Path:
    key = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:32]
    return Path(settings.EVOFLUX_STATE_DIR) / "document-versions" / session_id / key


def _lock_for(directory: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(directory, threading.Lock())


def _load(directory: Path, rel_path: str) -> DocumentHistory:
    try:
        raw = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        versions = [DocumentVersion(**item) for item in raw.get("versions", [])]
        return DocumentHistory(path=rel_path, versions=versions, head=raw.get("head"))
    except FileNotFoundError:
        return DocumentHistory(path=rel_path)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning(
            "document_versions_manifest_unreadable dir={} err={}", directory, exc
        )
        return DocumentHistory(path=rel_path)


def _save(directory: Path, history: DocumentHistory) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "path": history.path,
        "head": history.head,
        "versions": [asdict(version) for version in history.versions],
    }
    temporary = directory / f".manifest.{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(temporary, directory / "manifest.json")


def _read_document(path: Path) -> bytes | None:
    """Bytes of a complete document, or None while it is missing or mid-write."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    try:
        # A file caught mid-save has no central directory yet.
        with zipfile.ZipFile(io.BytesIO(data)):
            pass
    except zipfile.BadZipFile:
        return None
    return data


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.restore")
    temporary.write_bytes(data)
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            # Windows: a viewer or antivirus may hold the file briefly.
            if attempt == 19:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def _record_locked(
    directory: Path,
    history: DocumentHistory,
    data: bytes,
    *,
    label: str,
    source: str,
) -> bool:
    """Append ``data`` as the new head unless it already is. Holds the lock."""
    digest = hashlib.sha256(data).hexdigest()
    index = history.head_index
    if history.versions and history.versions[index].sha256 == digest:
        return False
    # A new save after undo replaces the redo branch, like an editor.
    removed = history.versions[index + 1 :]
    history.versions = history.versions[: index + 1]
    version = DocumentVersion(
        id=uuid.uuid4().hex[:12],
        sha256=digest,
        size=len(data),
        created_at=time.time(),
        label=label[:MAX_LABEL_CHARS],
        source=source,
    )
    blobs = directory / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    blob = blobs / digest
    if not blob.exists():
        temporary = blobs / f".{digest}.{uuid.uuid4().hex[:8]}.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, blob)
    history.versions.append(version)
    history.head = version.id
    if len(history.versions) > MAX_VERSIONS:
        removed += history.versions[: len(history.versions) - MAX_VERSIONS]
        history.versions = history.versions[-MAX_VERSIONS:]
    kept = {item.sha256 for item in history.versions}
    for old in removed:
        if old.sha256 not in kept:
            (blobs / old.sha256).unlink(missing_ok=True)
    return True


def _being_built(path: Path) -> bool:
    """A deck a running session is still building saves once per slide."""
    from app.services import memory_stream_store

    return deck_is_live_for_any(path, memory_stream_store.running_session_ids())


def record_version(
    session_id: str,
    root: Path,
    rel_path: str,
    *,
    label: str = "",
    source: str = "change",
) -> DocumentHistory:
    """Record the file's current content as a version when it changed."""
    directory = _history_dir(session_id, rel_path)
    with _lock_for(directory):
        history = _load(directory, rel_path)
        path = root / rel_path
        if not is_versioned(rel_path) or _being_built(path):
            return history
        data = _read_document(path)
        if data is None:
            return history
        pending = _pending_labels.get((session_id, rel_path))
        if _record_locked(
            directory,
            history,
            data,
            label=label or pending or "",
            source=source if history.versions else "baseline",
        ):
            if pending and not label:
                _pending_labels.pop((session_id, rel_path), None)
            _save(directory, history)
        return history


def checkpoint(
    session_id: str, root: Path, rel_path: str, label: str
) -> DocumentHistory:
    """Capture the file before an edit request; its next change gets ``label``."""
    history = record_version(session_id, root, rel_path, source="checkpoint")
    if label.strip():
        _pending_labels[(session_id, rel_path)] = label.strip()[:MAX_LABEL_CHARS]
    return history


def get_history(session_id: str, root: Path, rel_path: str) -> DocumentHistory:
    """The file's history, first recording any change made while unwatched."""
    return record_version(session_id, root, rel_path)


def restore_version(
    session_id: str, root: Path, rel_path: str, version_id: str
) -> DocumentHistory:
    """Write ``version_id`` back to the workspace and make it the head."""
    directory = _history_dir(session_id, rel_path)
    path = root / rel_path
    with _lock_for(directory):
        history = _load(directory, rel_path)
        target = next((v for v in history.versions if v.id == version_id), None)
        if target is None:
            raise DocumentVersionError("That version no longer exists.")
        # Never lose unrecorded work: keep what is on disk as a version first.
        current = _read_document(path)
        if current is not None and _record_locked(
            directory, history, current, label="", source="change"
        ):
            _save(directory, history)
            if target not in history.versions:
                raise DocumentVersionError(
                    "The file changed since, so that version was replaced."
                )
        try:
            data = (directory / "blobs" / target.sha256).read_bytes()
        except OSError as exc:
            raise DocumentVersionError("That version's content is missing.") from exc
        _write_atomic(path, data)
        history.head = target.id
        _save(directory, history)
        return history


def step(session_id: str, root: Path, rel_path: str, *, offset: int) -> DocumentHistory:
    """Undo (``offset=-1``) or redo (``offset=1``) one version."""
    history = get_history(session_id, root, rel_path)
    index = history.head_index + offset
    if not 0 <= index < len(history.versions):
        raise DocumentVersionError(
            "Nothing to undo." if offset < 0 else "Nothing to redo."
        )
    return restore_version(session_id, root, rel_path, history.versions[index].id)


async def ensure_watching(session_id: str, root: Path) -> None:
    """Record every settled Office save in ``root`` for this session."""
    import asyncio

    from app.services.workspace_file_watcher import workspace_file_watcher

    key = (session_id, str(root))
    if key in _watched:
        return
    _watched.add(key)

    async def on_change(_workspace: str, events: list[dict[str, str]]) -> None:
        paths = {
            event["path"]
            for event in events
            if event.get("type") != "deleted" and is_versioned(event.get("path", ""))
        }
        for rel_path in paths:
            await asyncio.to_thread(record_version, session_id, root, rel_path)

    await workspace_file_watcher.add_callback(str(root), on_change)


__all__ = [
    "MAX_VERSIONS",
    "DocumentHistory",
    "DocumentVersion",
    "DocumentVersionError",
    "checkpoint",
    "ensure_watching",
    "get_history",
    "is_versioned",
    "record_version",
    "restore_version",
    "step",
]
