"""Safe document editing and search inside an AIM knowledge-base repo."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml
from pydantic import ValidationError


MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_SEARCH_FILE_BYTES = 512 * 1024
MAX_SEARCH_RESULTS = 100

TEXT_SUFFIXES = {
    "",
    ".csv",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".sql",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

_PROTECTED_PREFIXES = (
    ".git/",
    ".aim-actuals/",
    "runs/",
    "state/",
)


class DocumentError(ValueError):
    """Invalid document path, content, or operation."""


class DocumentConflictError(DocumentError):
    def __init__(self, current_revision: str) -> None:
        super().__init__("document changed since it was opened")
        self.current_revision = current_revision


@dataclass(frozen=True, slots=True)
class KbDocument:
    path: str
    content: str
    revision: str
    size: int
    mtime: float
    writable: bool

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "content": self.content,
            "revision": self.revision,
            "size": self.size,
            "mtime": self.mtime,
            "writable": self.writable,
        }


@dataclass(frozen=True, slots=True)
class KbSearchResult:
    path: str
    line: int
    excerpt: str
    matches: int

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "excerpt": self.excerpt,
            "matches": self.matches,
        }


def _normalize_relative_path(path: str) -> str:
    candidate = path.strip().replace("\\", "/")
    pure = PurePosixPath(candidate)
    if (
        not candidate
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise DocumentError("path must be a safe KB-relative file path")
    return pure.as_posix()


def _resolve_path(kb_root: Path, path: str) -> tuple[str, Path]:
    relative = _normalize_relative_path(path)
    root = kb_root.resolve(strict=False)
    target = (root / relative).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise DocumentError("path escapes the KB root") from exc
    return relative, target


def is_writable_document(path: str) -> bool:
    relative = _normalize_relative_path(path)
    lowered = relative.lower()
    if lowered.startswith(_PROTECTED_PREFIXES):
        return False
    return PurePosixPath(relative).suffix.lower() in TEXT_SUFFIXES


def _revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_document(kb_root: Path, path: str) -> KbDocument:
    relative, target = _resolve_path(kb_root, path)
    if not target.is_file():
        raise FileNotFoundError(relative)
    payload = target.read_bytes()
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise DocumentError("document exceeds the 1 MiB editor limit")
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError("document is not UTF-8 text") from exc
    stat = target.stat()
    return KbDocument(
        path=relative,
        content=content,
        revision=_revision(payload),
        size=stat.st_size,
        mtime=stat.st_mtime,
        writable=is_writable_document(relative),
    )


def _validate_write(path: str, content: str) -> tuple[str, bytes]:
    relative = _normalize_relative_path(path)
    if not is_writable_document(relative):
        raise DocumentError("generated evidence and non-text files are read-only")
    _validate_structured_content(relative, content)
    payload = content.encode("utf-8")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise DocumentError("document exceeds the 1 MiB editor limit")
    return relative, payload


def _validate_structured_content(path: str, content: str) -> None:
    suffix = PurePosixPath(path).suffix.lower()
    try:
        parsed: object | None = None
        if suffix in {".yaml", ".yml"}:
            parsed = yaml.safe_load(content)
        elif suffix == ".json":
            parsed = json.loads(content)

        if path == "aim.yaml":
            from app.services.aim.models import AimManifest

            AimManifest.model_validate(parsed)
        elif path == "rulebook/rulebook.yaml":
            from app.services.aim.rulebook import RulebookManifest

            RulebookManifest.model_validate(parsed)
        elif path.startswith("modules/") and suffix == ".md":
            from app.agent.tools.builtin.skill import _parse_frontmatter
            from app.services.aim.models import UnitFrontmatter

            metadata, _body = _parse_frontmatter(content)
            UnitFrontmatter.model_validate(metadata)
        elif path.startswith("business-rules/") and suffix == ".md":
            from app.agent.tools.builtin.skill import _parse_frontmatter

            metadata, _body = _parse_frontmatter(content)
            unit = metadata.get("unit")
            if not isinstance(unit, str) or "/" not in unit:
                raise DocumentError(
                    "business-rule frontmatter requires unit: module/name"
                )
            if metadata.get("status") not in {"candidate", "confirmed"}:
                raise DocumentError(
                    "business-rule status must be candidate or confirmed"
                )
    except DocumentError:
        raise
    except (json.JSONDecodeError, yaml.YAMLError, ValidationError, ValueError) as exc:
        raise DocumentError(f"invalid structured document: {exc}") from exc


def _atomic_write(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = target.stat().st_mode if target.exists() else None
    handle, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if existing_mode is not None:
            os.chmod(temp_path, existing_mode)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def update_document(
    kb_root: Path,
    path: str,
    content: str,
    *,
    expected_revision: str,
) -> KbDocument:
    relative, payload = _validate_write(path, content)
    _resolved_relative, target = _resolve_path(kb_root, relative)
    if not target.is_file():
        raise FileNotFoundError(relative)
    current_revision = _revision(target.read_bytes())
    if current_revision != expected_revision:
        raise DocumentConflictError(current_revision)
    _atomic_write(target, payload)
    return read_document(kb_root, relative)


def create_document(kb_root: Path, path: str, content: str) -> KbDocument:
    relative, payload = _validate_write(path, content)
    _resolved_relative, target = _resolve_path(kb_root, relative)
    if target.exists():
        raise FileExistsError(relative)
    _atomic_write(target, payload)
    return read_document(kb_root, relative)


def search_documents(
    kb_root: Path,
    query: str,
    *,
    path_prefix: str | None = None,
    limit: int = 50,
) -> list[KbSearchResult]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return []
    prefix = (
        _normalize_relative_path(path_prefix).rstrip("/") + "/" if path_prefix else ""
    )
    capped_limit = max(1, min(limit, MAX_SEARCH_RESULTS))
    results: list[KbSearchResult] = []
    root = kb_root.resolve(strict=False)

    for path in sorted(root.rglob("*")):
        if len(results) >= capped_limit:
            break
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/") or (prefix and not relative.startswith(prefix)):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        path_folded = relative.casefold()
        if all(term in path_folded for term in terms):
            results.append(
                KbSearchResult(
                    path=relative,
                    line=0,
                    excerpt=relative,
                    matches=sum(path_folded.count(term) for term in terms),
                )
            )
            if len(results) >= capped_limit:
                break

        for line_number, line in enumerate(text.splitlines(), start=1):
            folded = line.casefold()
            if not all(term in folded for term in terms):
                continue
            excerpt = " ".join(line.strip().split())
            results.append(
                KbSearchResult(
                    path=relative,
                    line=line_number,
                    excerpt=excerpt[:240],
                    matches=sum(folded.count(term) for term in terms),
                )
            )
            if len(results) >= capped_limit:
                break

    return sorted(results, key=lambda item: (-item.matches, item.path, item.line))
