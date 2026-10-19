"""Fail-closed tests for declarative hook execution."""

from pathlib import Path
import asyncio

import pytest

from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
    HookRegistration,
    HookSource,
)
from app.agent.plugins.hook_runner import (
    HookExecutionError,
    HookIsolationUnavailable,
    run_hook,
)


def _registration(*, trusted: bool = True, digest: str = "a" * 64) -> HookRegistration:
    definition = HookDefinition(
        hook_id="startup",
        event=HookEvent.SESSION_START,
        command=("./hooks/startup.py",),
        timeout_seconds=5,
        input_fields=("source",),
        output_fields=("context", "deny", "reason"),
        failure_policy=HookFailurePolicy.FAIL_OPEN,
    )
    return HookRegistration(
        hook_id="startup",
        plugin_id="example",
        event=HookEvent.SESSION_START,
        source=HookSource.MANAGED_PLUGIN,
        definition=definition,
        digest=digest,
        trusted=trusted,
    )


@pytest.mark.asyncio
async def test_unavailable_isolation_refuses_before_launch(tmp_path: Path) -> None:
    class Backend:
        def __init__(self) -> None:
            self.launch_called = False

        def supports(self, profile: str) -> bool:
            return False

        async def launch(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.launch_called = True
            raise AssertionError("unsupported backend must never launch")

    backend = Backend()
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "startup.py").write_text("raise SystemExit(0)")
    from app.plugin_platform.hook_inspection import hook_digest

    registration = _registration(
        digest=hook_digest(tmp_path, _registration().definition)
    )

    with pytest.raises(HookIsolationUnavailable):
        await run_hook(
            registration,
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=backend,
        )

    assert backend.launch_called is False


