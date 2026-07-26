"""Filesystem service for agent and skill ``.md`` files.

Thin wrapper around the agents and skills directories. Handles path
validation, filename derivation, and atomic writes. All paths are kept
inside the configured root directory — traversal attempts raise
``AgentFsPathError``.

Used by ``app.api.routes.agents`` and ``app.api.routes.skills``.  Validation
of YAML frontmatter happens in ``app.services.team_manager`` (agents) or
by re-parsing after write (skills).
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from loguru import logger

from app.core.config import settings


# ── Errors ───────────────────────────────────────────────────────────────────


class AgentFsPathError(ValueError):
    """Raised when a caller-supplied path escapes the managed directory."""


class AgentFsNotFoundError(FileNotFoundError):
    """Raised when the requested .md file does not exist."""


class AgentFsConflictError(ValueError):
    """Raised when a create would overwrite an existing file."""


# ── Validation ───────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024
_MAX_SKILL_BUNDLE_BYTES = 20 * 1024 * 1024
_MAX_SKILL_TEXT_PREVIEW_BYTES = 512 * 1024


def _validate_name(name: str) -> str:
    """Reject names that would escape the directory or break YAML parsing."""
    if not name or not _NAME_RE.match(name):
        raise AgentFsPathError(
            f"Invalid name '{name}'. Use letters, digits, '.', '_', '-' only "
            "(1-64 chars, must start with letter/digit)."
        )
    return name


def _validate_skill_name(name: str) -> Path:
    """Validate a flat or one-level-nested skill name.

    Accepts ``"my-skill"`` (flat) or ``"parent/sub"`` (one nested level).
    Rejects empty names, names with more than one ``/``, and any segment
    that fails :func:`_validate_name`.

    Returns a :class:`~pathlib.Path` with 1 or 2 components that can be
    safely joined under the skills root.
    """
    parts = name.split("/")
    if len(parts) > 2:
        raise AgentFsPathError(
            f"Skill name '{name}' is nested more than one level deep. "
            "Only one level of nesting is allowed (e.g. 'parent/sub')."
        )
    if not parts or not parts[0]:
        raise AgentFsPathError("Skill name cannot be empty.")
    return Path(*(_validate_name(p) for p in parts))


def _validate_agent_name(name: str) -> Path:
    parts = Path(name).parts
    if not parts:
        raise AgentFsPathError("Agent name cannot be empty.")
    return Path(*(_validate_name(part) for part in parts))


# ── Paths ────────────────────────────────────────────────────────────────────


def agents_dir() -> Path:
    return Path(settings.AGENTS_DIR).resolve()


def skills_dir() -> Path:
    return Path(settings.SKILLS_DIR).resolve()


def _agent_file(name: str) -> Path:
    root = agents_dir()
    rel = _validate_agent_name(name).with_suffix(".md")
    file = (root / rel).resolve()
    if not file.is_relative_to(root):
        raise AgentFsPathError(f"Path escapes agents directory: '{name}'.")
    return file


def _skill_file(name: str) -> Path:
    root = skills_dir()
    file = (root / _validate_skill_name(name) / "SKILL.md").resolve()
    if not file.is_relative_to(root):
        raise AgentFsPathError(f"Path escapes skills directory: '{name}'.")
    return file


def _validate_skill_resource_path(path: str) -> PurePosixPath:
    """Return a safe bundle-relative path.

    Resource paths use POSIX separators on every platform. ``SKILL.md`` is
    reserved for the dedicated ``content`` field.
    """
    if not path or "\\" in path:
        raise AgentFsPathError(f"Invalid skill resource path '{path}'.")
    rel = PurePosixPath(path)
    if (
        rel.is_absolute()
        or any(part in {"", ".", ".."} for part in rel.parts)
        or rel.name == "SKILL.md"
    ):
        raise AgentFsPathError(f"Invalid skill resource path '{path}'.")
    return rel


def _skill_resource_file(skill_dir: Path, path: str) -> Path:
    root = skill_dir.resolve()
    rel = _validate_skill_resource_path(path)
    file = (root / Path(*rel.parts)).resolve()
    if not file.is_relative_to(root):
        raise AgentFsPathError(f"Path escapes skill directory: '{path}'.")
    return file


# ── Atomic write ─────────────────────────────────────────────────────────────


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (tmp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


# ── Public dataclasses ───────────────────────────────────────────────────────


@dataclass
class AgentFileRecord:
    """On-disk representation of an agent .md file."""

    name: str
    path: str  # absolute path
    content: str  # raw file text (frontmatter + body)


@dataclass
class SkillFileRecord:
    """On-disk representation of a skill SKILL.md file."""

    name: str
    path: str
    content: str


@dataclass
class SkillBundleFileRecord:
    """A resource file stored next to a skill's ``SKILL.md``."""

    path: str
    size: int
    media_type: str
    content: str | None
    encoding: Literal["utf-8", "base64"] | None
    editable: bool


