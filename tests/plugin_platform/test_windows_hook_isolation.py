from __future__ import annotations

import asyncio
import os
import shutil
import socket
from pathlib import Path

import pytest

from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
    HookRegistration,
    HookSource,
)
from app.agent.plugins.hook_runner import (
    HOOK_ISOLATION_PROFILE,
    HookExecutionError,
    run_hook,
)
from app.agent.plugins.hook_staging import stage_python_runtime
from app.plugin_platform.hook_inspection import hook_digest
from app.plugin_platform.windows_hook_isolation import WindowsAppContainerBackend


def _registration(
    root: Path, source: str, *, timeout: int = 10, files: tuple[str, ...] = ()
) -> HookRegistration:
    entry = root / "hooks" / "main.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(source, encoding="utf-8")
    definition = HookDefinition(
        hook_id="windows-smoke",
        event=HookEvent.SESSION_START,
        runtime="python",
        command=("./hooks/main.py",),
        files=tuple(files),
        timeout_seconds=timeout,
        input_fields=("source",),
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    registration = HookRegistration(
        hook_id=definition.hook_id,
        plugin_id="windows-fixture",
        event=definition.event,
        source=HookSource.MANAGED_PLUGIN,
        definition=definition,
        digest=hook_digest(root, definition),
        trusted=True,
    )
    return registration


async def _run(root: Path, registration: HookRegistration, source: str = "smoke"):
    return await run_hook(
        registration,
        {"session_id": "private", "source": source},
        plugin_root=root,
        backend=WindowsAppContainerBackend(),
    )


@pytest.mark.asyncio
async def test_windows_appcontainer_runs_reviewed_python_hook(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    helper = tmp_path / "hooks" / "helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("VALUE = 'declared helper'\n", encoding="utf-8")
    registration = _registration(
        tmp_path,
        "import json, sys\n"
        "from helper import VALUE\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'context': VALUE}))\n",
        files=("./hooks/helper.py",),
    )
    backend = WindowsAppContainerBackend()
    assert backend.supports(HOOK_ISOLATION_PROFILE)

    result = await _run(tmp_path, registration)

    assert result.output == {"context": "declared helper"}


@pytest.mark.asyncio
async def test_windows_appcontainer_denies_undeclared_host_file_read_and_write(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    plugin_root = tmp_path / "plugin"
    settings_root = tmp_path / "settings-config"
    settings_root.mkdir()
    secret = settings_root / "credentials.json"
    secret.write_text("credential material", encoding="utf-8")
    target = settings_root / "escaped-write.txt"
    source = (
        "import json, pathlib, sys\n"
        f"secret = pathlib.Path({str(secret)!r})\n"
        f"target = pathlib.Path({str(target)!r})\n"
        "try:\n secret.read_text(); read = 'allowed'\n"
        "except OSError: read = 'denied'\n"
        "try:\n target.write_text('escape'); write = 'allowed'\n"
        "except OSError: write = 'denied'\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'context': read + '/' + write}))\n"
    )
    registration = _registration(plugin_root, source)

    result = await _run(plugin_root, registration)

    assert result.output == {"context": "denied/denied"}
    assert not target.exists()


@pytest.mark.asyncio
async def test_windows_appcontainer_runs_native_entrypoint_from_exact_read_set(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    from app.agent.plugins.hook_contract import HookDefinition

    package_root = tmp_path / "plugin"
    package_root.mkdir(parents=True)
    runtime_root = package_root / "native-runtime"
    build_runtime = stage_python_runtime(tmp_path / "build-runtime")
    shutil.copytree(build_runtime.parent, runtime_root)
    runtime_files = tuple(
        "./" + path.relative_to(package_root).as_posix()
        for path in sorted(runtime_root.rglob("*"))
        if path.is_file()
    )
    definition = HookDefinition(
        hook_id="windows-native-smoke",
        event=HookEvent.SESSION_START,
        runtime="native",
        command=(
            "./native-runtime/python.exe",
            "-I",
            "-S",
            "-c",
            "import json; print(json.dumps({'context':'native contained'}))",
        ),
        files=runtime_files,
        timeout_seconds=10,
        input_fields=("source",),
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    registration = HookRegistration(
        hook_id=definition.hook_id,
        plugin_id="windows-native-fixture",
        event=definition.event,
        source=HookSource.MANAGED_PLUGIN,
        definition=definition,
        digest=hook_digest(package_root, definition),
        trusted=True,
    )

    result = await _run(package_root, registration)

    assert result.output == {"context": "native contained"}


@pytest.mark.asyncio
async def test_windows_appcontainer_denies_network_and_child_process_creation(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.25)
    port = listener.getsockname()[1]
    source = (
        "import json, socket, subprocess, sys\n"
        "try:\n"
        f" socket.create_connection(('127.0.0.1', {port}), timeout=1); network = 'allowed'\n"
        "except OSError: network = 'denied'\n"
        "try:\n"
        " subprocess.run([sys.executable, '-I', '-S', '-c', 'pass'], check=True, timeout=2); child = 'allowed'\n"
        "except (OSError, subprocess.SubprocessError): child = 'denied'\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'context': network + '/' + child}))\n"
    )
    try:
        registration = _registration(tmp_path, source)
        result = await _run(tmp_path, registration)
    finally:
        listener.close()

    assert result.output == {"context": "denied/denied"}


@pytest.mark.asyncio
async def test_windows_appcontainer_timeout_kills_hook_process(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    registration = _registration(
        tmp_path,
        "import json, sys, time\njson.load(sys.stdin)\ntime.sleep(30)\n",
        timeout=1,
    )
    with pytest.raises(HookExecutionError, match="timed out"):
        await _run(tmp_path, registration)


@pytest.mark.asyncio
async def test_windows_appcontainer_enforces_output_limit(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    registration = _registration(
        tmp_path,
        "import json, sys\njson.load(sys.stdin)\nsys.stdout.write('x' * 100000)\n",
    )
    with pytest.raises(HookExecutionError, match="output exceeds"):
        await _run(tmp_path, registration)


@pytest.mark.asyncio
async def test_windows_appcontainer_cancellation_terminates_hook(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    registration = _registration(
        tmp_path,
        "import json, sys, time\njson.load(sys.stdin)\ntime.sleep(30)\n",
    )
    cancellation = asyncio.Event()
    task = asyncio.create_task(
        run_hook(
            registration,
            {"session_id": "private", "source": "smoke"},
            plugin_root=tmp_path,
            backend=WindowsAppContainerBackend(),
            cancellation_token=cancellation,
        )
    )
    await asyncio.sleep(0.2)
    cancellation.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_windows_appcontainer_enforces_cpu_and_memory_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "nt":
        pytest.skip("Windows AppContainer integration")
    cpu_registration = _registration(
        tmp_path,
        "import json, sys\njson.load(sys.stdin)\nwhile True: pass\n",
        timeout=10,
    )
    from app.agent.plugins import hook_runner

    monkeypatch.setattr(hook_runner, "HOOK_CPU_TIME_LIMIT_SECONDS", 1)
    with pytest.raises(HookExecutionError, match="status"):
        await _run(tmp_path, cpu_registration)

    memory_registration = _registration(
        tmp_path,
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "try:\n"
        " bytearray(256 * 1024 * 1024); outcome = 'unlimited'\n"
        "except MemoryError: outcome = 'limited'\n"
        "print(json.dumps({'context': outcome}))\n",
    )
    try:
        result = await _run(tmp_path, memory_registration)
    except HookExecutionError:
        # Windows may terminate the process at the Job Object commit limit.
        pass
    else:
        assert result.output == {"context": "limited"}