@pytest.mark.asyncio
async def test_backend_launch_failure_is_always_an_isolation_failure(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("fixture")
    from app.plugin_platform.hook_inspection import hook_digest

    registration = _registration(
        digest=hook_digest(tmp_path, _registration().definition)
    )

    class Backend:
        def supports(self, profile: str) -> bool:
            return profile == "evoflux-plugin-hook-v2"

        async def launch(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise OSError("AppContainer ACL setup failed")

    with pytest.raises(HookIsolationUnavailable, match="establish hook isolation"):
        await run_hook(
            registration,
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=Backend(),
        )


@pytest.mark.asyncio
async def test_untrusted_hook_is_rejected_before_backend_check(tmp_path: Path) -> None:
    class Backend:
        def supports(self, profile: str) -> bool:
            raise AssertionError("trust gate must run before backend selection")

        async def launch(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("untrusted hook must never launch")

    with pytest.raises(HookExecutionError, match="not trusted"):
        await run_hook(
            _registration(trusted=False),
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=Backend(),
        )


@pytest.mark.asyncio
async def test_runner_projects_input_and_uses_only_fixed_environment(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("fixture")
    from app.plugin_platform.hook_inspection import hook_digest

    registration = _registration(
        digest=hook_digest(tmp_path, _registration().definition)
    )

    class Process:
        async def communicate(self, input_bytes: bytes) -> tuple[bytes, bytes, int]:
            assert input_bytes == b'{"source":"new"}'
            return b'{"context":"hello"}', b"", 0

        async def terminate_tree(self) -> None:
            raise AssertionError("successful execution must not be terminated")

    class Backend:
        def supports(self, profile: str) -> bool:
            return profile == "evoflux-plugin-hook-v2"

        async def launch(
            self,
            argv,
            *,
            cwd,
            env,
            limits,
            cancellation_token,
            read_only_root,
            writable_root,
        ):
            assert argv == (
                str(
                    (
                        cwd.parent / "read-only" / "package" / "hooks" / "startup.py"
                    ).resolve()
                ),
            )
            assert cwd.name == "tmp"
            assert read_only_root == cwd.parent / "read-only"
            assert writable_root == cwd
            assert not cwd.is_relative_to(tmp_path.resolve())
            assert env == {
                "EVOFLUX_HOOK_PROTOCOL": "1",
                "TMP": str(cwd),
                "TEMP": str(cwd),
            }
            assert limits.timeout_seconds == 5
            assert cancellation_token is None
            return Process()

    result = await run_hook(
        registration,
        {"session_id": "not-disclosed", "source": "new"},
        plugin_root=tmp_path,
        backend=Backend(),
    )

    assert result.output == {"context": "hello"}


@pytest.mark.asyncio
async def test_static_context_reads_only_trusted_package_file_without_process(
    tmp_path: Path,
) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    skill = tmp_path / "skills" / "using-superpowers" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("follow the reviewed workflow", encoding="utf-8")
    definition = HookDefinition(
        hook_id="superpowers.session-start",
        event=HookEvent.SESSION_START,
        command=("./skills/using-superpowers/SKILL.md",),
        execution_kind="static_context",
        timeout_seconds=1,
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_OPEN,
        context_prefix="<EXTREMELY_IMPORTANT>\n",
        context_suffix="\n</EXTREMELY_IMPORTANT>",
    )
    registration = HookRegistration(
        hook_id=definition.hook_id,
        plugin_id="superpowers",
        event=definition.event,
        source=HookSource.MANAGED_PLUGIN,
        definition=definition,
        digest=hook_digest(tmp_path, definition),
        trusted=True,
    )

    result = await run_hook(
        registration,
        {"session_id": "s1", "source": "create"},
        plugin_root=tmp_path,
    )

    assert result.output == {
        "context": "<EXTREMELY_IMPORTANT>\n"
        "follow the reviewed workflow"
        "\n</EXTREMELY_IMPORTANT>"
    }


@pytest.mark.asyncio
async def test_static_context_rechecks_digest_and_rejects_oversized_file(
    tmp_path: Path,
) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    skill = tmp_path / "skill.md"
    skill.write_text("approved", encoding="utf-8")
    definition = HookDefinition(
        hook_id="static-context",
        event=HookEvent.SESSION_START,
        command=("./skill.md",),
        execution_kind="static_context",
        timeout_seconds=1,
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_OPEN,
    )
    registration = HookRegistration(
        hook_id=definition.hook_id,
        plugin_id="example",
        event=definition.event,
        source=HookSource.MANAGED_PLUGIN,
        definition=definition,
        digest=hook_digest(tmp_path, definition),
        trusted=True,
    )
    skill.write_text("changed", encoding="utf-8")

    with pytest.raises(HookExecutionError, match="changed after"):
        await run_hook(
            registration,
            {"session_id": "s1", "source": "create"},
            plugin_root=tmp_path,
        )

    skill.write_bytes(b"x" * (64 * 1024 + 1))
    oversized = registration.model_copy(
        update={"digest": hook_digest(tmp_path, definition)}
    )
    with pytest.raises(HookExecutionError, match="static context exceeds"):
        await run_hook(
            oversized,
            {"session_id": "s1", "source": "create"},
            plugin_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_runner_rechecks_digest_after_review_before_launch(
    tmp_path: Path,
) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("approved version")
    registration = _registration(
        digest=hook_digest(tmp_path, _registration().definition)
    )
    executable.write_text("changed after approval")

    class Backend:
        launch_called = False

        def supports(self, profile: str) -> bool:
            return True

        async def launch(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.launch_called = True
            raise AssertionError("stale digest must be rejected before launch")

    backend = Backend()
    with pytest.raises(HookExecutionError, match="changed after"):
        await run_hook(
            registration,
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=backend,
        )
    assert backend.launch_called is False


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected"),
    [
        (b"not-json", 0, "invalid JSON"),
        (b"{}", 3, "status 3"),
        (b"x" * (64 * 1024 + 1), 0, "output exceeds"),
    ],
    ids=["invalid-json", "nonzero-exit", "oversized-output"],
)
@pytest.mark.asyncio
async def test_runner_rejects_bad_exit_and_oversized_output(
    tmp_path: Path, stdout: bytes, returncode: int, expected: str
) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("fixture")
    registration = _registration(
        digest=hook_digest(tmp_path, _registration().definition)
    )

    class Process:
        async def communicate(self, _input):
            return stdout, b"private stderr", returncode

        async def terminate_tree(self):
            raise AssertionError("completed process should not be terminated")

    class Backend:
        def supports(self, profile):
            return True

        async def launch(self, _argv, *, limits, **kwargs):
            assert limits.max_output_bytes == 64 * 1024
            return Process()

    with pytest.raises(HookExecutionError, match=expected):
        await run_hook(
            registration,
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=Backend(),
        )


@pytest.mark.asyncio
async def test_runner_timeout_terminates_contained_process_tree(tmp_path: Path) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("fixture")
    definition = _registration().definition.model_copy(update={"timeout_seconds": 1})
    registration = _registration(digest=hook_digest(tmp_path, definition)).model_copy(
        update={"definition": definition}
    )

    class Process:
        terminated = False

        async def communicate(self, _input):
            await asyncio.sleep(10)
            return b"{}", b"", 0

        async def terminate_tree(self):
            self.terminated = True

    process = Process()

    class Backend:
        def supports(self, profile):
            return True

        async def launch(self, _argv, **kwargs):
            return process

    with pytest.raises(HookExecutionError, match="timed out"):
        await run_hook(
            registration,
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=Backend(),
        )
    assert process.terminated is True


@pytest.mark.asyncio
async def test_runner_cancellation_terminates_contained_process_tree(
    tmp_path: Path,
) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("fixture")
    registration = _registration(
        digest=hook_digest(tmp_path, _registration().definition)
    )

    class Process:
        terminated = False

        async def communicate(self, _input):
            await asyncio.sleep(10)
            return b"{}", b"", 0

        async def terminate_tree(self):
            self.terminated = True

    process = Process()

    class Backend:
        def supports(self, profile):
            return True

        async def launch(self, _argv, **kwargs):
            return process

    cancellation = asyncio.Event()
    task = asyncio.create_task(
        run_hook(
            registration,
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=Backend(),
            cancellation_token=cancellation,
        )
    )
    await asyncio.sleep(0.02)
    cancellation.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated is True


@pytest.mark.asyncio
async def test_runner_observes_cancellation_while_backend_is_launching(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("fixture")
    from app.plugin_platform.hook_inspection import hook_digest

    registration = _registration(
        digest=hook_digest(tmp_path, _registration().definition)
    )
    launch_started = asyncio.Event()

    class Backend:
        def supports(self, profile):
            return True

        async def launch(self, *args, **kwargs):  # noqa: ANN002, ANN003
            launch_started.set()
            await asyncio.Event().wait()

    cancellation = asyncio.Event()
    task = asyncio.create_task(
        run_hook(
            registration,
            {"session_id": "s1", "source": "new"},
            plugin_root=tmp_path,
            backend=Backend(),
            cancellation_token=cancellation,
        )
    )
    await launch_started.wait()
    cancellation.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)


def test_staging_copies_only_hash_bound_declared_files(tmp_path: Path) -> None:
    from app.agent.plugins.hook_staging import stage_hook_files
    from app.plugin_platform.hook_inspection import hook_digest

    source = tmp_path / "source"
    (source / "hooks").mkdir(parents=True)
    (source / "data").mkdir()
    (source / "hooks" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "hooks" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "data" / "settings.yaml").write_text(
        "credential: secret\n", encoding="utf-8"
    )
    definition = HookDefinition(
        hook_id="stage-test",
        event=HookEvent.SESSION_START,
        runtime="python",
        command=("./hooks/main.py",),
        files=("./hooks/helper.py",),
        timeout_seconds=5,
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    digest = hook_digest(source, definition)
    staged = tmp_path / "staged"
    entry = stage_hook_files(source, definition, staged, expected_digest=digest)

    assert entry == staged / "hooks" / "main.py"
    assert hook_digest(staged, definition) == digest
    assert sorted(
        path.relative_to(staged).as_posix() for path in staged.rglob("*")
    ) == [
        "hooks",
        "hooks/helper.py",
        "hooks/main.py",
    ]


def test_staging_rejects_content_changed_after_review(tmp_path: Path) -> None:
    from app.agent.plugins.hook_staging import stage_hook_files
    from app.plugin_platform.hook_inspection import hook_digest

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("approved", encoding="utf-8")
    definition = HookDefinition(
        hook_id="stage-change",
        event=HookEvent.SESSION_START,
        runtime="native",
        command=("./main.py",),
        timeout_seconds=5,
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    digest = hook_digest(source, definition)
    (source / "main.py").write_text("changed", encoding="utf-8")

    with pytest.raises(HookExecutionError, match="changed"):
        stage_hook_files(
            source,
            definition,
            tmp_path / "staged",
            expected_digest=digest,
        )


@pytest.mark.asyncio
async def test_python_runtime_uses_active_interpreter_and_staged_entrypoint(
    tmp_path: Path,
) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    entrypoint = tmp_path / "hooks" / "main.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("print('{}')\n", encoding="utf-8")
    definition = HookDefinition(
        hook_id="python-runtime",
        event=HookEvent.SESSION_START,
        runtime="python",
        command=("./hooks/main.py", "--safe"),
        timeout_seconds=5,
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    registration = _registration(digest=hook_digest(tmp_path, definition)).model_copy(
        update={"definition": definition}
    )

    class Process:
        async def communicate(self, _input):
            return b'{"context":"ok"}', b"", 0

        async def terminate_tree(self):
            raise AssertionError("successful execution must not be terminated")

    class Backend:
        def supports(self, _profile):
            return True

        async def launch(self, argv, *, cwd, env, limits, cancellation_token, **kwargs):
            assert argv[:3] == (
                str(
                    (
                        cwd.parent / "read-only" / "python-runtime" / "python.exe"
                    ).resolve()
                ),
                "-I",
                "-S",
            )
            assert argv[3] == "-c"
            assert "sys.path.extend([os.path.dirname(entry)" in argv[4]
            assert Path(argv[5]).name == "main.py"
            assert argv[6:] == ("--safe",)
            assert Path(argv[0]).is_relative_to(
                cwd.parent / "read-only" / "python-runtime"
            )
            assert Path(argv[5]).is_relative_to(cwd.parent / "read-only" / "package")
            return Process()

    result = await run_hook(
        registration,
        {"session_id": "s1", "source": "new"},
        plugin_root=tmp_path,
        backend=Backend(),
    )

    assert result.output == {"context": "ok"}


def test_staged_python_runtime_has_isolated_stdlib_and_no_site_packages(
    tmp_path: Path,
) -> None:
    import subprocess

    from app.agent.plugins.hook_staging import stage_python_runtime

    runtime = stage_python_runtime(tmp_path / "runtime")
    assert runtime.is_file()
    assert (runtime.parent / "python312.zip").is_file()
    assert (runtime.parent / "DLLs").is_dir()
    assert not (runtime.parent / "site-packages").exists()

    completed = subprocess.run(
        [
            str(runtime),
            "-I",
            "-S",
            "-c",
            "import json,sys; print(json.dumps(sys.flags.no_site))",
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    assert completed.stdout.strip() == "1"