# ── Agents ───────────────────────────────────────────────────────────────────


def list_agents() -> list[str]:
    """Return the list of agent names (stem of each .md file)."""
    root = agents_dir()
    if not root.exists():
        return []
    from app.agent.loader import ensure_builtin_agent_blueprints

    coding_root = root / "coding"
    if any(coding_root.glob("*.md")):
        ensure_builtin_agent_blueprints(coding_root, mode="coding")
    return sorted(
        name
        for p in root.rglob("*.md")
        if (name := str(p.relative_to(root).with_suffix("")).replace("\\", "/"))
        != "coding/executor"
    )


def read_agent(name: str) -> AgentFileRecord:
    file = _agent_file(name)
    if not file.is_file():
        raise AgentFsNotFoundError(f"Agent '{name}' not found.")
    return AgentFileRecord(
        name=name, path=str(file), content=file.read_text(encoding="utf-8")
    )


def write_agent(name: str, content: str, *, create: bool) -> AgentFileRecord:
    """Write an agent .md file. Set *create* = True to require the file not
    already exist (POST semantics); False to allow overwrite (PUT semantics).
    """
    file = _agent_file(name)
    if create and file.exists():
        raise AgentFsConflictError(f"Agent '{name}' already exists.")
    _atomic_write(file, content)
    logger.info("agent_fs_write name={} bytes={}", name, len(content))
    return AgentFileRecord(name=name, path=str(file), content=content)


def delete_agent(name: str) -> None:
    file = _agent_file(name)
    if not file.is_file():
        raise AgentFsNotFoundError(f"Agent '{name}' not found.")
    file.unlink()
    logger.info("agent_fs_delete name={}", name)


# ── Skills ───────────────────────────────────────────────────────────────────


def list_skills() -> list[str]:
    """Return the list of skill names — directories containing SKILL.md.

    Supports a flat layout (``{root}/{name}/SKILL.md``) and one nested
    level (``{root}/{parent}/{sub}/SKILL.md``).  Sub-skills are returned
    as ``"parent/sub"``.
    """
    root = skills_dir()
    if not root.exists():
        return []
    names: list[str] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        if (p / "SKILL.md").is_file():
            names.append(p.name)
        # One level of nesting
        for nested in p.iterdir():
            if nested.is_dir() and (nested / "SKILL.md").is_file():
                names.append(f"{p.name}/{nested.name}")
    return sorted(names)


def read_skill(name: str) -> SkillFileRecord:
    file = _skill_file(name)
    if not file.is_file():
        raise AgentFsNotFoundError(f"Skill '{name}' not found.")
    return SkillFileRecord(
        name=name, path=str(file), content=file.read_text(encoding="utf-8")
    )


def write_skill(name: str, content: str, *, create: bool) -> SkillFileRecord:
    file = _skill_file(name)
    if create and file.exists():
        raise AgentFsConflictError(f"Skill '{name}' already exists.")
    if create and file.parent.is_dir():
        unrelated = [
            child
            for child in file.parent.iterdir()
            if not (child.is_dir() and (child / "SKILL.md").is_file())
        ]
        if unrelated:
            raise AgentFsConflictError(
                f"Skill bundle directory for '{name}' already contains files."
            )
    _atomic_write(file, content)
    logger.info("skill_fs_write name={} bytes={}", name, len(content))
    return SkillFileRecord(name=name, path=str(file), content=content)


