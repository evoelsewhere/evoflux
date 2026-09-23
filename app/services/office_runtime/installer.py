"""User-triggered install of the LibreOffice rendering runtime.

The install runs as a background task that outlives the request which started
it, so the viewer can poll ``runtime_status()`` for byte-level progress. Every
archive is checked against the pinned asset (size, SHA-256) before a single
member is extracted, extraction refuses anything outside ``soffice/`` or any
special file, and the verified tree replaces the previous version atomically.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from loguru import logger

from app.core.config import settings
from app.services.office_runtime.manifest import (
    RUNTIME_ID,
    RUNTIME_ROOT,
    RuntimeAsset,
    current_asset,
)

InstallPhase = Literal["downloading", "verifying", "extracting", "failed"]

_MAX_ENTRIES = 60_000
_MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024
_CHUNK = 1024 * 1024
_PROGRESS_CHUNK = 64 * 1024
_INSTALL_RECORD = "install.json"


class RuntimeInstallError(RuntimeError):
    """The runtime could not be downloaded, verified or installed."""


@dataclass(frozen=True, slots=True)
class InstallJob:
    phase: InstallPhase
    version: str
    bytes_done: int
    bytes_total: int
    started_at: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class InstalledRuntime:
    version: str
    executable: Path
    root: Path


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    """What the viewer needs to decide whether to offer the download."""

    available: bool
    platform: str | None
    version: str | None
    download_bytes: int | None
    install_bytes: int | None
    installed_version: str | None
    job: InstallJob | None


_job: InstallJob | None = None
_task: asyncio.Task[None] | None = None
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def runtime_home() -> Path:
    return Path(settings.EVOFLUX_DATA_DIR) / "runtimes" / RUNTIME_ID


def installed_runtime() -> InstalledRuntime | None:
    """Return the active installed runtime if its executable is present."""
    home = runtime_home()
    try:
        record = json.loads((home / _INSTALL_RECORD).read_text(encoding="utf-8"))
        version = str(record["version"])
        executable = str(record["executable"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    root = home / version
    path = root.joinpath(*PurePosixPath(executable).parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return InstalledRuntime(version=version, executable=path, root=root)


def expose_to_tool_environment(env: dict[str, str]) -> dict[str, str]:
    """Advertise the installed runtime to agent-run commands.

    Agent shells get a scrubbed environment, so the runtime the user installed
    for exact previews was invisible to the Office Skills, which look for
    ``EVOFLUX_SOFFICE`` or ``soffice`` on ``PATH``. Only the executable's
    location is added; its directory is appended to ``PATH`` so it never
    shadows a tool the user already has.
    """
    runtime = installed_runtime()
    if runtime is None:
        return env
    executable = str(runtime.executable)
    env["EVOFLUX_SOFFICE"] = executable
    path_key = next((key for key in env if key.upper() == "PATH"), "PATH")
    directory = str(runtime.executable.parent)
    entries = [entry for entry in env.get(path_key, "").split(os.pathsep) if entry]
    folded = os.path.normcase(os.path.normpath(directory))
    if not any(
        os.path.normcase(os.path.normpath(entry)) == folded for entry in entries
    ):
        entries.append(directory)
    env[path_key] = os.pathsep.join(entries)
    return env


def runtime_status() -> RuntimeStatus:
    asset = current_asset()
    installed = installed_runtime()
    return RuntimeStatus(
        available=asset is not None,
        platform=asset.platform if asset else None,
        version=asset.version if asset else None,
        download_bytes=asset.size if asset else None,
        install_bytes=asset.installed_size if asset else None,
        installed_version=installed.version if installed else None,
        job=_job,
    )


def _set_job(job: InstallJob | None) -> None:
    global _job
    with _lock:
        _job = job


def _update(**changes: object) -> None:
    global _job
    with _lock:
        if _job is not None:
            _job = replace(_job, **changes)  # type: ignore[arg-type]


def partial_download_path(asset: RuntimeAsset) -> Path:
    """Where an unfinished download of ``asset`` is kept between attempts."""
    return runtime_home() / f".download-{asset.sha256}.part"


def _hash_existing(path: Path, limit: int) -> tuple[hashlib._Hash, int]:
    digest = hashlib.sha256()
    received = 0
    try:
        with path.open("rb") as handle:
            while received < limit and (chunk := handle.read(_CHUNK)):
                chunk = chunk[: limit - received]
                digest.update(chunk)
                received += len(chunk)
    except FileNotFoundError:
        pass
    return digest, received


async def _download(asset: RuntimeAsset, destination: Path) -> str:
    """Stream the archive to ``destination`` and return its SHA-256.

    Slow or flaky links are the norm for a ~200 MB download, so a previous
    attempt's bytes are kept and the transfer resumes with an HTTP range
    request. The final SHA-256 still covers every byte, resumed or not.
    """
    digest, received = await asyncio.to_thread(_hash_existing, destination, asset.size)
    if destination.exists() and destination.stat().st_size != received:
        os.truncate(destination, received)
    _update(bytes_done=received)

    def accept(chunk: bytes, handle: Any) -> None:
        nonlocal received
        received += len(chunk)
        if received > asset.size:
            raise RuntimeInstallError("Runtime archive is larger than pinned")
        digest.update(chunk)
        handle.write(chunk)
        _update(bytes_done=received)

    parsed = urlparse(asset.url)
    if received < asset.size and parsed.scheme == "file":
        source = Path(url2pathname(unquote(parsed.path)))
        with source.open("rb") as reader, destination.open("ab") as handle:
            reader.seek(received)
            while chunk := await asyncio.to_thread(reader.read, _PROGRESS_CHUNK):
                accept(chunk, handle)
    elif received < asset.size:
        timeout = httpx.Timeout(60.0, read=120.0)
        headers = {"Range": f"bytes={received}-"} if received else {}
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", asset.url, headers=headers) as response:
                if response.status_code == 200 and received:
                    # The server ignored the range: start over.
                    digest, received = hashlib.sha256(), 0
                    os.truncate(destination, 0)
                    _update(bytes_done=0)
                elif response.status_code not in {200, 206}:
                    raise RuntimeInstallError(
                        f"Download failed with HTTP {response.status_code}"
                    )
                with destination.open("ab") as handle:
                    # No fixed chunk size: on a slow link waiting to fill a
                    # megabyte froze the progress bar for tens of seconds.
                    async for chunk in response.aiter_bytes():
                        accept(chunk, handle)
    if received != asset.size:
        raise RuntimeInstallError(
            f"Runtime archive is {received} bytes, expected {asset.size}"
        )
    return digest.hexdigest()


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Validate every member before extracting any of them."""
    members: list[tarfile.TarInfo] = []
    seen: set[str] = set()
    total = 0
    for member in archive:
        if len(members) >= _MAX_ENTRIES:
            raise RuntimeInstallError("Runtime archive has too many entries")
        name = member.name.replace("\\", "/")
        path = PurePosixPath(name)
        parts = path.parts
        if (
            not parts
            or path.is_absolute()
            or ":" in parts[0]
            or any(part in {"", ".", ".."} for part in parts)
            or parts[0] != RUNTIME_ROOT
        ):
            raise RuntimeInstallError(f"Runtime archive entry escapes soffice/: {name}")
        if member.issym() or member.islnk():
            target = PurePosixPath(member.linkname.replace("\\", "/"))
            resolved = PurePosixPath(os.path.normpath(path.parent / target))
            if (
                target.is_absolute()
                or not resolved.parts
                or resolved.parts[0] != RUNTIME_ROOT
            ):
                raise RuntimeInstallError(f"Runtime archive link escapes: {name}")
        elif not (member.isfile() or member.isdir()):
            raise RuntimeInstallError(f"Runtime archive has a special file: {name}")
        key = path.as_posix().casefold()
        if key in seen and not member.isdir():
            raise RuntimeInstallError(f"Runtime archive has a duplicate path: {name}")
        seen.add(key)
        total += max(member.size, 0)
        if total > _MAX_EXTRACTED_BYTES:
            raise RuntimeInstallError("Runtime archive expands beyond the size limit")
        members.append(member)
    if not members:
        raise RuntimeInstallError("Runtime archive is empty")
    return members


