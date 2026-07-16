"""Sandbox configuration and path-validation utilities for computer tools.

The sandbox uses a **denylist** model: agent filesystem operations may touch
any path on disk *except* paths that resolve under one of the denied roots.
By default the denied roots are:

- ``EVOFLUX_DATA_DIR``    — EvoFlux's SQLite DB and other internal data.
- ``EVOFLUX_STATE_DIR``   — logs, telemetry, OTEL rollups
- ``EVOFLUX_CACHE_DIR``   — regeneratable cache including OAuth tokens

User uploads live *inside* the per-session workspace
(``{workspace}/<sid>/uploads/``) and are therefore reachable by the
agent's fs tools as the relative path ``uploads/<filename>``.

All relative paths resolve under ``workspace_root`` (the implicit "current
directory" for the agent).  Absolute paths anywhere on the filesystem are
accepted as long as they don't fall under a denied root.

Symlink rejection
-----------------
Symlinks whose target lands inside a denied root are rejected.

Tilde expansion
---------------
Tilde paths (``~/...``) are rejected at the API surface.

Command validation
------------------
Shell-command validation lives in :class:`PermissionService`
(``app.agent.permission``).  The sandbox additionally provides
:meth:`SandboxConfig.check_command` — a best-effort scanner that walks
shell-tokenised commands looking for path arguments inside denied roots
or matching deny-patterns.
"""

from __future__ import annotations

import contextvars
import fnmatch
import os
import shlex
import stat as stat_module
from pathlib import Path

from loguru import logger

from app.core.config import settings

# ── Module-level defaults (no env-var overrides) ──────────────────────────
DEFAULT_MAX_EXECUTION_SECONDS = 120
DEFAULT_MAX_OUTPUT_BYTES = 131072
DEFAULT_ALLOW_NETWORK = True

# ── Context-aware Sandbox ───────────────────────────────────────────────

_sandbox_ctx: contextvars.ContextVar["SandboxConfig"] = contextvars.ContextVar(
    "sandbox_ctx"
)


def get_sandbox() -> "SandboxConfig":
    """Return the active SandboxConfig for the current context."""
    try:
        return _sandbox_ctx.get()
    except LookupError:
        return _get_default_sandbox()


def set_sandbox(sandbox: "SandboxConfig") -> contextvars.Token:
    """Set the active SandboxConfig for the current context."""
    return _sandbox_ctx.set(sandbox)