def list_skill_bundle_files(skill_dir: Path) -> list[SkillBundleFileRecord]:
    """List resource files without following symlinks.

    Small UTF-8 files are returned inline for editing. Binary and oversized
    files remain visible as metadata without inflating the API response.
    """
    root = skill_dir.resolve()
    if not root.is_dir():
        raise AgentFsNotFoundError(f"Skill directory '{skill_dir}' not found.")
    records: list[SkillBundleFileRecord] = []
    for file in sorted(root.rglob("*")):
        if file.name == "SKILL.md" or not file.is_file() or file.is_symlink():
            continue
        try:
            resolved = file.resolve()
            resolved.relative_to(root)
            size = file.stat().st_size
        except (OSError, ValueError):
            continue
        media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        content: str | None = None
        encoding: str | None = None
        editable = size <= _MAX_SKILL_TEXT_PREVIEW_BYTES
        if editable:
            try:
                candidate = file.read_text(encoding="utf-8")
                if "\x00" in candidate:
                    editable = False
                else:
                    content = candidate
                    encoding = "utf-8"
            except (OSError, UnicodeDecodeError):
                editable = False
        records.append(
            SkillBundleFileRecord(
                path=resolved.relative_to(root).as_posix(),
                size=size,
                media_type=media_type,
                content=content,
                encoding=encoding,
                editable=editable,
            )
        )
    return records


def apply_skill_bundle_files(
    skill_dir: Path,
    files: list[tuple[str, str, str]],
    deleted_files: list[str],
) -> None:
    """Apply resource upserts and removals inside an existing skill bundle."""
    root = skill_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    decoded: list[tuple[Path, bytes]] = []
    total_bytes = 0
    seen: set[str] = set()
    for path, content, encoding in files:
        rel = _validate_skill_resource_path(path).as_posix()
        if rel in seen:
            raise AgentFsConflictError(f"Duplicate skill resource path '{rel}'.")
        seen.add(rel)
        try:
            payload = (
                content.encode("utf-8")
                if encoding == "utf-8"
                else base64.b64decode(content, validate=True)
            )
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise AgentFsPathError(f"Invalid {encoding} content for '{rel}'.") from exc
        if len(payload) > _MAX_SKILL_FILE_BYTES:
            raise AgentFsPathError(
                f"Skill resource '{rel}' exceeds the 2 MiB per-file limit."
            )
        total_bytes += len(payload)
        if total_bytes > _MAX_SKILL_BUNDLE_BYTES:
            raise AgentFsPathError("Skill resource updates exceed the 20 MiB limit.")
        decoded.append((_skill_resource_file(root, rel), payload))

    for path in deleted_files:
        file = _skill_resource_file(root, path)
        if file.is_symlink() or (file.exists() and not file.is_file()):
            raise AgentFsPathError(f"Skill resource '{path}' is not a regular file.")
        if file.is_file():
            file.unlink()
            parent = file.parent
            while parent != root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

    for file, payload in decoded:
        if file.is_symlink():
            raise AgentFsPathError(f"Skill resource '{file.name}' is a symlink.")
        file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=file.parent,
            prefix=f".{file.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        tmp_path.replace(file)


def delete_skill(name: str) -> None:
    file = _skill_file(name)
    if not file.is_file():
        raise AgentFsNotFoundError(f"Skill '{name}' not found.")
    file.unlink()
    # Remove the now-empty skill directory if nothing else sits alongside it.
    try:
        file.parent.rmdir()
    except OSError:
        # Directory not empty (e.g. reference/, scripts/, sub-skills) — leave it.
        pass
    else:
        # For a nested skill (parent/sub) the parent dir may now also be
        # empty — attempt to clean it up too.
        parent = file.parent.parent
        if parent != skills_dir():
            try:
                parent.rmdir()
            except OSError:
                pass
    logger.info("skill_fs_delete name={}", name)
