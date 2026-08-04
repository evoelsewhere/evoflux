"""Machine-verifiable completion contracts for coding turns."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.process_sandbox import sandboxed_process_argv
from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.shell import _scrubbed_env
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

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class CompletionContract:
    """Verification result bound to one exact changed-file snapshot."""

    artifact_hash: str
    changed_files: tuple[str, ...]
    evidence: tuple[VerificationEvidence, ...]
    rigor: str = "standard"

    @property
    def passed(self) -> bool:
        return bool(self.evidence) and all(item.passed for item in self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_hash": self.artifact_hash,
            "changed_files": list(self.changed_files),
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
        raw_paths = state.metadata.get("_verification_changed_files") or set()
        if not raw_paths:
            return None

        sandbox = get_sandbox()
        changed_files = tuple(sorted(str(path) for path in raw_paths))
        artifact_hash = _artifact_hash(sandbox.workspace_root, changed_files)
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
        )
        contract = CompletionContract(
            artifact_hash=artifact_hash,
            changed_files=changed_files,
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


def _artifact_hash(workspace: Path, changed_files: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
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
) -> list[VerificationEvidence]:
    paths = [Path(path) for path in changed_files]
    commands: list[tuple[list[str], Path]] = []

    git = shutil.which("git")
    if git and (workspace / ".git").exists():
        commands.append(([git, "diff", "--check", "--", *changed_files], workspace))

    python_files = [path for path in paths if path.suffix in {".py", ".pyi"}]
    ruff = shutil.which("ruff")
    if python_files and ruff:
        commands.append(([ruff, "check", *map(str, python_files)], workspace))
    ty = shutil.which("ty")
    if rigor == "strict" and python_files and ty:
        commands.append(([ty, "check", *map(str, python_files)], workspace))
    changed_tests = [
        str(path)
        for path in python_files
        if "tests" in path.parts and path.name.startswith("test_")
    ]
    pytest = shutil.which("pytest")
    if changed_tests and pytest:
        commands.append(([pytest, "--no-cov", "-q", *changed_tests], workspace))

    if any(path.suffix in {".ts", ".tsx", ".js", ".jsx"} for path in paths):
        bun = shutil.which("bun")
        web_root = workspace / "web"
        if bun and (web_root / "package.json").exists():
            commands.append(([bun, "run", "typecheck"], web_root))
            if rigor == "strict":
                commands.append(([bun, "run", "lint"], web_root))

    if any(path.suffix == ".rs" for path in paths):
        cargo = shutil.which("cargo")
        rust_root = workspace / "desktop" / "src-tauri"
        if cargo and (rust_root / "Cargo.toml").exists():
            commands.append(([cargo, "check"], rust_root))
            if rigor == "strict":
                commands.append(([cargo, "clippy", "--", "-D", "warnings"], rust_root))

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

    revision = await _git_revision(workspace)
    return [
        await _run_command(command, cwd, revision, artifact_hash)
        for command, cwd in commands
    ]


async def _run_command(
    command: list[str],
    cwd: Path,
    revision: str | None,
    artifact_hash: str,
) -> VerificationEvidence:
    command_id = str(uuid.uuid4())
    try:
        sandbox = get_sandbox()
        exec_bin, exec_argv = sandboxed_process_argv(
            command[0],
            command[1:],
            sandbox=sandbox,
            cwd=cwd,
        )
        proc = await asyncio.create_subprocess_exec(
            exec_bin,
            *exec_argv,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
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
    )


async def _git_revision(workspace: Path) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        sandbox = get_sandbox()
        exec_bin, exec_argv = sandboxed_process_argv(
            git,
            ["-C", str(workspace), "rev-parse", "HEAD"],
            sandbox=sandbox,
            cwd=workspace,
        )
        proc = await asyncio.create_subprocess_exec(
            exec_bin,
            *exec_argv,
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
