"""Stage only digest-approved hook files into a fresh execution directory."""

from __future__ import annotations

import os
import shutil
import sys
import sysconfig
import zipfile
from pathlib import Path

from app.agent.plugins.hook_contract import HookDefinition
from app.agent.plugins.hook_runner import HookExecutionError


def _referenced_paths(definition: HookDefinition) -> tuple[str, ...]:
    entrypoint = definition.command[0]
    return tuple(sorted({entrypoint, *definition.files}))


def stage_hook_files(
    package_root: str | Path,
    definition: HookDefinition,
    stage_root: str | Path,
    *,
    expected_digest: str,
) -> Path:
    """Copy the exact declared read-set and verify its staged identity.

    ``stage_root`` must be new and empty by construction. The source digest is
    checked immediately before reading, then the digest is recomputed over the
    staged bytes before the caller can expose the directory to a child process.
    """

    from app.plugin_platform.hook_inspection import (
        MAX_HOOK_TOTAL_FILE_BYTES,
        _resolve_package_file,
        hook_digest,
    )

    source_root = Path(package_root).resolve(strict=True)
    destination = Path(stage_root)
    if destination.exists():
        raise HookExecutionError("hook staging directory must be new")
    if hook_digest(source_root, definition).lower() != expected_digest.lower():
        raise HookExecutionError("hook changed after its digest was reviewed")

    source_files: list[tuple[Path, str, bytes]] = []
    total_bytes = 0
    for relative in _referenced_paths(definition):
        source, normalized = _resolve_package_file(source_root, relative)
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise HookExecutionError("hook file could not be staged") from exc
        total_bytes += len(data)
        if total_bytes > MAX_HOOK_TOTAL_FILE_BYTES:
            raise HookExecutionError("hook files exceed the configured total limit")
        source_files.append((source, normalized, data))

    destination.mkdir(parents=True, exist_ok=False)
    try:
        for _source, normalized, data in source_files:
            target = destination.joinpath(*normalized.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                target.chmod(0o444)
            except OSError:
                # ACLs from the native isolation backend remain authoritative.
                pass
        staged_digest = hook_digest(destination, definition)
        if staged_digest.lower() != expected_digest.lower():
            raise HookExecutionError("staged hook digest does not match approval")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    return destination.joinpath(
        *definition.command[0][2:].replace("\\", "/").split("/")
    )


def stage_python_runtime(runtime_root: str | Path) -> Path:
    """Copy the active EvoFlux CPython runtime and stdlib, excluding packages."""

    destination = Path(runtime_root)
    if destination.exists():
        raise HookExecutionError("Python runtime staging directory must be new")
    base = Path(sys.base_prefix).resolve(strict=True)
    stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
    executable = base / "python.exe"
    if not executable.is_file():
        executable = Path(sys.executable).resolve(strict=True)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(executable, destination / "python.exe")
        library_archive = (
            destination / f"python{sysconfig.get_config_var('VERSION')}.zip"
        )
        with zipfile.ZipFile(
            library_archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for source in stdlib.rglob("*"):
                if (
                    not source.is_file()
                    or "site-packages" in source.parts
                    or "__pycache__" in source.parts
                ):
                    continue
                archive.write(source, source.relative_to(stdlib).as_posix())
        for dll_path in base.glob("*.dll"):
            if dll_path.is_file():
                shutil.copy2(dll_path, destination / dll_path.name)
        dlls = base / "DLLs"
        if dlls.is_dir():
            shutil.copytree(dlls, destination / "DLLs")
        for path in destination.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        for path in sorted(destination.rglob("*"), reverse=True):
            if path.is_dir():
                path.chmod(0o555)
        destination.chmod(0o555)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination / "python.exe"


def staged_python_argv(
    entrypoint: Path,
    command: tuple[str, ...],
    *,
    interpreter: str | Path,
) -> tuple[str, ...]:
    """Build an isolated-mode argv with imports limited to staged package files."""

    entry = str(entrypoint.resolve(strict=True))
    bootstrap = (
        "import os,runpy,sys;"
        "entry=sys.argv[1];"
        "args=sys.argv[2:];"
        "sys.path.extend([os.path.dirname(entry),"
        "os.path.dirname(os.path.dirname(entry))]);"
        "sys.argv=[entry,*args];"
        "runpy.run_path(entry,run_name='__main__')"
    )
    return (
        str(Path(interpreter).resolve(strict=True)),
        "-I",
        "-S",
        "-c",
        bootstrap,
        entry,
        *command[1:],
    )


__all__ = ["stage_hook_files", "stage_python_runtime", "staged_python_argv"]
