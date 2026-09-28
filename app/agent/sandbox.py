"""Workspace-allowlisted sandbox configuration for computer tools.

Agent filesystem operations are confined to the active workspace, explicitly
granted project roots, read-only roots, and session artifact locations.
Sensitive deny patterns are applied even inside allowed roots.

Those boundaries are enforced at the application layer. Child processes are
not wrapped in an operating-system sandbox, so command validation is a guardrail
rather than a containment boundary.

- ``EVOFLUX_DATA_DIR``    — EvoFlux's SQLite DB and other internal data.
- ``EVOFLUX_STATE_DIR``   — logs, telemetry, OTEL rollups
- ``EVOFLUX_CACHE_DIR``   — regeneratable cache including OAuth tokens

User uploads live in app-managed per-session storage. Every session sandbox
automatically mounts that directory as a read-only root, so Work and Coding
agents can inspect arbitrary attachments without modifying the upload or
polluting a repository.

All relative paths resolve under ``workspace_root``. Absolute paths must land
inside one of the explicit allowed roots.

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
import re
import shlex
import stat as stat_module
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, NamedTuple

from loguru import logger

from app.core.config import settings

# ── Module-level defaults (no env-var overrides) ──────────────────────────
DEFAULT_MAX_EXECUTION_SECONDS = 600
DEFAULT_MAX_OUTPUT_BYTES = 131072

# A single command rarely touches more paths than this; the rest is summarised
# so one ``find`` over many roots cannot flood the log.
_AUDIT_MAX_VIOLATIONS_LOGGED = 10

ViolationKind = Literal["denied_root", "denied_pattern", "outside", "read_only"]


class CommandViolation(NamedTuple):
    """One out-of-scope path operand found by :meth:`SandboxConfig.command_violations`."""

    resolved: Path
    kind: ViolationKind
    # The matched denied root / pattern or read-only root, or a fixed message
    # for ``outside``.
    detail: str

    @property
    def reason(self) -> str:
        """Human-readable reason for audit logs."""
        if self.kind == "denied_root":
            return f"denied root {self.detail}"
        if self.kind == "denied_pattern":
            return f"denied pattern {self.detail}"
        if self.kind == "read_only":
            return f"redirect into read-only root {self.detail}"
        return self.detail


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
    """Workspace-allowlisted sandbox for the agent's filesystem tools.

    All relative paths resolve under ``workspace_root``.
    Absolute paths must resolve inside an explicitly allowed root.
    """

    def __init__(
        self,
        workspace: str | None = None,
        session_id: str | None = None,
        denied_roots: list[Path] | None = None,
        denied_patterns: list[str] | None = None,
        max_execution_seconds: int | None = None,
        max_output_bytes: int | None = None,
        inherit_shell_environment: bool | None = None,
        load_shell_profile: bool | None = None,
        outbound_data_policy: Literal["block", "redact", "off"] | None = None,
        outbound_pii_policy: Literal["off", "standard", "strict"] | None = None,
        # Other repos in the same CodingProject, if this session is
        # project-scoped. Lets tools that call get_sandbox() (for example,
        # repository-aware tools, which may traverse every authorized repository)
        # see the full repo set without a model-facing "workspace_paths"
        # argument on every one of them.
        extra_workspace_paths: list[str] | None = None,
        # Paths that remain readable — they are NOT in denied_roots, so
        # read/search/grep tools still work — but are rejected by write-path
        # tools (write/edit/patch/rm). See validate_path's is_write param.
        read_only_paths: list[str] | None = None,
        # Optional member-task write lease. When non-empty, every direct
        # filesystem mutation must stay under one of these workspace-relative
        # or absolute paths.
        write_allowed_paths: list[str] | None = None,
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
        self.allowed_workspace_roots: list[Path] = [
            self.workspace_root,
            *(Path(p).resolve() for p in self.extra_workspace_paths),
        ]
        resolved_read_only = [Path(p).resolve() for p in (read_only_paths or [])]
        if session_id:
            from app.core.paths import session_uploads_dir

            upload_root = session_uploads_dir(session_id).resolve()
            if upload_root not in resolved_read_only:
                resolved_read_only.append(upload_root)
        self.read_only_paths: list[Path] = resolved_read_only
        self.write_allowed_paths: list[Path] = [
            (
                Path(path).resolve()
                if Path(path).is_absolute()
                else (self.workspace_root / path).resolve()
            )
            for path in (write_allowed_paths or [])
        ]
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        if denied_roots is None:
            denied_roots = [
                Path(settings.EVOFLUX_DATA_DIR).resolve(),
                Path(settings.EVOFLUX_STATE_DIR).resolve(),
                Path(settings.EVOFLUX_CACHE_DIR).resolve(),
            ]
        self.denied_roots: list[Path] = list(denied_roots)

        file_config = None
        # Passing an explicit deny-list is also the constructor's opt-out from
        # user-level policy loading (used by tests and isolated internal jobs).
        # Normal session sandboxes omit it and receive the complete saved policy.
        if denied_patterns is None:
            try:
                from app.agent.sandbox_config import load_config

                file_config = load_config()
            except (ValueError, OSError) as exc:
                logger.warning("sandbox_config_load_failed err={}", exc)
        if denied_patterns is None:
            denied_patterns = (
                list(file_config.denied_patterns) if file_config is not None else []
            )
        self.denied_patterns: list[str] = list(denied_patterns)

        self.max_execution_seconds: int = (
            max_execution_seconds
            if max_execution_seconds is not None
            else (
                file_config.max_execution_seconds
                if file_config is not None
                else DEFAULT_MAX_EXECUTION_SECONDS
            )
        )
        self.max_output_bytes: int = (
            max_output_bytes
            if max_output_bytes is not None
            else (
                file_config.max_output_bytes
                if file_config is not None
                else DEFAULT_MAX_OUTPUT_BYTES
            )
        )
        self.inherit_shell_environment: bool = (
            inherit_shell_environment
            if inherit_shell_environment is not None
            else (
                file_config.inherit_shell_environment
                if file_config is not None
                else False
            )
        )
        self.load_shell_profile: bool = (
            load_shell_profile
            if load_shell_profile is not None
            else (file_config.load_shell_profile if file_config is not None else False)
        )
        self.outbound_data_policy: Literal["block", "redact", "off"] = (
            outbound_data_policy
            if outbound_data_policy is not None
            else (
                getattr(file_config, "outbound_data_policy", "off")
                if file_config is not None
                else "off"
            )
        )
        self.outbound_pii_policy: Literal["off", "standard", "strict"] = (
            outbound_pii_policy
            if outbound_pii_policy is not None
            else (
                getattr(file_config, "outbound_pii_policy", "off")
                if file_config is not None
                else "off"
            )
        )

    def metadata_path(self, name: str) -> Path:
        """Return a path under ``.evoflux`` for this sandbox context."""
        from app.agent.artifacts import session_artifact_dir

        return session_artifact_dir(self.session_id) / name

    # ── Path validation ───────────────────────────────────────────────────

    def _is_denied(self, resolved: Path) -> Path | str | None:
        """Return the denied root or glob pattern that matched, or None."""
        root_exempt = [
            *self.allowed_workspace_roots,
            *self.read_only_paths,
            *_allowed_internal_roots(self.session_id),
        ]
        if not any(_path_is_under(resolved, root) for root in root_exempt):
            for denied in self.denied_roots:
                if _path_is_under(resolved, denied):
                    return denied
        # Glob patterns are authored with POSIX separators (``**/.env``).
        # Match against ``as_posix()`` so Windows ``\`` paths still hit.
        resolved_posix = resolved.as_posix()
        for pattern in self.denied_patterns:
            if fnmatch.fnmatchcase(resolved_posix, pattern):
                return pattern
        return None

    def _is_allowed(self, resolved: Path) -> bool:
        roots = [
            *self.allowed_workspace_roots,
            *self.read_only_paths,
            *_allowed_internal_roots(self.session_id),
        ]
        return any(_path_is_under(resolved, root) for root in roots)

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
                though it's readable — agents may read those roots but must
                never modify them, while ordinary read/search tools stay
                unaffected.

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

        if not self._is_allowed(resolved):
            logger.warning("sandbox_path_outside_allowlist path={}", resolved)
            raise PermissionError(
                f"Path '{resolved}' is outside the allowed sandbox roots. "
                "Add it as an explicit project/read-only root before access."
            )

        if is_write:
            if self.write_allowed_paths and not any(
                _path_is_under(resolved, root) for root in self.write_allowed_paths
            ):
                logger.warning(
                    "sandbox_write_outside_claim path={} claims={}",
                    resolved,
                    self.write_allowed_paths,
                )
                raise PermissionError(
                    f"Path '{resolved}' is outside this agent's active write claims: "
                    + ", ".join(str(path) for path in self.write_allowed_paths)
                )
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

    def command_violations(
        self, command: str, *, cwd: Path | None = None
    ) -> list[CommandViolation]:
        """Scan *command* for path operands outside the sandbox roots.

        Returns every distinct violation in command order: arguments inside
        denied roots or matching deny patterns, arguments outside the allowed
        roots, and — when ``read_only_paths`` is set — ``>``/``>>``
        redirection targets landing inside one of them. Relative operands
        resolve against *cwd* (default: the workspace root), following any
        ``cd``/``pushd`` earlier in the command.

        This reports; it does not gate. Command execution deliberately runs
        unrestricted (see :meth:`audit_command`), so the result is for
        logging, telemetry, and tests. Filesystem *tools* enforce their own
        scope separately, and OS permissions remain the last line of defence.
        """
        violations: list[CommandViolation] = []
        seen: set[Path] = set()
        base = cwd if cwd is not None else self.workspace_root
        for resolved, redirected in _command_operands(command, base):
            if resolved in seen:
                continue
            violation = self._classify_operand(resolved, redirected=redirected)
            if violation is not None:
                seen.add(resolved)
                violations.append(violation)
        return violations

    def check_command(
        self, command: str, *, cwd: Path | None = None
    ) -> tuple[Path, str] | None:
        """Return the first :meth:`command_violations` entry as
        ``(resolved_path, detail)``, or ``None`` when nothing is flagged.

        ``detail`` is the matched denied root or pattern, the read-only root,
        or ``"outside allowed sandbox roots"``.
        """
        violations = self.command_violations(command, cwd=cwd)
        if not violations:
            return None
        return violations[0].resolved, violations[0].detail

    def _classify_operand(
        self, resolved: Path, *, redirected: bool
    ) -> CommandViolation | None:
        denied = self._is_denied(resolved)
        if denied is not None:
            kind = "denied_root" if isinstance(denied, Path) else "denied_pattern"
            return CommandViolation(resolved, kind, str(denied))
        if not self._is_allowed(resolved):
            return CommandViolation(
                resolved, "outside", "outside allowed sandbox roots"
            )
        if redirected and self.read_only_paths:
            read_only_root = self._is_read_only(resolved)
            if read_only_root is not None:
                return CommandViolation(resolved, "read_only", str(read_only_root))
        return None

    def audit_command(
        self, command: str, *, tool: str, cwd: Path | None = None
    ) -> None:
        """Log any sandbox violation in *command* without blocking it.

        Command execution is unrestricted by product decision: an agent's
        shell has to run ordinary developer commands that legitimately reach
        outside the workspace — ``ssh-keyscan >> ~/.ssh/known_hosts``, reading
        ``~/.gitconfig``, invoking a credential helper — and a path scanner
        cannot tell those apart from misuse without breaking normal work.

        What remains is observability: every command that touches a denied or
        out-of-scope path is recorded, so the behaviour is reviewable after
        the fact even though nothing is prevented. Callers must not treat a
        return from this method as permission having been granted; it never
        withholds it.
        """
        violations = self.command_violations(command, cwd=cwd)
        for violation in violations[:_AUDIT_MAX_VIOLATIONS_LOGGED]:
            logger.warning(
                "sandbox_command_audit tool={} resolved={} reason={} (not blocked)",
                tool,
                violation.resolved,
                violation.reason,
            )
        if len(violations) > _AUDIT_MAX_VIOLATIONS_LOGGED:
            logger.warning(
                "sandbox_command_audit tool={} more_violations={} (not blocked)",
                tool,
                len(violations) - _AUDIT_MAX_VIOLATIONS_LOGGED,
            )

    # ── Display helpers ──────────────────────────────────────────────────

    def display_path(self, resolved: Path) -> str:
        """Return a display path for ``resolved``."""
        if _path_is_under(resolved, self.workspace_root):
            rel = resolved.relative_to(self.workspace_root)
            return str(self.workspace_root) if str(rel) == "." else rel.as_posix()
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


# ── Command scanning ────────────────────────────────────────────────────
#
# A best-effort, POSIX-shell-shaped reading of agent commands for
# ``audit_command``. It never gates execution, so the goal is a log that is
# right about what a command touches: few false alarms, and no blind spot for
# the obvious ways agents reach files (``cd`` then relative paths, Git Bash
# ``/c/...`` drive paths, interpreter one-liners that open a path literal).

_IS_WINDOWS = sys.platform == "win32"

# Operators split simple commands; newline is one too (outside quotes).
_SHELL_PUNCTUATION = "();<>|&\n"
# A backslash run followed by a path character is a Windows separator; any
# other backslash is a shell escape (``\(``, ``\;``, ``\*``) and must survive.
_WINDOWS_SEPARATOR_RE = re.compile(r"\\+(?=[\w.~%-])")
# ...except a glob right after a path component: ``C:\dir\*.md``. At the start
# of a word (``find -name \*.py``) the backslash is still an escape.
_WINDOWS_GLOB_SEPARATOR_RE = re.compile(r"(?<=[\w.~%-])\\+(?=[*?])")
# Characters that make a word an expression (sed/awk programs, regexes,
# command substitution) rather than a path.
_NON_PATH_CHARS = frozenset("$<>|`")
_LINE_CONTINUATION_RE = re.compile(r"\\\r?\n")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
# Git Bash/MSYS drive mounts: ``/c/Users`` is ``C:/Users``.
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])(?=/|$)")
# cmd.exe-style switches (``/s``, ``/b``, ``/AD``, ``/O:N``) are not paths.
_WINDOWS_SWITCH_RE = re.compile(r"^/[A-Za-z?]{1,2}(?::\S*)?$")
_DEVICE_PATHS = frozenset(
    {"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/tty", "nul"}
)
# ``<<EOF`` / ``<<-'EOF'`` / ``<<"EOF"`` — not the ``<<<`` here-string.
_HEREDOC_RE = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# A quoted absolute path literal inside an interpreter script, optionally as a
# ``file:`` URI (``sqlite3.connect('file:C:/…/app.db?mode=ro')``).
_SCRIPT_PATH_LITERAL_RE = re.compile(
    r"""(['"])(?:file:(?://)?)?((?:[A-Za-z]:[\\/]|~[\\/]|/)[^'"\n?*<>|]*)"""
)
_INTERPRETER_RE = re.compile(
    r"^(python[0-9.]*|py|node|deno|bun|ruby|perl|php|pwsh|powershell)$"
)
_SHELL_RE = re.compile(r"^(bash|sh|zsh|dash|ksh)$")
_SCRIPT_FLAGS = frozenset({"-c", "-e", "--eval", "-command"})
_CD_COMMANDS = frozenset({"cd", "pushd"})
_MAX_SCRIPT_DEPTH = 2


def _to_slashes(match: re.Match[str]) -> str:
    return "/" * len(match.group())


def _shell_tokens(command: str) -> list[str]:
    """Split *command* into shell words and operator tokens.

    Operators (``;``, ``&&``, ``|``, ``>``, newline, …) come back as their own
    tokens so callers can find command boundaries and redirect targets.
    Raises ``ValueError`` on unbalanced quotes.
    """
    command = _LINE_CONTINUATION_RE.sub(" ", command)
    if _IS_WINDOWS:
        # POSIX-mode shlex treats ``\`` as an escape and would mangle
        # ``C:\Users\...`` into ``C:Users...``.
        command = _WINDOWS_GLOB_SEPARATOR_RE.sub(_to_slashes, command)
        command = _WINDOWS_SEPARATOR_RE.sub(_to_slashes, command)
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_SHELL_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    return list(lexer)


def _is_operator(token: str) -> bool:
    return bool(token) and all(ch in _SHELL_PUNCTUATION for ch in token)


def _is_redirect(token: str) -> bool:
    return set(token) <= set("<>&") and ("<" in token or ">" in token)


def _program_name(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.removesuffix(".exe")


def _simple_commands(tokens: list[str]) -> Iterator[list[tuple[str, bool]]]:
    """Group *tokens* into simple commands of ``(word, written_to)`` pairs.

    ``written_to`` marks the target of a ``>``/``>>`` redirection.
    """
    words: list[tuple[str, bool]] = []
    written_to = False
    for token in tokens:
        if _is_operator(token):
            if _is_redirect(token):
                written_to = ">" in token
                continue
            if words:
                yield words
            words = []
            written_to = False
            continue
        words.append((token, written_to))
        written_to = False
    if words:
        yield words


def _extract_heredocs(command: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove here-document bodies from *command*.

    Returns the remaining command plus ``(text_before_operator, body)`` for
    each here-document. Bodies are data for the receiving program, not shell
    words, so they must not be tokenised as arguments.
    """
    lines = command.split("\n")
    kept: list[str] = []
    bodies: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for match in _HEREDOC_RE.finditer(line):
            strip_tabs = match.group(1) == "-"
            delimiter = match.group(3)
            body: list[str] = []
            while index < len(lines):
                candidate = lines[index].rstrip("\r")
                index += 1
                if (candidate.lstrip("\t") if strip_tabs else candidate) == delimiter:
                    break
                body.append(candidate)
            bodies.append((line[: match.start()], "\n".join(body)))
    return "\n".join(kept), bodies


def _command_program(prefix: str) -> str | None:
    """Return the program of the last simple command in *prefix*."""
    try:
        tokens = _shell_tokens(prefix)
    except ValueError:
        return None
    last: list[tuple[str, bool]] | None = None
    for words in _simple_commands(tokens):
        last = words
    if not last:
        return None
    for word, _ in last:
        if not _ASSIGNMENT_RE.match(word):
            return _program_name(word)
    return None


def _normalize_operand(token: str) -> str | None:
    """Map a shell word to a filesystem path string, or None if it is not one."""
    if not _looks_path_like(token):
        return None
    if token.lower() in _DEVICE_PATHS or token.startswith("/dev/fd/"):
        return None
    if _IS_WINDOWS:
        if _WINDOWS_SWITCH_RE.match(token):
            return None
        drive = _MSYS_DRIVE_RE.match(token)
        if drive:
            rest = token[drive.end() :]
            return f"{drive.group(1).upper()}:{rest or '/'}"
        if token == "/tmp" or token.startswith("/tmp/"):
            return tempfile.gettempdir() + token[len("/tmp") :]
    return token


def _resolve_operand(path: str, cwd: Path) -> Path | None:
    candidate = Path(os.path.expanduser(path))
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        return candidate.resolve()
    except OSError:
        return None


def _script_path_literals(script: str, cwd: Path) -> Iterator[Path]:
    """Yield existing absolute paths quoted inside an interpreter script.

    Only quoted absolute literals are considered, and only when they exist:
    scripts are full of strings that merely look like paths (URL paths,
    ``"/api/…"`` routes), whereas a real file the script opens exists.
    """
    for match in _SCRIPT_PATH_LITERAL_RE.finditer(script):
        raw = match.group(2).rstrip()
        if _IS_WINDOWS:
            raw = re.sub(r"\\+", "/", raw)
        candidate = Path(os.path.expanduser(raw))
        if not candidate.is_absolute():
            continue
        resolved = _resolve_operand(str(candidate), cwd)
        if resolved is not None and resolved.exists():
            yield resolved


def _command_operands(
    command: str, cwd: Path, *, depth: int = 0
) -> Iterator[tuple[Path, bool]]:
    """Yield ``(resolved_path, written_to)`` for each path *command* touches."""
    command, heredocs = _extract_heredocs(command)
    try:
        tokens = _shell_tokens(command)
    except ValueError:
        # Malformed quoting: the shell will reject it too.
        return

    for words in _simple_commands(tokens):
        # Leading ``VAR=value`` words are environment assignments.
        start = 0
        while start < len(words) and _ASSIGNMENT_RE.match(words[start][0]):
            start += 1
        if start == len(words):
            continue
        # The first word is the executable, not a workspace operand.
        program = _program_name(words[start][0])
        operands = words[start + 1 :]
        takes_script = bool(_INTERPRETER_RE.match(program) or _SHELL_RE.match(program))
        index = 0
        while index < len(operands):
            word, written_to = operands[index]
            index += 1
            if takes_script and word.lower() in _SCRIPT_FLAGS and index < len(operands):
                script = operands[index][0]
                index += 1
                if _SHELL_RE.match(program):
                    if depth < _MAX_SCRIPT_DEPTH:
                        yield from _command_operands(script, cwd, depth=depth + 1)
                else:
                    for path in _script_path_literals(script, cwd):
                        yield path, False
                continue
            normalized = _normalize_operand(word)
            if normalized is None:
                continue
            resolved = _resolve_operand(normalized, cwd)
            if resolved is None:
                continue
            yield resolved, written_to
            if program in _CD_COMMANDS:
                # Later relative operands resolve from the new directory.
                cwd = resolved
                break

    for prefix, body in heredocs:
        program = _command_program(prefix)
        if program is None:
            continue
        if _SHELL_RE.match(program):
            if depth < _MAX_SCRIPT_DEPTH:
                yield from _command_operands(body, cwd, depth=depth + 1)
        elif _INTERPRETER_RE.match(program):
            for path in _script_path_literals(body, cwd):
                yield path, False


def _looks_path_like(token: str) -> bool:
    if not token:
        return False
    if token.startswith("-"):
        return False
    if _URL_RE.match(token):
        return False
    if not _NON_PATH_CHARS.isdisjoint(token):
        return False
    if "/" in token or "\\" in token:
        return True
    # Windows drive path (``C:foo`` after separator normalization, or ``C:``).
    if len(token) >= 2 and token[0].isalpha() and token[1] == ":":
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
        _default_sandbox_instance = SandboxConfig(
            workspace=str(Path(tempfile.gettempdir()) / "EvoFlux-default-sandbox"),
        )
    return _default_sandbox_instance
