"""Bounded hook runner boundary with no unrestricted subprocess fallback.

The default backend selects Windows AppContainer + Job Object containment and
refuses executable hooks on hosts without that verified profile.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.agent.plugins.hook_contract import (
    HookEvent,
    HookDefinition,
    HookRegistration,
    validate_event_input,
    validate_hook_output,
)

HOOK_ISOLATION_PROFILE = "evoflux-plugin-hook-v2"
STATIC_CONTEXT_PROFILE = "evoflux-static-context-v1"
MAX_HOOK_INPUT_BYTES = 64 * 1024
MAX_HOOK_OUTPUT_BYTES = 64 * 1024
HOOK_CPU_TIME_LIMIT_SECONDS = 10


class HookExecutionError(RuntimeError):
    """A hook could not be executed or returned an invalid result."""


class HookIsolationUnavailable(HookExecutionError):
    """No backend can enforce the required operating-system profile."""


@dataclass(frozen=True, slots=True)
class HookExecutionLimits:
    timeout_seconds: int
    cpu_time_seconds: int = HOOK_CPU_TIME_LIMIT_SECONDS
    max_input_bytes: int = MAX_HOOK_INPUT_BYTES
    max_output_bytes: int = MAX_HOOK_OUTPUT_BYTES
    max_processes: int = 1
    memory_bytes: int = 128 * 1024 * 1024


class IsolatedProcess(Protocol):
    """Process handle whose methods operate on the entire contained process tree."""

    async def communicate(self, input_bytes: bytes) -> tuple[bytes, bytes, int]: ...

    async def terminate_tree(self) -> None: ...


class HookIsolationBackend(Protocol):
    """Native isolation provider; support means every profile control is enforced."""

    def supports(self, profile: str) -> bool: ...

    async def launch(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        limits: HookExecutionLimits,
        cancellation_token: asyncio.Event | None,
        read_only_root: Path,
        writable_root: Path,
    ) -> IsolatedProcess: ...


class UnavailableHookIsolationBackend:
    """Safe default until a native backend passes platform containment review."""

    def supports(self, profile: str) -> bool:
        return False

    async def launch(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        limits: HookExecutionLimits,
        cancellation_token: asyncio.Event | None,
        read_only_root: Path,
        writable_root: Path,
    ) -> IsolatedProcess:
        del argv, cwd, env, limits, cancellation_token, read_only_root, writable_root
        raise HookIsolationUnavailable("hook isolation backend is unavailable")


@dataclass(frozen=True, slots=True)
class HookExecutionResult:
    hook_id: str
    event: HookEvent
    output: dict


_UNAVAILABLE_BACKEND = UnavailableHookIsolationBackend()


def default_hook_isolation_backend() -> HookIsolationBackend:
    """Select only a platform backend whose implementation can enforce v2."""

    if os.name == "nt":
        from app.plugin_platform.windows_hook_isolation import (
            WindowsAppContainerBackend,
        )

        return WindowsAppContainerBackend()
    return _UNAVAILABLE_BACKEND


def hook_isolation_available() -> bool:
    """Whether this host has the native backend for the current hook profile."""

    return default_hook_isolation_backend().supports(HOOK_ISOLATION_PROFILE)


def hook_trust_profile(definition: HookDefinition) -> str:
    """Return the digest approval profile for a normalized hook action."""

    if definition.execution_kind == "static_context":
        return STATIC_CONTEXT_PROFILE
    return HOOK_ISOLATION_PROFILE


async def _communicate_isolated(
    backend: HookIsolationBackend,
    argv: tuple[str, ...],
    *,
    cwd: Path,
    read_only_root: Path,
    env: dict[str, str],
    limits: HookExecutionLimits,
    cancellation_token: asyncio.Event | None,
    input_bytes: bytes,
    timeout_seconds: int,
) -> bytes:
    loop = asyncio.get_running_loop()
    started = loop.time()
    launch_task = asyncio.create_task(
        backend.launch(
            argv,
            cwd=cwd,
            env=env,
            limits=limits,
            cancellation_token=cancellation_token,
            read_only_root=read_only_root,
            writable_root=cwd,
        )
    )
    cancel_task = (
        asyncio.create_task(cancellation_token.wait())
        if cancellation_token is not None
        else None
    )
    process: IsolatedProcess | None = None
    communicate_task: asyncio.Task[tuple[bytes, bytes, int]] | None = None

    async def abort_launch() -> IsolatedProcess | None:
        if not launch_task.done():
            launch_task.cancel()
        result = await asyncio.gather(launch_task, return_exceptions=True)
        launched = result[0]
        return launched if not isinstance(launched, BaseException) else None

    try:
        launch_waiters = (
            (launch_task, cancel_task) if cancel_task is not None else (launch_task,)
        )
        done, _ = await asyncio.wait(
            launch_waiters,
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task is not None and cancel_task in done:
            process = await abort_launch()
            if process is not None:
                await process.terminate_tree()
                process = None
            raise asyncio.CancelledError
        if launch_task not in done:
            process = await abort_launch()
            if process is not None:
                await process.terminate_tree()
                process = None
            raise HookExecutionError("hook timed out")
        try:
            process = launch_task.result()
        except HookIsolationUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - launch establishes security
            raise HookIsolationUnavailable(
                "could not establish hook isolation on this host"
            ) from exc

        remaining = timeout_seconds - (loop.time() - started)
        if cancellation_token is not None and cancellation_token.is_set():
            await process.terminate_tree()
            process = None
            raise asyncio.CancelledError
        if remaining <= 0:
            await process.terminate_tree()
            process = None
            raise HookExecutionError("hook timed out")

        communicate_task = asyncio.create_task(process.communicate(input_bytes))
        waiters = (
            (communicate_task, cancel_task)
            if cancel_task is not None
            else (communicate_task,)
        )
        done, _ = await asyncio.wait(
            waiters,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task is not None and cancel_task in done:
            raise asyncio.CancelledError
        if communicate_task not in done:
            await process.terminate_tree()
            process = None
            communicate_task.cancel()
            await asyncio.gather(communicate_task, return_exceptions=True)
            raise HookExecutionError("hook timed out")
        stdout, _stderr, returncode = communicate_task.result()
    except asyncio.CancelledError:
        if process is None:
            process = await abort_launch()
        if process is not None:
            await process.terminate_tree()
        if communicate_task is not None and not communicate_task.done():
            communicate_task.cancel()
            await asyncio.gather(communicate_task, return_exceptions=True)
        raise
    except HookExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001 - backend failures are hook failures
        raise HookExecutionError("isolated hook process failed") from exc
    finally:
        if cancel_task is not None:
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)

    if returncode != 0:
        raise HookExecutionError(f"hook exited with status {returncode}")
    if len(stdout) > limits.max_output_bytes:
        raise HookExecutionError("hook output exceeds the configured limit")
    return stdout


def _resolve_hook_command(
    registration: HookRegistration, plugin_root: Path
) -> tuple[Path, tuple[str, ...]]:
    definition = registration.definition
    if definition is None:
        raise HookExecutionError("legacy Python hooks are not declarative commands")

    root = plugin_root.resolve(strict=True)
    relative = definition.command[0]
    if not relative.startswith("./"):
        raise HookExecutionError("hook executable must be package-relative")
    parts = relative[2:].replace("\\", "/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise HookExecutionError("hook executable path contains an invalid component")
    candidate = root
    try:
        for part in parts:
            candidate = candidate / part
            if stat.S_ISLNK(candidate.lstat().st_mode):
                raise HookExecutionError(
                    "hook executable paths cannot contain symlinks"
                )
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise HookExecutionError(
            "hook executable escapes or is missing from package"
        ) from exc
    if not stat.S_ISREG(candidate.stat().st_mode):
        raise HookExecutionError("hook executable must be a regular package file")

    return root, (str(resolved), *definition.command[1:])


async def run_hook(
    registration: HookRegistration,
    event_input: dict,
    *,
    plugin_root: Path,
    backend: HookIsolationBackend | None = None,
    cancellation_token: asyncio.Event | None = None,
) -> HookExecutionResult:
    """Run one trusted declarative hook through a verified isolation backend.

    The hook gets only declared event fields, a fixed non-secret environment,
    and its package directory as cwd. The OS backend must bound the process
    tree, filesystem, network, CPU, memory, input, and output.
    """

    if not registration.trusted:
        raise HookExecutionError("hook is not trusted for its current digest")
    if not registration.enabled:
        raise HookExecutionError("hook is disabled")
    definition = registration.definition
    if definition is None:
        raise HookExecutionError("legacy Python hooks cannot use the command runner")

    if cancellation_token is not None and cancellation_token.is_set():
        raise asyncio.CancelledError

    selected_backend: HookIsolationBackend | None = None
    if definition.execution_kind != "static_context":
        selected_backend = backend or default_hook_isolation_backend()
        if not selected_backend.supports(HOOK_ISOLATION_PROFILE):
            # Isolation is a core policy gate, not a hook execution error.
            # Check it before package resolution so fail_open cannot hide an
            # unavailable security boundary behind a missing/invalid file.
            raise HookIsolationUnavailable(
                f"no backend enforces {HOOK_ISOLATION_PROFILE} on this host"
            )

    safe_input = validate_event_input(
        registration.event,
        event_input,
        declared_fields=definition.input_fields,
    )
    input_bytes = json.dumps(
        safe_input, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(input_bytes) > MAX_HOOK_INPUT_BYTES:
        raise HookExecutionError("hook input exceeds the configured limit")

    cwd, argv = _resolve_hook_command(registration, plugin_root)
    if definition.execution_kind == "static_context":
        context_path = Path(argv[0])
        try:
            with context_path.open("rb") as handle:
                context_bytes = handle.read(MAX_HOOK_OUTPUT_BYTES + 1)
        except OSError as exc:
            raise HookExecutionError("static context file could not be read") from exc
        if len(context_bytes) > MAX_HOOK_OUTPUT_BYTES:
            raise HookExecutionError("static context exceeds the configured limit")
        if registration.digest is not None:
            from app.plugin_platform.hook_inspection import hook_digest

            try:
                current_digest = hook_digest(
                    plugin_root,
                    definition,
                    referenced_bytes=context_bytes,
                )
            except (OSError, ValueError) as exc:
                raise HookExecutionError(
                    "hook changed or became invalid after review"
                ) from exc
            if current_digest.lower() != registration.digest.lower():
                raise HookExecutionError("hook changed after its digest was reviewed")
        try:
            context_text = context_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise HookExecutionError("static context file is not valid UTF-8") from exc
        output = validate_hook_output(
            registration.event,
            definition.output_fields,
            {
                "context": (
                    definition.context_prefix + context_text + definition.context_suffix
                )
            },
        )
        if (
            len(
                json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            > MAX_HOOK_OUTPUT_BYTES
        ):
            raise HookExecutionError("static context exceeds the configured limit")
        return HookExecutionResult(
            hook_id=registration.hook_id,
            event=registration.event,
            output=output,
        )

    if registration.digest is None:
        raise HookExecutionError("hook has no reviewed digest")
    from app.agent.plugins.hook_staging import (
        stage_hook_files,
        stage_python_runtime,
        staged_python_argv,
    )

    limits = HookExecutionLimits(
        timeout_seconds=definition.timeout_seconds,
        cpu_time_seconds=HOOK_CPU_TIME_LIMIT_SECONDS,
    )
    assert selected_backend is not None
    with tempfile.TemporaryDirectory(prefix="evoflux-hook-") as temporary:
        temp_root = Path(temporary)
        read_only_root = temp_root / "read-only"
        read_only_root.mkdir()
        package_stage = read_only_root / "package"
        writable_root = temp_root / "tmp"
        writable_root.mkdir()
        entrypoint = stage_hook_files(
            plugin_root,
            definition,
            package_stage,
            expected_digest=registration.digest,
        )
        argv = (
            staged_python_argv(
                entrypoint,
                definition.command,
                interpreter=stage_python_runtime(read_only_root / "python-runtime"),
            )
            if definition.runtime == "python"
            else (str(entrypoint), *definition.command[1:])
        )
        stdout = await _communicate_isolated(
            selected_backend,
            argv,
            cwd=writable_root,
            read_only_root=read_only_root,
            env={
                "EVOFLUX_HOOK_PROTOCOL": "1",
                "TMP": str(writable_root),
                "TEMP": str(writable_root),
            },
            limits=limits,
            cancellation_token=cancellation_token,
            input_bytes=input_bytes,
            timeout_seconds=definition.timeout_seconds,
        )
    try:
        decoded = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HookExecutionError("hook returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise HookExecutionError("hook output must be a JSON object")
    output = validate_hook_output(
        registration.event,
        definition.output_fields,
        decoded,
    )
    return HookExecutionResult(
        hook_id=registration.hook_id,
        event=registration.event,
        output=output,
    )


__all__ = [
    "HOOK_ISOLATION_PROFILE",
    "STATIC_CONTEXT_PROFILE",
    "HookExecutionError",
    "HookExecutionLimits",
    "HookExecutionResult",
    "HookIsolationBackend",
    "HookIsolationUnavailable",
    "IsolatedProcess",
    "UnavailableHookIsolationBackend",
    "hook_trust_profile",
    "default_hook_isolation_backend",
    "hook_isolation_available",
    "run_hook",
]