def _extract(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = _safe_members(archive)
        archive.extractall(destination, members=members, filter="tar")
    for path in destination.rglob("*"):
        if path.is_file() and not path.is_symlink():
            mode = path.stat().st_mode
            path.chmod((mode & 0o755) | stat.S_IRUSR | stat.S_IWUSR)


def _replace_with_retry(source: Path, target: Path, *, attempts: int = 40) -> None:
    """Rename a freshly extracted tree, riding out transient Windows locks.

    Antivirus and the search indexer open newly written executables for a
    few seconds; renaming their parent directory meanwhile fails with
    ``PermissionError`` (WinError 5/32) even though nothing is wrong.
    """
    delay = 0.25
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)


def _activate(asset: RuntimeAsset, extracted: Path) -> None:
    home = runtime_home()
    target = home / asset.version
    executable = extracted.joinpath(*PurePosixPath(asset.executable).parts)
    if not executable.is_file():
        raise RuntimeInstallError(f"Runtime is missing {asset.executable}")
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    if sys.platform == "darwin":
        # The sidecar's own download is not quarantined, but a bundle copied
        # in by other means may be; Gatekeeper would then block the ad-hoc
        # signed (trimmed) app on first launch.
        subprocess.run(
            ["xattr", "-dr", "com.apple.quarantine", str(extracted)],
            capture_output=True,
            check=False,
        )
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    _replace_with_retry(extracted, target)
    record = {
        "id": RUNTIME_ID,
        "version": asset.version,
        "platform": asset.platform,
        "sha256": asset.sha256,
        "executable": asset.executable,
        "installed_at": _now(),
    }
    temporary = home / f".{_INSTALL_RECORD}.tmp"
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temporary, home / _INSTALL_RECORD)
    for sibling in home.iterdir():
        if (
            sibling.is_dir()
            and sibling.name not in {asset.version, "profile"}
            and not (sibling.name.startswith("."))
        ):
            shutil.rmtree(sibling, ignore_errors=True)