class SandboxConfig:
    """Denylist-based sandbox for the agent's filesystem tools.

    All relative paths resolve under ``workspace_root``.
    Absolute paths are accepted as-is, subject to the denylist check.
    """

    def __init__(
        self,
        workspace: str | None = None,
        session_id: str | None = None,
        denied_roots: list[Path] | None = None,
        denied_patterns: list[str] | None = None,
        max_execution_seconds: int | None = None,
        max_output_bytes: int | None = None,
        allow_network: bool | None = None,
        # Other repos in the same CodingProject, if this session is
        # project-scoped. Lets tools that call get_sandbox() (e.g.
        # code_search/code_neighbors/code_references with scope='project')
        # see the full repo set without a model-facing "workspace_paths"
        # argument on every one of them.
        extra_workspace_paths: list[str] | None = None,
        # AIM mode only: paths (typically base-source repos) that remain
        # readable — they are NOT in denied_roots, so read/search/grep tools
        # still work — but are rejected by write-path tools (write/edit/
        # patch/rm). See validate_path's is_write param.
        read_only_paths: list[str] | None = None,
        # Kept for backward compatibility — ignored.
        memory: str | None = None,
    ):
        if not workspace:
            raise ValueError(
                "SandboxConfig requires an explicit workspace path; "
                "no implicit default is provided."
            )
        self.workspace_root: Path = Path(workspace).resolve()
        self.session_id = session_id
        self.extra_workspace_paths: list[str] = list(extra_workspace_paths or [])
        self.read_only_paths: list[Path] = [
            Path(p).resolve() for p in (read_only_paths or [])
        ]
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        if denied_roots is None:
            denied_roots = [
                Path(settings.EVOFLUX_DATA_DIR).resolve(),
                Path(settings.EVOFLUX_STATE_DIR).resolve(),
                Path(settings.EVOFLUX_CACHE_DIR).resolve(),
            ]
        self.denied_roots: list[Path] = list(denied_roots)

        if denied_patterns is None:
            try:
                from app.agent.sandbox_config import load_config

                denied_patterns = list(load_config().denied_patterns)
            except (ValueError, OSError) as exc:
                logger.warning("sandbox_patterns_load_failed err={}", exc)
                denied_patterns = []
        self.denied_patterns: list[str] = list(denied_patterns)

        self.max_execution_seconds: int = (
            max_execution_seconds or DEFAULT_MAX_EXECUTION_SECONDS
        )
        self.max_output_bytes: int = max_output_bytes or DEFAULT_MAX_OUTPUT_BYTES
        self.allow_network: bool = (
            allow_network if allow_network is not None else DEFAULT_ALLOW_NETWORK
        )

    def metadata_path(self, name: str) -> Path:
        """Return a path under ``.EvoFlux`` for this sandbox context."""
        from app.agent.artifacts import session_artifact_dir

        return session_artifact_dir(self.session_id) / name

    # ── Path validation ───────────────────────────────────────────────────

    def _is_denied(self, resolved: Path) -> Path | str | None:
        """Return the denied root or glob pattern that matched, or None."""
        if _path_is_under(resolved, self.workspace_root):
            return None
        allowed = _allowed_internal_roots(self.session_id)
        if any(_path_is_under(resolved, root) for root in allowed):
            return None
        for denied in self.denied_roots:
            if _path_is_under(resolved, denied):
                return denied
        resolved_str = str(resolved)
        for pattern in self.denied_patterns:
            if fnmatch.fnmatchcase(resolved_str, pattern):
                return pattern
        return None

    def _is_read_only(self, resolved: Path) -> Path | None:
        for ro_root in self.read_only_paths:
            if _path_is_under(resolved, ro_root):
                return ro_root
        return None

    def validate_path(self, path: str | Path, *, is_write: bool = False) -> Path:
        """Resolve *path* and verify it's not inside a denied root.

        Args:
            is_write: pass ``True`` from write-path tools (write/edit/patch/
                rm) so a path under ``read_only_paths`` is rejected even
                though it's readable — the AIM base-source read-only rule
                (documents/research/aim-framework.md §3.3): agents may read
                the base source but must never modify it, while ordinary
                read/search tools stay unaffected.

        Raises:
            PermissionError: if the resolved path falls under a denied
                root, contains a symlink whose target is denied, uses
                tilde expansion, or (when ``is_write``) falls under a
                read-only root.
        """
        if str(path).startswith("~"):
            raise PermissionError(
                f"Tilde paths are not allowed inside the sandbox: {path}"
            )

        p = Path(path)
        candidate = p if p.is_absolute() else self.workspace_root / p

        # Walk every component looking for symlinks BEFORE resolve() follows them.
        check = candidate
        while True:
            try:
                st = os.lstat(check)
                if stat_module.S_ISLNK(st.st_mode):
                    target = Path(os.readlink(check))
                    if not target.is_absolute():
                        target = check.parent / target
                    target_resolved = target.resolve()
                    denied = self._is_denied(target_resolved)
                    if denied is not None:
                        logger.warning(
                            "sandbox_symlink_to_denied path={} target={} denied_root={}",
                            candidate,
                            target_resolved,
                            denied,
                        )
                        raise PermissionError(
                            f"Symlink target is inside a denied root: "
                            f"{candidate} -> {target_resolved} (denied: {denied})"
                        )
            except (FileNotFoundError, NotADirectoryError):
                pass
            parent = check.parent
            if parent == check:
                break
            check = parent

        resolved = candidate.resolve()

        denied = self._is_denied(resolved)
        if denied is not None:
            logger.warning(
                "sandbox_path_denied path={} denied_root={}",
                resolved,
                denied,
            )
            raise PermissionError(
                f"Path '{resolved}' is inside a denied sandbox root: {denied}"
            )

        if is_write:
            read_only_root = self._is_read_only(resolved)
            if read_only_root is not None:
                logger.warning(
                    "sandbox_write_denied_read_only path={} read_only_root={}",
                    resolved,
                    read_only_root,
                )
                raise PermissionError(
                    f"Path '{resolved}' is read-only in this session (base "
                    f"source, never written to): {read_only_root}"
                )

        return resolved

    # ── Command validation (best-effort) ─────────────────────────────────

    def check_command(self, command: str) -> tuple[Path, str] | None:
        """Best-effort scan of *command* for arguments inside denied paths,
        plus (if ``read_only_paths`` is set) shell redirection targets
        (``>``/``>>``) landing inside one of them.

        The redirect check is deliberately narrow — it catches the most
        common accidental/naive write pattern with no false positives
        (a redirect is unambiguously a write), not every way a shell
        command could modify a read-only file (``sed -i``, a script's own
        file-write flags, etc. are not caught). OS-level permissions on the
        base-source repo remain the last line of defence, same caveat the
        denied-root scan below already carries.
        """
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return None

        for index, tok in enumerate(tokens):
            if not _looks_path_like(tok):
                continue
            expanded = os.path.expanduser(tok)
            p = Path(expanded)
            candidate = p if p.is_absolute() else (self.workspace_root / p)
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            denied = self._is_denied(resolved)
            if denied is not None:
                logger.warning(
                    "sandbox_command_denied token={} resolved={} denied={}",
                    tok,
                    resolved,
                    denied,
                )
                return resolved, str(denied)
            if (
                self.read_only_paths
                and index > 0
                and tokens[index - 1] in (">", ">>")
            ):
                read_only_root = self._is_read_only(resolved)
                if read_only_root is not None:
                    logger.warning(
                        "sandbox_command_write_denied_read_only token={} resolved={} read_only_root={}",
                        tok,
                        resolved,
                        read_only_root,
                    )
                    return resolved, str(read_only_root)
        return None

    # ── Display helpers ──────────────────────────────────────────────────

    def display_path(self, resolved: Path) -> str:
        """Return a display path for ``resolved``."""
        if _path_is_under(resolved, self.workspace_root):
            rel = resolved.relative_to(self.workspace_root)
            return str(self.workspace_root) if str(rel) == "." else str(rel)
        return str(resolved)


def _path_is_under(child: Path, parent: Path) -> bool:
    """True if *child* equals or is contained by *parent* (after resolve)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _allowed_internal_roots(session_id: str | None) -> list[Path]:
    """Return internal EvoFlux paths agents may inspect."""
    roots = [Path(settings.EVOFLUX_STATE_DIR).resolve() / "logs"]
    if session_id:
        from app.agent.artifacts import session_artifact_dir

        roots.append(session_artifact_dir(session_id).resolve())
    return roots


def _looks_path_like(token: str) -> bool:
    if not token:
        return False
    if token.startswith("-"):
        return False
    if "/" in token:
        return True
    if token.startswith("~"):
        return True
    if token.startswith("."):
        return True
    return False


_default_sandbox_instance: SandboxConfig | None = None


def _get_default_sandbox() -> SandboxConfig:
    global _default_sandbox_instance
    if _default_sandbox_instance is None:
        import tempfile

        _default_sandbox_instance = SandboxConfig(
            workspace=str(Path(tempfile.gettempdir()) / "EvoFlux-default-sandbox"),
        )
    return _default_sandbox_instance
