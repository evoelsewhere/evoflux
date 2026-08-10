"""External runtime plumbing shared by the Office document pipelines.

The pipelines share source hashing and executable discovery. PPTX template and
XLSX authoring additionally drive Node workers over JSON request files and use
``@oai/artifact-tool``. Keeping that plumbing here prevents their dependency
lookup rules from drifting apart.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Final

ARTIFACT_TOOL_ENTRYPOINT_ENV: Final = "EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT"
NODE_BIN_ENV: Final = "EVOFLUX_NODE_BIN"

DEFAULT_WORKER_TIMEOUT_SECONDS: Final = 300

_HASH_CHUNK_BYTES: Final = 1024 * 1024
_ARTIFACT_TOOL_PACKAGE: Final = ("node_modules", "@oai", "artifact-tool")


def file_sha256(path: Path) -> str:
    """Hash *path* in bounded chunks so large Office packages stay streamable."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_root() -> Path:
    """Return the EvoFlux checkout root.

    Anchored on this file at ``app/services/office/runtime.py``; update the
    index if the module moves.
    """
    return Path(__file__).resolve().parents[3]


def codex_runtime_dependencies() -> Path:
    """Return the Codex primary-runtime dependency root.

    EvoFlux does not own this layout, so callers must treat it as a last-resort
    fallback behind the environment overrides and the repository's own
    ``node_modules``. Resolved per call so tests can relocate ``HOME``.
    """
    return (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
    )


def resolve_executable(
    env_var: str,
    names: tuple[str, ...],
    *,
    fallback_dirs: tuple[Path, ...] = (),
    requirement: str,
) -> str:
    """Locate an external executable, preferring an explicit env override.

    Args:
        env_var: Environment variable holding an explicit absolute path.
        names: Candidate executable names to look up on ``PATH``, in order.
        fallback_dirs: Directories searched only after ``PATH`` misses.
        requirement: Message raised when nothing matches.

    Raises:
        RuntimeError: if no candidate resolves to an existing file.
    """
    explicit = os.environ.get(env_var)
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).resolve())
    for name in names:
        if found := shutil.which(name):
            return found
    for directory in fallback_dirs:
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError(requirement)


def resolve_node_binary(*, purpose: str) -> str:
    """Return a Node executable able to run the Office workers."""
    return resolve_executable(
        NODE_BIN_ENV,
        ("node",),
        fallback_dirs=(codex_runtime_dependencies() / "node" / "bin",),
        requirement=(
            f"Node.js 20+ is required for {purpose}. "
            f"Set {NODE_BIN_ENV} to a Node 20+ executable."
        ),
    )


def resolve_artifact_tool(
    workspace_root: Path, *, purpose: str, hint: str = ""
) -> Path:
    """Return the built ``@oai/artifact-tool`` entrypoint.

    Args:
        workspace_root: Active agent workspace, searched first.
        purpose: Pipeline description used in the failure message.
        hint: Extra guidance appended to the failure message.

    Raises:
        RuntimeError: if no built entrypoint exists.
    """
    explicit = os.environ.get(ARTIFACT_TOOL_ENTRYPOINT_ENV)
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    package_roots = (
        workspace_root.joinpath(*_ARTIFACT_TOOL_PACKAGE),
        _repo_root().joinpath(*_ARTIFACT_TOOL_PACKAGE),
        codex_runtime_dependencies().joinpath("node", *_ARTIFACT_TOOL_PACKAGE),
    )
    for package_root in package_roots:
        candidates.append(package_root / "dist" / "node" / "artifact_tool.mjs")
        candidates.append(package_root / "dist" / "artifact_tool.mjs")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    message = (
        f"@oai/artifact-tool is required for {purpose}. "
        f"Set {ARTIFACT_TOOL_ENTRYPOINT_ENV} to its built artifact_tool.mjs."
    )
    raise RuntimeError(f"{message} {hint}".strip())


@dataclass(frozen=True, slots=True)
class NodeWorkerRuntime:
    """One pipeline's Node worker, invoked over a JSON request file.

    Attributes:
        worker: Absolute path to the ``.mjs`` entrypoint.
        label: Short pipeline name used to prefix error messages.
        purpose: Longer description used when a runtime dependency is missing.
        requirement_hint: Extra guidance appended to dependency failures.
    """

    worker: Path
    label: str
    purpose: str
    requirement_hint: str = ""

    async def run(
        self,
        action: str,
        request: dict[str, Any],
        *,
        workspace_root: Path,
        work_dir: Path,
        timeout_seconds: int = DEFAULT_WORKER_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Run *action* and return the worker's JSON response object.

        The request is handed over as a file rather than stdin so the payload
        stays inspectable in the work directory after a failure.

        Raises:
            RuntimeError: on timeout, non-zero exit, or unparseable output.
        """
        work_dir.mkdir(parents=True, exist_ok=True)
        request_path = work_dir / f"{action}-request.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        env = os.environ.copy()
        env[ARTIFACT_TOOL_ENTRYPOINT_ENV] = str(
            resolve_artifact_tool(
                workspace_root,
                purpose=self.purpose,
                hint=self.requirement_hint,
            )
        )
        process = await asyncio.create_subprocess_exec(
            resolve_node_binary(purpose=self.purpose),
            str(self.worker),
            action,
            str(request_path),
            cwd=str(workspace_root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(
                f"{self.label} {action} exceeded {timeout_seconds} seconds"
            ) from None
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or f"{self.label} worker failed ({action})")
        for line in reversed(stdout.decode("utf-8", errors="replace").splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise RuntimeError(f"{self.label} worker returned invalid JSON")


__all__ = [
    "ARTIFACT_TOOL_ENTRYPOINT_ENV",
    "DEFAULT_WORKER_TIMEOUT_SECONDS",
    "NODE_BIN_ENV",
    "NodeWorkerRuntime",
    "codex_runtime_dependencies",
    "file_sha256",
    "resolve_artifact_tool",
    "resolve_executable",
    "resolve_node_binary",
]