async def _install(asset: RuntimeAsset) -> None:
    home = runtime_home()
    home.mkdir(parents=True, exist_ok=True)
    archive = partial_download_path(asset)
    try:
        digest = await _download(asset, archive)
    except asyncio.CancelledError:
        # The user stopped the download: do not keep its bytes around.
        archive.unlink(missing_ok=True)
        raise
    # Any other failure keeps the partial file so Retry resumes from it.
    _update(phase="verifying")
    if digest != asset.sha256:
        archive.unlink(missing_ok=True)
        raise RuntimeInstallError("Runtime archive checksum does not match")
    _update(phase="extracting")
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=home))
    try:
        extracted = staging / "tree"
        extracted.mkdir()
        await asyncio.to_thread(_extract, archive, extracted)
        await asyncio.to_thread(_activate, asset, extracted)
        archive.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def start_runtime_install() -> InstallJob:
    """Begin downloading and installing the runtime; return immediately."""
    global _task
    asset = current_asset()
    if asset is None:
        raise RuntimeInstallError(
            "No verified LibreOffice runtime is published for this platform."
        )
    if _task is not None and not _task.done() and _job is not None:
        return _job
    _remove_stale_staging(keep=partial_download_path(asset))
    job = InstallJob(
        phase="downloading",
        version=asset.version,
        bytes_done=0,
        bytes_total=asset.size,
        started_at=_now(),
    )
    _set_job(job)

    async def run() -> None:
        try:
            await _install(asset)
        except asyncio.CancelledError:
            # The user stopped the download; _install already removed staging.
            _set_job(None)
            logger.info("office_runtime_install_cancelled version={}", asset.version)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            _update(phase="failed", error=str(exc) or type(exc).__name__)
            logger.warning("office_runtime_install_failed error={}", exc)
        else:
            _set_job(None)
            logger.info("office_runtime_installed version={}", asset.version)

    _task = asyncio.create_task(run(), name="office-runtime-install")
    return job


def _remove_stale_staging(*, keep: Path | None = None) -> None:
    """Delete leftovers of installs the app quit in the middle of.

    Activation only prunes version directories, so an interrupted extraction
    would otherwise keep up to a gigabyte on disk forever. Partial downloads
    are kept only for the asset about to be installed (``keep``), which the
    download then resumes; those of other versions are removed.
    """
    home = runtime_home()
    if not home.is_dir():
        return
    for staging in home.glob(".staging-*"):
        shutil.rmtree(staging, ignore_errors=True)
    for partial in home.glob(".download-*.part"):
        if keep is None or partial != keep:
            partial.unlink(missing_ok=True)


def cancel_runtime_install() -> None:
    """Stop an install that is still downloading or verifying.

    Extraction and activation run in worker threads that cannot be
    interrupted safely, so a cancel that arrives then is refused.
    """
    job = _job
    if _task is None or _task.done() or job is None:
        return
    if job.phase not in {"downloading", "verifying"}:
        raise RuntimeInstallError("The renderer is already being installed.")
    _task.cancel()


def dismiss_install_error() -> None:
    if _job is not None and _job.phase == "failed":
        _set_job(None)


def uninstall_runtime() -> None:
    if _task is not None and not _task.done():
        raise RuntimeInstallError("The runtime is still being installed.")
    shutil.rmtree(runtime_home(), ignore_errors=True)


__all__ = [
    "InstallJob",
    "InstalledRuntime",
    "RuntimeInstallError",
    "RuntimeStatus",
    "cancel_runtime_install",
    "dismiss_install_error",
    "installed_runtime",
    "runtime_home",
    "runtime_status",
    "start_runtime_install",
    "uninstall_runtime",
]
