"""Machine-verifiable completion contracts for coding turns."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.shell import _scrubbed_env
from app.services.trace_contracts import parse_verification_command
from app.services.turn_changes import _parse_patch_ops


@dataclass(frozen=True)
class VerificationEvidence:
    """Evidence produced by a real process invocation."""

    command_id: str
    command: list[str]
    cwd: str
    exit_code: int
    revision: str | None
    artifact_hash: str
    output: str
    source: str = "automatic"
    spec_command: str | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class CompletionContract:
    """Verification result bound to one exact changed-file snapshot."""

    artifact_hash: str
    changed_files: tuple[str, ...]
    scope_paths: tuple[str, ...]
    scope_targets: tuple[dict[str, str | None], ...]
    evidence: tuple[VerificationEvidence, ...]
    rigor: str = "standard"

    @property
    def passed(self) -> bool:
        return bool(self.evidence) and all(item.passed for item in self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_hash": self.artifact_hash,
            "changed_files": list(self.changed_files),
            "scope_paths": list(self.scope_paths),
            "scope_targets": list(self.scope_targets),
            "passed": self.passed,
            "rigor": self.rigor,
            "evidence": [
                asdict(item) | {"passed": item.passed} for item in self.evidence
            ],
        }


class CompletionVerificationHook(BaseAgentHook):
    """Require targeted deterministic checks after successful file mutations."""

    async def before_agent(self, ctx, state) -> None:
        state.metadata.setdefault("_verification_changed_files", set())
        if "_easd_run_id" in state.metadata:
            state.metadata["_verification_git_baseline"] = await _git_baseline(
                get_sandbox()
            )

    async def wrap_tool_call(self, ctx, state, tool_call, handler) -> str:
        if tool_call.function.name == "team_handoff":
            try:
                handoff_args = json.loads(tool_call.function.arguments or "{}")
            except (TypeError, ValueError):
                handoff_args = {}
            if handoff_args.get("status", "final") == "final":
                failure = await self._evaluate(ctx, state)
                if failure:
                    return "HANDOFF BLOCKED — machine verification failed:\n" + failure

        result = await handler(ctx, state, tool_call)
        if not isinstance(result, str) or _tool_failed(result):
            return result

        name = tool_call.function.name
        if name not in {"edit", "write", "patch", "rm"}:
            return result
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except (TypeError, ValueError):
            return result

        paths = _changed_paths(name, args)
        if paths:
            changed: set[str] = state.metadata.setdefault(
                "_verification_changed_files", set()
            )
            changed.update(paths)
            state.metadata.pop("completion_contract", None)
        return result

    async def before_completion(self, ctx, state, response) -> str | None:
        return await self._evaluate(ctx, state)

    async def _evaluate(self, ctx, state) -> str | None:
        raw_paths = set(state.metadata.get("_verification_changed_files") or set())
        baseline = state.metadata.get("_verification_git_baseline")
        if isinstance(baseline, dict):
            raw_paths.update(await _git_changes_since(get_sandbox(), baseline))
        planned_commands = tuple(
            str(command)
            for command in state.metadata.get("_easd_verification_commands", [])
            if isinstance(command, str) and command.strip()
        )
        # The final EASD Verify phase is intentionally read-only. It still needs
        # a machine CompletionContract bound to the current repository revision,
        # even when this verifier did not mutate a file in its own turn.
        verify_only = state.metadata.get("_easd_phase") == "verifying" and bool(
            planned_commands
        )
        if not raw_paths and not verify_only:
            return None
        context_error = state.metadata.get("_easd_context_error")
        if context_error:
            return (
                "EASD contract unavailable: workspace changes cannot be verified "
                f"against the accepted Scope ({context_error}). Retry after the "
                "local contract store is available."
            )

        sandbox = get_sandbox()
        changed_files = tuple(sorted(str(path) for path in raw_paths))
        scope_paths, scope_targets = _scope_changes(
            sandbox,
            changed_files,
            state.metadata.get("_easd_repository_roots"),
        )
        impact_targets = state.metadata.get("_easd_impact_targets")
        outside = (
            _outside_impact_targets(scope_targets, impact_targets)
            if "_easd_impact_targets" in state.metadata
            else []
        )
        if outside:
            return (
                "EASD scope violation: changed paths are outside the accepted "
                "Impact targets: "
                + ", ".join(outside)
                + ". Record a deviation and ask the user to accept a revised "
                "specification before completing."
            )
        repository_revision = await _git_revision(sandbox.workspace_root)
        artifact_hash = _artifact_hash(
            sandbox.workspace_root,
            changed_files,
            repository_revision=repository_revision,
            planned_commands=planned_commands,
        )
        rigor = str(state.metadata.get("verification_rigor") or "standard")
        cached = state.metadata.get("completion_contract")
        if (
            isinstance(cached, dict)
            and cached.get("artifact_hash") == artifact_hash
            and cached.get("rigor") == rigor
        ):
            if cached.get("passed") is True:
                return None
            return _failure_feedback(cached)

        evidence = await _run_required_checks(
            sandbox.workspace_root,
            changed_files,
            artifact_hash,
            rigor,
            planned_commands,
        )
        contract = CompletionContract(
            artifact_hash=artifact_hash,
            changed_files=changed_files,
            scope_paths=scope_paths,
            scope_targets=scope_targets,
            evidence=tuple(evidence),
            rigor=rigor,
        )
        payload = contract.to_dict()
        state.metadata["completion_contract"] = payload
        logger.info(
            "completion_contract_evaluated session={} files={} checks={} passed={}",
            ctx.session_id,
            len(changed_files),
            len(evidence),
            contract.passed,
        )
        return None if contract.passed else _failure_feedback(payload)


def _tool_failed(result: str) -> bool:
    lowered = result.lstrip().lower()
    return lowered.startswith(("error", "[error", "[plan", "[blocked"))


def _changed_paths(tool_name: str, args: dict[str, Any]) -> set[str]:
    if tool_name == "patch":
        patch_text = args.get("patch_text")
        if not isinstance(patch_text, str):
            return set()
        return {path for path, _status, _add, _delete in _parse_patch_ops(patch_text)}
    raw = args.get("path") or args.get("file_path") or args.get("target")
    return {raw} if isinstance(raw, str) and raw.strip() else set()


def _artifact_hash(
    workspace: Path,
    changed_files: tuple[str, ...],
    *,
    repository_revision: str | None = None,
    planned_commands: tuple[str, ...] = (),
) -> str:
    digest = hashlib.sha256()
    # Verification depends on the whole repository/configuration baseline, not
    # only the files edited through model-facing tools. A rebase/cherry-pick can
    # change pytest, type-checker, or build behavior without touching the
    # mission's tracked paths, so it must invalidate a cached contract.
    digest.update((repository_revision or "<no-git-revision>").encode("utf-8"))
    for command in planned_commands:
        digest.update(b"\x00planned\x00")
        digest.update(command.encode("utf-8"))
    for raw in changed_files:
        digest.update(raw.encode("utf-8"))
        path = Path(raw)
        resolved = path if path.is_absolute() else workspace / path
        try:
            digest.update(resolved.read_bytes())
        except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
            digest.update(b"<missing>")
    return digest.hexdigest()


async def _run_required_checks(
    workspace: Path,
    changed_files: tuple[str, ...],
    artifact_hash: str,
    rigor: str = "standard",
    planned_commands: tuple[str, ...] = (),
) -> list[VerificationEvidence]:
    commands: list[tuple[list[str], Path, str, str | None]] = []
    for repository, paths in _changed_files_by_repository(
        workspace, changed_files
    ).items():
        path_strings = [path.as_posix() for path in paths]
        git = shutil.which("git")
        if git and (repository / ".git").exists():
            commands.append(
                (
                    [git, "diff", "--check", "--", *path_strings],
                    repository,
                    "automatic",
                    None,
                )
            )

        python_files = [path for path in paths if path.suffix in {".py", ".pyi"}]
        ruff = shutil.which("ruff")
        if python_files and ruff:
            commands.append(
                (
                    [ruff, "check", *map(str, python_files)],
                    repository,
                    "automatic",
                    None,
                )
            )
        ty = shutil.which("ty")
        if rigor == "strict" and python_files and ty:
            commands.append(
                ([ty, "check", *map(str, python_files)], repository, "automatic", None)
            )
        changed_tests = [
            str(path)
            for path in python_files
            if "tests" in path.parts and path.name.startswith("test_")
        ]
        pytest = _pytest_command_prefix()
        if changed_tests and pytest:
            commands.append(
                (
                    [*pytest, "--no-cov", "-q", *changed_tests],
                    repository,
                    "automatic",
                    None,
                )
            )

        if any(path.suffix in {".ts", ".tsx", ".js", ".jsx"} for path in paths):
            bun = shutil.which("bun")
            web_root = (
                repository
                if (repository / "package.json").exists()
                else repository / "web"
            )
            if bun and (web_root / "package.json").exists():
                commands.append(
                    ([bun, "run", "typecheck"], web_root, "automatic", None)
                )
                if rigor == "strict":
                    commands.append(([bun, "run", "lint"], web_root, "automatic", None))

        if any(path.suffix == ".rs" for path in paths):
            cargo = shutil.which("cargo")
            rust_root = (
                repository
                if (repository / "Cargo.toml").exists()
                else repository / "desktop" / "src-tauri"
            )
            if cargo and (rust_root / "Cargo.toml").exists():
                commands.append(([cargo, "check"], rust_root, "automatic", None))
                if rigor == "strict":
                    commands.append(
                        (
                            [cargo, "clippy", "--", "-D", "warnings"],
                            rust_root,
                            "automatic",
                            None,
                        )
                    )

    for command in planned_commands:
        commands.append(
            (
                _resolve_verification_argv(command, workspace),
                workspace,
                "planned",
                command,
            )
        )

    unique_commands: list[tuple[list[str], Path, str, str | None]] = []
    seen: set[tuple[tuple[str, ...], str]] = set()
    for command, cwd, source, spec_command in commands:
        key = (tuple(command), str(cwd))
        if key in seen:
            continue
        seen.add(key)
        unique_commands.append((command, cwd, source, spec_command))
    commands = unique_commands

    if not commands:
        # A changed-file contract without an executable check is not evidence.
        return [
            VerificationEvidence(
                command_id=str(uuid.uuid4()),
                command=[],
                cwd=str(workspace),
                exit_code=127,
                revision=await _git_revision(workspace),
                artifact_hash=artifact_hash,
                output="No deterministic verification command is available.",
            )
        ]

    evidence: list[VerificationEvidence] = []
    revisions: dict[Path, str | None] = {}
    for command, cwd, source, spec_command in commands:
        if cwd not in revisions:
            revisions[cwd] = await _git_revision(cwd)
        evidence.append(
            await _run_command(
                command,
                cwd,
                revisions[cwd],
                artifact_hash,
                source=source,
                spec_command=spec_command,
            )
        )
    return evidence


def _changed_files_by_repository(
    workspace: Path, changed_files: tuple[str, ...]
) -> dict[Path, list[Path]]:
    sandbox = get_sandbox()
    roots = [Path(path).resolve() for path in sandbox.allowed_workspace_roots]
    primary = workspace.resolve()
    grouped: dict[Path, list[Path]] = {}
    for raw in changed_files:
        path = Path(raw)
        repository = primary
        relative = path
        if path.is_absolute():
            resolved = path.resolve(strict=False)
            matches = [
                root for root in roots if resolved == root or root in resolved.parents
            ]
            if matches:
                repository = max(matches, key=lambda item: len(item.parts))
                relative = resolved.relative_to(repository)
        grouped.setdefault(repository, []).append(relative)
    return grouped


def _resolve_verification_argv(command: str, workspace: Path) -> list[str]:
    parts = parse_verification_command(command)
    program = parts[0]
    if program in {"python", "python3"}:
        parts[0] = sys.executable
    elif program in {"./gradlew", "./mvnw"}:
        parts[0] = str((workspace / program[2:]).resolve())
    else:
        parts[0] = shutil.which(program) or program
    return parts


def _scope_changes(
    sandbox,
    changed_files: tuple[str, ...],
    repository_roots: object,
) -> tuple[tuple[str, ...], tuple[dict[str, str | None], ...]]:
    normalized: list[str] = []
    roots = [Path(path).resolve() for path in sandbox.allowed_workspace_roots]
    configured: list[dict[str, object]] = []
    if isinstance(repository_roots, list):
        configured = [
            cast(dict[str, object], item)
            for item in cast(list[object], repository_roots)
            if isinstance(item, dict)
        ]
    targets: list[dict[str, str | None]] = []

    def repository_for(index: int, root: Path) -> str | None:
        for item in configured:
            source = item.get("path")
            repository = item.get("repository")
            if not isinstance(source, str) or not isinstance(repository, str):
                continue
            source_path = Path(source).resolve()
            if root == source_path or source_path in root.parents:
                return repository
        if index < len(configured):
            repository = configured[index].get("repository")
            return repository if isinstance(repository, str) else None
        return None

    for raw in changed_files:
        path = Path(raw)
        repository: str | None = None
        if path.is_absolute():
            resolved = path.resolve(strict=False)
            relative = None
            for index, root in enumerate(roots):
                if resolved == root or root in resolved.parents:
                    relative = resolved.relative_to(root).as_posix()
                    repository = repository_for(index, root)
                    break
            normalized_path = relative or f"<outside>:{resolved}"
        else:
            relative = path.as_posix()
            normalized_path = relative[2:] if relative.startswith("./") else relative
            if roots:
                repository = repository_for(0, roots[0])
        normalized.append(normalized_path)
        targets.append({"repository": repository, "path": normalized_path})
    unique_targets = {(item["repository"], item["path"]): item for item in targets}
    return (
        tuple(sorted(dict.fromkeys(normalized))),
        tuple(
            unique_targets[key]
            for key in sorted(
                unique_targets,
                key=lambda item: (item[0] or "", item[1]),
            )
        ),
    )


async def _git_baseline(sandbox) -> dict[str, dict[str, Any]]:
    roots = [Path(path).resolve() for path in sandbox.allowed_workspace_roots]
    snapshots = await asyncio.gather(*(_git_snapshot(root) for root in roots))
    return {
        str(root): snapshot
        for root, snapshot in zip(roots, snapshots, strict=True)
        if snapshot is not None
    }


async def _git_changes_since(sandbox, baseline: dict[object, object]) -> set[str]:
    primary = sandbox.workspace_root.resolve()
    changed: set[str] = set()
    for root_raw, previous_raw in baseline.items():
        if not isinstance(root_raw, str) or not isinstance(previous_raw, dict):
            continue
        root = Path(root_raw).resolve()
        previous = cast(dict[str, Any], previous_raw)
        current = await _git_snapshot(root)
        if current is None:
            continue
        previous_files = previous.get("files")
        current_files = current.get("files")
        before = (
            cast(dict[str, str], previous_files)
            if isinstance(previous_files, dict)
            else {}
        )
        after = (
            cast(dict[str, str], current_files)
            if isinstance(current_files, dict)
            else {}
        )
        relative_paths = {
            path
            for path, fingerprint in after.items()
            if before.get(path) != fingerprint
        }
        old_revision = previous.get("revision")
        new_revision = current.get("revision")
        if (
            isinstance(old_revision, str)
            and isinstance(new_revision, str)
            and old_revision != new_revision
        ):
            committed = await _git_output(
                root, "diff", "--name-only", "-z", f"{old_revision}..{new_revision}"
            )
            if committed is not None:
                relative_paths.update(_nul_paths(committed))
        for relative in relative_paths:
            changed.add(
                relative if root == primary else str((root / relative).resolve())
            )
    return changed


async def _git_snapshot(root: Path) -> dict[str, Any] | None:
    if not (root / ".git").exists():
        return None
    revision_raw, unstaged, staged, untracked = await asyncio.gather(
        _git_output(root, "rev-parse", "HEAD"),
        _git_output(root, "diff", "--name-only", "-z"),
        _git_output(root, "diff", "--cached", "--name-only", "-z"),
        _git_output(root, "ls-files", "--others", "--exclude-standard", "-z"),
    )
    if revision_raw is None:
        return None
    paths: set[str] = set()
    for output in (unstaged, staged, untracked):
        if output is not None:
            paths.update(_nul_paths(output))
    files = {
        relative: await asyncio.to_thread(_file_fingerprint, root / relative)
        for relative in paths
    }
    return {
        "revision": revision_raw.decode("utf-8", errors="replace").strip(),
        "files": files,
    }


async def _git_output(root: Path, *args: str) -> bytes | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        sandbox = get_sandbox()
        proc = await asyncio.create_subprocess_exec(
            git,
            "-C",
            str(root),
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return stdout if proc.returncode == 0 else None
    except (OSError, TimeoutError):
        return None


def _nul_paths(output: bytes) -> set[str]:
    return {
        item.decode("utf-8", errors="replace") for item in output.split(b"\x00") if item
    }


def _file_fingerprint(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "<missing>"
    except (IsADirectoryError, PermissionError, OSError) as exc:
        return f"<unreadable:{type(exc).__name__}>"


def _outside_impact_targets(
    changed_files: tuple[dict[str, str | None], ...], impact_targets: object
) -> list[str]:
    if not changed_files or not isinstance(impact_targets, list):
        return []
    accepted: list[tuple[str | None, str]] = []
    for raw in cast(list[object], impact_targets):
        if not isinstance(raw, dict):
            continue
        item = cast(dict[str, object], raw)
        path = item.get("path")
        repository = item.get("repository")
        if isinstance(path, str):
            accepted.append(
                (
                    repository if isinstance(repository, str) else None,
                    Path(path).as_posix().strip("/"),
                )
            )
    if not accepted:
        return [
            f"{item['repository']}:{item['path']}"
            if item["repository"]
            else str(item["path"])
            for item in changed_files
        ]
    outside: list[str] = []
    for changed in changed_files:
        path = changed["path"] or ""
        repository = changed["repository"]
        if path.startswith("<outside>:") or not any(
            (repository is None or accepted_repository == repository)
            and (path == target or path.startswith(f"{target}/"))
            for accepted_repository, target in accepted
        ):
            outside.append(f"{repository}:{path}" if repository else path)
    return outside


def _pytest_command_prefix() -> list[str]:
    """Prefer ``python -m pytest`` so the verified workspace stays importable."""

    if importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest"]
    executable = shutil.which("pytest")
    return [executable] if executable else []


async def _run_command(
    command: list[str],
    cwd: Path,
    revision: str | None,
    artifact_hash: str,
    *,
    source: str = "automatic",
    spec_command: str | None = None,
) -> VerificationEvidence:
    command_id = str(uuid.uuid4())
    try:
        sandbox = get_sandbox()
        proc = await asyncio.create_subprocess_exec(
            command[0],
            *command[1:],
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()
            raise
        output = stdout.decode("utf-8", errors="replace")[-8000:]
        exit_code = proc.returncode or 0
    except TimeoutError:
        output = "Verification timed out after 180 seconds."
        exit_code = 124
    except OSError as exc:
        output = str(exc)
        exit_code = 127
    return VerificationEvidence(
        command_id=command_id,
        command=command,
        cwd=str(cwd),
        exit_code=exit_code,
        revision=revision,
        artifact_hash=artifact_hash,
        output=output,
        source=source,
        spec_command=spec_command,
    )


async def _git_revision(workspace: Path) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        sandbox = get_sandbox()
        proc = await asyncio.create_subprocess_exec(
            git,
            "-C",
            str(workspace),
            "rev-parse",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return stdout.decode().strip() if proc.returncode == 0 else None
    except (OSError, TimeoutError):
        return None


def _failure_feedback(contract: dict[str, Any]) -> str:
    failures = [
        item
        for item in contract.get("evidence", [])
        if isinstance(item, dict) and item.get("passed") is not True
    ]
    details = []
    for item in failures:
        command = " ".join(item.get("command") or []) or "(no command)"
        output = str(item.get("output") or "").strip()
        details.append(
            f"- `{command}` exited {item.get('exit_code')}: "
            f"{output[-1200:] or '(no output)'}"
        )
    return (
        "Mandatory verification failed for the current changed-file snapshot "
        f"{contract.get('artifact_hash')}:\n" + "\n".join(details)
    )
