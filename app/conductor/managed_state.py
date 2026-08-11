"""Durable project-scoped state for Conductor-managed resources."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from app.conductor.models import ManagedResourceDocument, ManagedResourceRecord
from app.core.config import settings


class ManagedResourceStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(settings.EVOFLUX_STATE_DIR) / "conductor"
        self.path = self.root / "managed-resources-v2.json"
        self._lock = threading.RLock()

    def load(self) -> ManagedResourceDocument:
        with self._lock:
            if not self.path.exists():
                return ManagedResourceDocument()
            if self.path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Conductor managed-resource state exceeds 4 MiB.")
            return ManagedResourceDocument.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )

    def replace_project(self, project_id: str) -> ManagedResourceDocument:
        with self._lock:
            current = self.load()
            if current.project_id in {None, project_id}:
                if current.project_id is None:
                    current.project_id = project_id
                    self._write(current)
                return current
            replacement = ManagedResourceDocument(project_id=project_id)
            self._write(replacement)
            return replacement

    def upsert(self, record: ManagedResourceRecord) -> ManagedResourceDocument:
        with self._lock:
            document = self.load()
            if document.project_id not in {None, record.project_id}:
                raise ValueError(
                    "Managed resource belongs to another Conductor project."
                )
            document.project_id = record.project_id
            for index, item in enumerate(document.resources):
                if item.resource_id == record.resource_id:
                    document.resources[index] = record
                    break
            else:
                document.resources.append(record)
            document.resources.sort(key=lambda item: (item.kind, item.slug))
            self._write(document)
            return document

    def find(self, project_id: str, resource_id: str) -> ManagedResourceRecord | None:
        document = self.load()
        if document.project_id != project_id:
            return None
        return next(
            (item for item in document.resources if item.resource_id == resource_id),
            None,
        )

    def commit_cursor(self, project_id: str, cursor: str) -> ManagedResourceDocument:
        with self._lock:
            document = self.load()
            if document.project_id not in {None, project_id}:
                raise ValueError("Cursor belongs to another Conductor project.")
            document.project_id = project_id
            document.committed_cursor = cursor
            self._write(document)
            return document

    def _write(self, document: ManagedResourceDocument) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = document.model_dump_json(indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(
            prefix=".managed-resources.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


__all__ = ["ManagedResourceStore"]
