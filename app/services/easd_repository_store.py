"""Version-controlled repository store for normative EASD artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal
from uuid import UUID, uuid4

import yaml

from app.services.easd_setup_service import (
    EASD_MANIFEST,
    normalize_data_directory,
)

EasdArtifactKind = Literal[
    "missions",
    "reviews",
    "verifications",
    "evidence",
    "deviations",
    "events",
]

_RUN_SUFFIX = re.compile(
    r"--(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)
_MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
_RUN_ROOTS: dict[UUID, Path] = {}


class EasdStoreError(RuntimeError):
    """Base repository-store error."""


class EasdStoreConflict(EasdStoreError):
    """The repository document changed since the caller's snapshot."""


class EasdStoreNotFound(EasdStoreError):
    """The requested repository artifact does not exist."""


def _stable_yaml(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    )


def document_hash(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("document_hash", None)
    raw = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise EasdStoreNotFound(f"EASD document not found: {path}")
    if path.stat().st_size > _MAX_DOCUMENT_BYTES:
        raise EasdStoreError(f"EASD document exceeds 8 MiB: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise EasdStoreError(f"Invalid EASD YAML document: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EasdStoreError(f"EASD document must contain a mapping: {path}")
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "run")[:80]


def spec_catalog_directory(title: str, run_id: str | UUID) -> str:
    """Return the stable data-directory-relative catalogue path for a Run Spec."""

    normalized = str(UUID(str(run_id)))
    return f"specs/{_slug(title)}--{normalized}"


@dataclass(frozen=True, slots=True)
class EasdStoredRun:
    root: Path
    directory: Path
    run: dict[str, Any]


class EasdRepositoryStore:
    """Atomic, hash-addressed EASD documents in one owning repository."""

    def __init__(self, repository_root: str | Path) -> None:
        self.root = Path(repository_root).expanduser().resolve()
        if not self.root.is_dir():
            raise EasdStoreError(f"EASD repository is unavailable: {self.root}")
        manifest_path = self.root / EASD_MANIFEST
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EasdStoreError(f"Cannot read EASD manifest: {manifest_path}") from exc
        if not isinstance(manifest, dict):
            raise EasdStoreError("EASD manifest must contain an object")
        relative = normalize_data_directory(str(manifest.get("data_directory") or ""))
        self.data_directory = relative
        self.data_path = self._inside(relative)
        self.specs_path = self._inside(relative / "specs")
        self.runs_path = self._inside(relative / "runs")
        self.local_path = self._inside(Path(".evoflux/easd/.local"))

    def _inside(self, relative: Path) -> Path:
        candidate = self.root / relative
        resolved = candidate.resolve(strict=False)
        if resolved != self.root and self.root not in resolved.parents:
            raise EasdStoreError(f"EASD store path escapes repository: {relative}")
        if candidate.is_symlink():
            raise EasdStoreError(f"EASD store path must not be a symlink: {relative}")
        return candidate

    def _run_directory(self, run_id: str | UUID) -> Path:
        normalized = str(UUID(str(run_id)))
        matches = list(self.runs_path.glob(f"*--{normalized}"))
        if len(matches) != 1 or not matches[0].is_dir() or matches[0].is_symlink():
            raise EasdStoreNotFound(f"EASD run {normalized} was not found")
        return matches[0]

    def _spec_directory(self, run_id: str | UUID) -> Path:
        normalized = str(UUID(str(run_id)))
        matches = list(self.specs_path.glob(f"*--{normalized}"))
        if len(matches) != 1 or not matches[0].is_dir() or matches[0].is_symlink():
            raise EasdStoreNotFound(
                f"Published EASD specification {normalized} was not found"
            )
        return matches[0]

    @contextmanager
    def _lock(self, key: str, *, timeout: float = 5.0) -> Iterator[None]:
        locks = self.local_path / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        lock = locks / f"{key}.lock"
        deadline = time.monotonic() + timeout
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 60:
                        lock.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise EasdStoreConflict(f"EASD document is busy: {key}") from None
                time.sleep(0.025)
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(descriptor)
            lock.unlink(missing_ok=True)

    def _write_document(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        expected_hash: str | None = None,
        create_only: bool = False,
    ) -> dict[str, Any]:
        key = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
        with self._lock(key):
            current: dict[str, Any] | None = None
            if path.exists():
                current = _read_yaml(path)
            if create_only and current is not None:
                raise EasdStoreConflict(f"EASD document already exists: {path}")
            if expected_hash is not None:
                current_hash = document_hash(current) if current is not None else None
                if current_hash != expected_hash:
                    raise EasdStoreConflict(
                        "EASD repository document changed; reload and review the diff"
                    )
            output = dict(payload)
            output["document_hash"] = document_hash(output)
            _atomic_write(path, _stable_yaml(output))
            return output

    def create_run(
        self,
        *,
        run: dict[str, Any],
        intent: dict[str, Any] | None,
    ) -> EasdStoredRun:
        run_id = str(UUID(str(run["id"])))
        directory = self.runs_path / f"{_slug(str(run['title']))}--{run_id}"
        if directory.exists():
            raise EasdStoreConflict(f"EASD run already exists: {run_id}")
        directory.mkdir(parents=True)
        for name in (
            "specifications",
            "plans",
            "missions",
            "reviews",
            "verifications",
            "evidence",
            "deviations",
            "events",
        ):
            (directory / name).mkdir()
        projection = dict(run)
        projection.setdefault("store_generation", 1)
        projection.setdefault("owner_repository", self.root.name)
        stored = self._write_document(
            directory / "run.yaml", projection, create_only=True
        )
        if intent is not None:
            self._write_document(
                directory / "intent.yaml",
                {"run_id": run_id, **intent},
                create_only=True,
            )
        self.append_event(
            run_id,
            {
                "event": "intent_created" if intent is not None else "run_created",
                "from_status": None,
                "to_status": run["status"],
                "actor": "human",
            },
        )
        _RUN_ROOTS[UUID(run_id)] = self.root
        return EasdStoredRun(self.root, directory, stored)

    def load_run(self, run_id: str | UUID) -> EasdStoredRun:
        directory = self._run_directory(run_id)
        normalized = UUID(str(run_id))
        _RUN_ROOTS[normalized] = self.root
        return EasdStoredRun(self.root, directory, _read_yaml(directory / "run.yaml"))

    def list_runs(self) -> list[EasdStoredRun]:
        if not self.runs_path.is_dir():
            return []
        rows: list[EasdStoredRun] = []
        for directory in sorted(self.runs_path.iterdir()):
            if (
                not directory.is_dir()
                or directory.is_symlink()
                or not _RUN_SUFFIX.search(directory.name)
            ):
                continue
            try:
                rows.append(
                    EasdStoredRun(
                        self.root,
                        directory,
                        _read_yaml(directory / "run.yaml"),
                    )
                )
                _RUN_ROOTS[UUID(str(rows[-1].run["id"]))] = self.root
            except EasdStoreError:
                continue
        return rows

    def update_run(
        self,
        run_id: str | UUID,
        run: dict[str, Any],
        *,
        expected_hash: str,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stored = self.load_run(run_id)
        output = dict(run)
        output["store_generation"] = int(stored.run.get("store_generation") or 0) + 1
        updated = self._write_document(
            stored.directory / "run.yaml",
            output,
            expected_hash=expected_hash,
        )
        if event is not None:
            self.append_event(
                run_id, event | {"run_document_hash": updated["document_hash"]}
            )
        return updated

    def write_revision(
        self,
        run_id: str | UUID,
        *,
        kind: Literal["specifications", "plans"],
        version: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        directory = self._run_directory(run_id)
        return self._write_document(
            directory / kind / f"{version:04d}.yaml",
            payload,
            create_only=True,
        )

    def replace_revision(
        self,
        run_id: str | UUID,
        *,
        kind: Literal["specifications", "plans"],
        version: int,
        payload: dict[str, Any],
        expected_hash: str,
    ) -> dict[str, Any]:
        directory = self._run_directory(run_id)
        path = directory / kind / f"{version:04d}.yaml"
        current = _read_yaml(path)
        if current.get("status") == "accepted":
            raise EasdStoreConflict(
                "Accepted EASD revisions are immutable; create a new revision"
            )
        return self._write_document(
            path,
            payload,
            expected_hash=expected_hash,
        )

    def read_revisions(
        self,
        run_id: str | UUID,
        kind: Literal["specifications", "plans"],
    ) -> list[dict[str, Any]]:
        directory = self._run_directory(run_id) / kind
        return [_read_yaml(path) for path in sorted(directory.glob("[0-9]*.yaml"))]

    def publish_spec_revision(
        self,
        run_id: str | UUID,
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish one accepted Run snapshot into the common Spec catalogue."""

        normalized_run_id = str(UUID(str(run_id)))
        version = int(revision.get("version") or 0)
        content_hash = str(revision.get("content_hash") or "")
        specification = revision.get("spec")
        if (
            revision.get("status") != "accepted"
            or version < 1
            or len(content_hash) != 64
            or not isinstance(specification, dict)
            or not str(specification.get("title") or "").strip()
        ):
            raise EasdStoreError(
                "Only a complete accepted EASD Spec revision can be published"
            )
        title = str(specification["title"]).strip()
        directory = self.data_path / spec_catalog_directory(title, normalized_run_id)
        if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
            raise EasdStoreConflict(
                f"EASD specification catalogue path is invalid: {directory}"
            )
        revisions = directory / "revisions"
        revisions.mkdir(parents=True, exist_ok=True)
        if revisions.is_symlink() or not revisions.is_dir():
            raise EasdStoreConflict(
                "EASD specification revisions must be a repository-local directory"
            )
        revision_path = revisions / f"{version:04d}.yaml"
        published_payload = {
            **revision,
            "run_snapshot": (
                self._run_directory(normalized_run_id)
                / "specifications"
                / f"{version:04d}.yaml"
            )
            .relative_to(self.data_path)
            .as_posix(),
        }
        if revision_path.exists():
            current_revision = _read_yaml(revision_path)
            if (
                current_revision.get("content_hash") != content_hash
                or current_revision.get("status") != "accepted"
            ):
                raise EasdStoreConflict(
                    "Published EASD Spec revision conflicts with repository state"
                )
        else:
            self._write_document(
                revision_path,
                published_payload,
                create_only=True,
            )

        index_path = directory / "index.yaml"
        current_index = _read_yaml(index_path) if index_path.exists() else None
        if current_index is not None:
            current_version = int(current_index.get("current_revision") or 0)
            if current_version > version:
                raise EasdStoreConflict(
                    "Published EASD Spec index already points to a newer revision"
                )
            if (
                current_version == version
                and current_index.get("current_hash") != content_hash
            ):
                raise EasdStoreConflict(
                    "Published EASD Spec index conflicts at the same revision"
                )
        index_payload = {
            "id": normalized_run_id,
            "title": title,
            "status": "accepted",
            "current_revision": version,
            "current_hash": content_hash,
            "current_path": f"revisions/{version:04d}.yaml",
            "owning_run_id": normalized_run_id,
            "updated_at": revision.get("accepted_at") or revision.get("created_at"),
        }
        return self._write_document(
            index_path,
            index_payload,
            expected_hash=(
                document_hash(current_index) if current_index is not None else None
            ),
            create_only=current_index is None,
        )

    def load_published_spec(self, run_id: str | UUID) -> dict[str, Any]:
        """Load the common catalogue index and its current accepted revision."""

        directory = self._spec_directory(run_id)
        index = _read_yaml(directory / "index.yaml")
        current_path = index.get("current_path")
        if not isinstance(current_path, str):
            raise EasdStoreError("Published EASD Spec index has no current path")
        revision_path = directory / current_path
        resolved = revision_path.resolve(strict=False)
        if resolved != directory and directory not in resolved.parents:
            raise EasdStoreError("Published EASD Spec path escapes its catalogue")
        revision = _read_yaml(revision_path)
        if revision.get("content_hash") != index.get("current_hash"):
            raise EasdStoreConflict("Published EASD Spec hash does not match its index")
        return {"directory": directory, "index": index, "revision": revision}

    def append_artifact(
        self,
        run_id: str | UUID,
        kind: EasdArtifactKind,
        artifact_id: str | UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        directory = self._run_directory(run_id)
        return self._write_document(
            directory / kind / f"{artifact_id}.yaml",
            payload,
            create_only=True,
        )

    def upsert_artifact(
        self,
        run_id: str | UUID,
        kind: EasdArtifactKind,
        artifact_id: str | UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or CAS-update a mutable projection such as a mission status."""

        directory = self._run_directory(run_id)
        path = directory / kind / f"{artifact_id}.yaml"
        if not path.exists():
            return self._write_document(
                path,
                payload,
                create_only=True,
            )
        current = _read_yaml(path)
        return self._write_document(
            path,
            payload,
            expected_hash=document_hash(current),
        )

    def read_artifacts(
        self, run_id: str | UUID, kind: EasdArtifactKind
    ) -> list[dict[str, Any]]:
        directory = self._run_directory(run_id) / kind
        return [_read_yaml(path) for path in sorted(directory.glob("*.yaml"))]

    def read_events(
        self,
        run_id: str | UUID,
        *,
        limit: int = 1_000,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Read a bounded ordered event ledger without hiding valid siblings."""

        if limit < 1 or limit > 1_000:
            raise EasdStoreError("EASD event read limit must be between 1 and 1000")
        directory = self._run_directory(run_id) / "events"
        paths = sorted(directory.glob("*.yaml"))
        diagnostics: list[dict[str, str]] = []
        if len(paths) > limit:
            diagnostics.append(
                {
                    "code": "events_truncated",
                    "message": f"Showing the latest {limit} of {len(paths)} events.",
                }
            )
            paths = paths[-limit:]
        events: list[dict[str, Any]] = []
        for path in paths:
            try:
                payload = _read_yaml(path)
                sequence = int(payload.get("sequence") or 0)
                if sequence < 1 or not str(payload.get("event") or "").strip():
                    raise EasdStoreError("event requires a sequence and event name")
            except (EasdStoreError, TypeError, ValueError) as exc:
                diagnostics.append(
                    {
                        "code": "event_document_invalid",
                        "message": f"Skipped {path.name}: {exc}",
                    }
                )
                continue
            events.append(payload)
        events.sort(key=lambda item: int(item["sequence"]))
        return events, diagnostics

    def append_event(
        self, run_id: str | UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        directory = self._run_directory(run_id)
        events = directory / "events"
        with self._lock(f"run-{UUID(str(run_id))}-events"):
            sequence = len(list(events.glob("*.yaml"))) + 1
            event_id = str(payload.get("id") or uuid4())
            return self._write_document(
                events / f"{sequence:06d}-{event_id}.yaml",
                {
                    "id": event_id,
                    "run_id": str(UUID(str(run_id))),
                    "sequence": sequence,
                    **payload,
                },
                create_only=True,
            )

    def write_convergence(
        self, run_id: str | UUID, report: dict[str, Any]
    ) -> dict[str, Any]:
        directory = self._run_directory(run_id)
        return self._write_document(
            directory / "convergence.yaml",
            report,
            create_only=True,
        )


def registered_run_root(run_id: str | UUID) -> Path | None:
    return _RUN_ROOTS.get(UUID(str(run_id)))


__all__ = [
    "EasdRepositoryStore",
    "EasdStoreConflict",
    "EasdStoreError",
    "EasdStoreNotFound",
    "EasdStoredRun",
    "document_hash",
    "registered_run_root",
    "spec_catalog_directory",
]
