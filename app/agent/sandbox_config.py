"""Config schema and file I/O for ``{CONFIG_DIR}/sandbox.yaml``.

User-configurable extension to the sandbox denylist: a list of glob
patterns that, when matched against a resolved absolute path, cause the
sandbox to reject access.  Patterns ship seeded with ``**/.env`` and
``**/.env.*`` on first run so secret files are protected by default;
users can edit/remove them via the Settings UI.

File shape (YAML)::

    denied_patterns:
      - "**/.env"
      - "**/.env.*"
      - "**/secrets/**"
    worktree_location: repository
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings

_CONFIG_FILENAME = "sandbox.yaml"

#: Patterns seeded into a freshly-created ``sandbox.yaml``.  Chosen to
#: cover the most common "sensitive file" case without being noisy.
DEFAULT_DENIED_PATTERNS: tuple[str, ...] = (
    "**/.env",
    "**/.env.*",
)


class SandboxFileConfig(BaseModel):
    """Top-level shape of ``sandbox.yaml``."""

    model_config = ConfigDict(extra="forbid")

    denied_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_DENIED_PATTERNS),
        description="Glob patterns seeded from DEFAULT_DENIED_PATTERNS when not specified.",
    )
    worktree_location: Literal["repository", "user_data"] = Field(
        default="repository",
        description=(
            "Store managed worktrees under the repository's .evoflux directory "
            "or the per-user EvoFlux data directory."
        ),
    )


def repository_worktree_root(source: Path) -> Path:
    """Return the repository-local managed worktree root."""
    return source.expanduser().resolve() / ".evoflux" / "worktrees"


def user_data_worktree_root(source: Path) -> Path:
    """Return the legacy per-user managed worktree root for *source*."""
    import hashlib

    resolved = source.expanduser().resolve()
    key = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:10]
    return (
        Path(settings.EVOFLUX_DATA_DIR) / "worktrees" / f"{resolved.name}-{key}"
    ).resolve()


def managed_worktree_roots(source: Path) -> tuple[Path, Path]:
    """Return all recognized roots, including the legacy user-data root."""
    return repository_worktree_root(source), user_data_worktree_root(source)


def selected_worktree_root(source: Path, *, create: bool = True) -> Path:
    """Resolve the configured root and optionally create it."""
    cfg = load_config()
    root = (
        repository_worktree_root(source)
        if cfg.worktree_location == "repository"
        else user_data_worktree_root(source)
    )
    if create:
        if cfg.worktree_location == "repository":
            ensure_repository_worktrees_ignored(source)
        root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def ensure_repository_worktrees_ignored(source: Path) -> None:
    """Locally ignore ``.evoflux/worktrees`` without editing project files."""
    source = source.expanduser().resolve()
    marker = source / ".git"
    if marker.is_dir():
        git_dir = marker
    elif marker.is_file():
        first_line = marker.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if not first_line.lower().startswith(prefix):
            return
        raw_git_dir = Path(first_line[len(prefix) :].strip())
        git_dir = (
            raw_git_dir if raw_git_dir.is_absolute() else (source / raw_git_dir)
        ).resolve()
        common_file = git_dir / "commondir"
        if common_file.exists():
            raw_common = Path(common_file.read_text(encoding="utf-8").strip())
            git_dir = (
                raw_common if raw_common.is_absolute() else git_dir / raw_common
            ).resolve()
    else:
        return

    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    pattern = "/.evoflux/worktrees/"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if pattern in {line.strip() for line in existing.splitlines()}:
        return
    separator = "" if not existing or existing.endswith("\n") else "\n"
    _atomic_write_text(exclude, f"{existing}{separator}{pattern}\n")


def config_path() -> Path:
    """Return the resolved path to ``sandbox.yaml``."""
    return Path(settings.EVOFLUX_CONFIG_DIR) / _CONFIG_FILENAME


def load_config(path: Path | None = None) -> SandboxFileConfig:
    """Load ``sandbox.yaml`` from disk.

    When the file does not exist, returns the seed defaults without
    writing — the file is only created on the first PUT from the
    Settings UI (or whenever the user hand-edits the file).  Empty/blank
    patterns are dropped silently.

    Raises ``ValueError`` if the file exists but is malformed.
    """
    resolved = path or config_path()
    if not resolved.exists():
        return SandboxFileConfig()

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {resolved}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{resolved}: expected a YAML mapping at top level")

    cfg = SandboxFileConfig.model_validate(raw)
    cfg.denied_patterns = [p for p in cfg.denied_patterns if p.strip()]
    return cfg


def save_config(cfg: SandboxFileConfig, path: Path | None = None) -> Path:
    """Persist ``cfg`` to disk atomically. Returns the resolved path."""
    resolved = path or config_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    payload = cfg.model_dump(mode="json")
    text = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)

    # Atomic write: tmp file in same dir, then rename.
    _atomic_write_text(resolved, text)

    logger.info(
        "sandbox_config_saved path={} patterns={} worktree_location={}",
        resolved,
        len(cfg.denied_patterns),
        cfg.worktree_location,
    )
    return resolved


def _atomic_write_text(resolved: Path, text: str) -> None:
    """Write UTF-8 text through a sibling temp file and atomic replace."""
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{resolved.name}.", suffix=".tmp", dir=resolved.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, resolved)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
