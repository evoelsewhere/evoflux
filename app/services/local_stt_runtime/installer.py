"""Download and manage the optional local faster-whisper runtime and model."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from loguru import logger

from app.core.config import settings
from app.services.local_stt_runtime.manifest import (
    MODEL_ID,
    RUNTIME_ID,
    RuntimeAsset,
    current_assets,
    platform_key,
)

InstallPhase = Literal[
    "downloading_runtime",
    "downloading_model",
    "verifying",
    "extracting",
    "checking",
    "failed",
]
RuntimeState = Literal[
    "unavailable", "not_installed", "installing", "ready", "needs_repair", "failed"
]
_INSTALL_RECORD = "install.json"
_CHUNK = 1024 * 1024
_MAX_ENTRIES = 100_000
_MAX_EXTRACTED_BYTES = 8 * 1024 * 1024 * 1024


class LocalSttRuntimeError(RuntimeError):
    """The optional local speech runtime cannot be installed or used."""


@dataclass(frozen=True, slots=True)
class InstallJob:
    phase: InstallPhase
    runtime_version: str
    model_version: str
    bytes_done: int
    bytes_total: int
    started_at: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    available: bool
    state: RuntimeState
    platform: str | None
    model_id: str
    runtime_version: str | None
    model_version: str | None
    download_bytes: int | None
    install_bytes: int | None
    installed_runtime_version: str | None
    installed_model_version: str | None
    healthy: bool
    job: InstallJob | None


@dataclass(frozen=True, slots=True)
class InstalledRuntime:
    runtime_root: Path
    model_root: Path
    runtime_version: str
    model_version: str


_job: InstallJob | None = None
_task: asyncio.Task[None] | None = None
_lock = threading.Lock()
_health_failed = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def runtime_home() -> Path:
    return Path(settings.EVOFLUX_DATA_DIR) / "runtimes" / RUNTIME_ID


def _read_record() -> dict[str, Any] | None:
    try:
        record = json.loads((runtime_home() / _INSTALL_RECORD).read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("id") != RUNTIME_ID:
            return None
        return record
    except (OSError, ValueError, TypeError):
        return None


def installed_runtime() -> InstalledRuntime | None:
    record = _read_record()
    if record is None:
        return None
    runtime_version = str(record.get("runtime_version", ""))
    model_version = str(record.get("model_version", ""))
    home = runtime_home().resolve()
    runtime_root = home / "runtime" / runtime_version
    model_root = home / "model" / model_version
    try:
        runtime_root.resolve().relative_to(home)
        model_root.resolve().relative_to(home)
    except (OSError, ValueError):
        return None
    if not (runtime_root / "site-packages" / "faster_whisper").is_dir():
        return None
    if not (model_root / "model.bin").is_file() or not (model_root / "config.json").is_file():
        return None
    return InstalledRuntime(runtime_root, model_root, runtime_version, model_version)


def _set_job(job: InstallJob | None) -> None:
    global _job
    with _lock:
        _job = job


def _update(**changes: object) -> None:
    global _job
    with _lock:
        if _job is not None:
            _job = replace(_job, **changes)  # type: ignore[arg-type]


def _installed_size(assets: tuple[RuntimeAsset, RuntimeAsset]) -> int | None:
    sizes = [asset.installed_size for asset in assets]
    return sum(sizes) if all(size is not None for size in sizes) else None


def runtime_status() -> RuntimeStatus:
    global _health_failed
    assets = current_assets()
    installed = installed_runtime()
    job = _job
    state: RuntimeState
    if installed is not None and _health_failed:
        state = "needs_repair"
    elif assets is None:
        if installed is not None:
            state = "ready"
        elif _read_record() is not None:
            state = "needs_repair"
        else:
            state = "unavailable"
    elif job is not None:
        state = "failed" if job.phase == "failed" else "installing"
    elif installed is None and _read_record() is not None:
        state = "needs_repair"
    elif installed is None:
        state = "not_installed"
    else:
        state = "ready"
    return RuntimeStatus(
        available=assets is not None,
        state=state,
        platform=assets[0].platform if assets else platform_key(),
        model_id=MODEL_ID,
        runtime_version=assets[0].version if assets else None,
        model_version=assets[1].version if assets else None,
        download_bytes=sum(asset.size for asset in assets) if assets else None,
        install_bytes=_installed_size(assets) if assets else None,
        installed_runtime_version=installed.runtime_version if installed else None,
        installed_model_version=installed.model_version if installed else None,
        healthy=installed is not None and not _health_failed,
        job=job,
    )


def _partial_path(asset: RuntimeAsset) -> Path:
    return runtime_home() / f".download-{asset.kind}-{asset.sha256}.part"


def _hash_partial(path: Path, limit: int) -> tuple[Any, int]:
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


async def _download(asset: RuntimeAsset, destination: Path, *, progress_offset: int) -> str:
    digest, received = await asyncio.to_thread(_hash_partial, destination, asset.size)
    if destination.exists() and destination.stat().st_size != received:
        with destination.open("r+b") as handle:
            handle.truncate(received)
    _update(bytes_done=progress_offset + received)

    def write_chunk(chunk: bytes, handle: Any) -> None:
        nonlocal received
        received += len(chunk)
        if received > asset.size:
            raise LocalSttRuntimeError("The runtime download exceeded its pinned size.")
        digest.update(chunk)
        handle.write(chunk)
        _update(bytes_done=progress_offset + received)

    parsed = urlparse(asset.url)
    if parsed.scheme == "file":
        source = Path(url2pathname(unquote(parsed.path)))
        with source.open("rb") as reader, destination.open("ab") as writer:
            reader.seek(received)
            while chunk := await asyncio.to_thread(reader.read, _CHUNK):
                write_chunk(chunk, writer)
    elif received < asset.size:
        headers = {"Range": f"bytes={received}-"} if received else {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=120)) as client:
            async with client.stream("GET", asset.url, headers=headers) as response:
                if response.url.scheme != "https":
                    raise LocalSttRuntimeError("The runtime download redirected away from HTTPS.")
                if response.status_code == 200 and received:
                    digest, received = hashlib.sha256(), 0
                    with destination.open("wb"):
                        pass
                    _update(bytes_done=0)
                elif response.status_code not in {200, 206}:
                    raise LocalSttRuntimeError(
                        f"The runtime download failed with HTTP {response.status_code}."
                    )
                if response.status_code == 206 and received:
                    content_range = response.headers.get("content-range", "")
                    if not content_range.startswith(f"bytes {received}-"):
                        destination.unlink(missing_ok=True)
                        raise LocalSttRuntimeError("The runtime server returned an invalid resume range.")
                with destination.open("ab") as writer:
                    async for chunk in response.aiter_bytes():
                        write_chunk(chunk, writer)
    if received != asset.size:
        raise LocalSttRuntimeError(
            f"The downloaded {asset.kind} asset has an unexpected size."
        )
    return digest.hexdigest()


def _safe_zip_members(archive: zipfile.ZipFile, root: str) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    seen: set[str] = set()
    total = 0
    for item in archive.infolist():
        if len(members) >= _MAX_ENTRIES:
            raise LocalSttRuntimeError("The runtime archive has too many entries.")
        name = item.filename.replace("\\", "/")
        path = PurePosixPath(name)
        mode = item.external_attr >> 16
        if (
            path.is_absolute()
            or not path.parts
            or ":" in path.parts[0]
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.parts[0] != root
            or stat.S_ISLNK(mode)
            or (mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))
        ):
            raise LocalSttRuntimeError("The runtime archive contains an unsafe path or file type.")
        folded = path.as_posix().casefold()
        if folded in seen and not item.is_dir():
            raise LocalSttRuntimeError("The runtime archive contains a duplicate path.")
        seen.add(folded)
        total += item.file_size
        if total > _MAX_EXTRACTED_BYTES:
            raise LocalSttRuntimeError("The runtime archive expands beyond the allowed size.")
        members.append(item)
    if not members:
        raise LocalSttRuntimeError("The runtime archive is empty.")
    return members


def _extract_zip(archive_path: Path, destination: Path, root: str) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_zip_members(archive, root)
        target_root = destination.resolve()
        for item in members:
            relative = PurePosixPath(item.filename.replace("\\", "/"))
            output = destination.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.resolve().relative_to(target_root)
            if item.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            with archive.open(item) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target, _CHUNK)
            mode = item.external_attr >> 16
            if mode & 0o111:
                output.chmod(output.stat().st_mode | 0o111)


def _worker_env(runtime_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    key = next((name for name in env if name.upper() == "PYTHONPATH"), "PYTHONPATH")
    package_path = str(runtime_root / "site-packages")
    previous = env.get(key, "")
    env[key] = package_path + (os.pathsep + previous if previous else "")
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    return env


def _health_check(runtime_root: Path, model_root: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "app.services.local_stt_runtime.worker",
        "--health",
        str(model_root),
    ]
    try:
        result = subprocess.run(
            command,
            env=_worker_env(runtime_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalSttRuntimeError("The local speech model could not be checked.") from exc
    if result.returncode != 0:
        raise LocalSttRuntimeError("The local speech model failed its load check.")


def installed_runtime_for_use() -> InstalledRuntime:
    installed = installed_runtime()
    if installed is None:
        raise LocalSttRuntimeError("Download the local speech model in Settings → Voice input first.")
    return installed


def check_runtime() -> RuntimeStatus:
    global _health_failed
    installed = installed_runtime()
    if installed is None:
        return runtime_status()
    try:
        _health_check(installed.runtime_root, installed.model_root)
    except LocalSttRuntimeError:
        _health_failed = True
        logger.warning("local_stt_health_check_failed runtime_version={}", installed.runtime_version)
    else:
        _health_failed = False
    return runtime_status()


def _has_space(home: Path, assets: tuple[RuntimeAsset, RuntimeAsset]) -> bool:
    required_extract = _installed_size(assets)
    required = sum(asset.size for asset in assets)
    if required_extract is None:
        required_extract = required
    # Keep the old runtime active during staging, with modest archive overhead.
    required += required_extract + 512 * 1024 * 1024
    return shutil.disk_usage(home.parent if home.parent.exists() else home.anchor).free >= required


async def _install(assets: tuple[RuntimeAsset, RuntimeAsset]) -> None:
    global _health_failed
    home = runtime_home()
    home.mkdir(parents=True, exist_ok=True)
    if not _has_space(home, assets):
        raise LocalSttRuntimeError("There is not enough free disk space to install local speech recognition.")
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=home))
    staged_paths: dict[str, Path] = {}
    backups: dict[Path, Path] = {}
    destinations: list[Path] = []
    activated = False
    try:
        completed_bytes = 0
        for asset in assets:
            _update(
                phase="downloading_runtime" if asset.kind == "runtime" else "downloading_model",
                bytes_done=0,
                bytes_total=sum(item.size for item in assets),
            )
            archive = _partial_path(asset)
            digest = await _download(asset, archive, progress_offset=completed_bytes)
            _update(phase="verifying")
            if digest != asset.sha256:
                archive.unlink(missing_ok=True)
                raise LocalSttRuntimeError(f"The {asset.kind} download failed integrity verification.")
            _update(phase="extracting")
            extracted = stage / f"{asset.kind}-tree"
            extracted.mkdir()
            await asyncio.to_thread(_extract_zip, archive, extracted, asset.root.split("/", 1)[0])
            staged_paths[asset.kind] = extracted.joinpath(*PurePosixPath(asset.root).parts[1:])
            archive.unlink(missing_ok=True)
            completed_bytes += asset.size

        runtime_dest = home / "runtime" / assets[0].version
        model_dest = home / "model" / assets[1].version
        # Validate the candidate before replacing any active version. The
        # health check executes only the pinned, checksum-verified staged code.
        _update(phase="checking")
        await asyncio.to_thread(_health_check, staged_paths["runtime"], staged_paths["model"])
        for asset, staged, destination in (
            (assets[0], staged_paths["runtime"], runtime_dest),
            (assets[1], staged_paths["model"], model_dest),
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = home / f".backup-{asset.kind}-{uuid.uuid4().hex}"
                os.replace(destination, backup)
                backups[destination] = backup
            os.replace(staged, destination)
            destinations.append(destination)
        record = {
            "id": RUNTIME_ID,
            "platform": assets[0].platform,
            "runtime_version": assets[0].version,
            "runtime_sha256": assets[0].sha256,
            "model_id": MODEL_ID,
            "model_version": assets[1].version,
            "model_sha256": assets[1].sha256,
            "installed_at": _now(),
        }
        temporary = home / f".{_INSTALL_RECORD}.tmp"
        temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(temporary, home / _INSTALL_RECORD)
        activated = True
        _health_failed = False
        _prune_versions(home, keep_runtime=assets[0].version, keep_model=assets[1].version)
    except Exception:
        for destination in reversed(destinations):
            shutil.rmtree(destination, ignore_errors=True)
        for destination, backup in backups.items():
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if backup.exists():
                os.replace(backup, destination)
        raise
    finally:
        if activated:
            for backup in backups.values():
                shutil.rmtree(backup, ignore_errors=True)
        else:
            for backup in backups.values():
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)


def _prune_versions(home: Path, *, keep_runtime: str, keep_model: str) -> None:
    for parent, keep in ((home / "runtime", keep_runtime), (home / "model", keep_model)):
        if parent.is_dir():
            for child in parent.iterdir():
                if child.is_dir() and child.name != keep:
                    shutil.rmtree(child, ignore_errors=True)


def start_install() -> InstallJob:
    global _task
    assets = current_assets()
    if assets is None:
        raise LocalSttRuntimeError("No verified local STT assets are published for this platform.")
    if _task is not None and not _task.done() and _job is not None:
        return _job
    for stale in runtime_home().glob(".staging-*") if runtime_home().exists() else ():
        shutil.rmtree(stale, ignore_errors=True)
    _set_job(
        InstallJob(
            phase="downloading_runtime",
            runtime_version=assets[0].version,
            model_version=assets[1].version,
            bytes_done=0,
            bytes_total=sum(asset.size for asset in assets),
            started_at=_now(),
        )
    )

    async def run() -> None:
        try:
            await _install(assets)
        except asyncio.CancelledError:
            for asset in assets:
                _partial_path(asset).unlink(missing_ok=True)
            _set_job(None)
            logger.info("local_stt_install_cancelled runtime_version={}", assets[0].version)
        except Exception as exc:  # noqa: BLE001 - message is safe, clip-free lifecycle metadata
            safe_error = (
                str(exc)
                if isinstance(exc, LocalSttRuntimeError)
                else "Installation failed. Check the network and available disk space, then retry."
            )
            _update(phase="failed", error=safe_error)
            logger.warning("local_stt_install_failed error={}", type(exc).__name__)
        else:
            _set_job(None)
            logger.info("local_stt_installed model_version={}", assets[1].version)

    _task = asyncio.create_task(run(), name="local-stt-install")
    return _job  # type: ignore[return-value]


def cancel_install() -> None:
    if _task is None or _task.done() or _job is None:
        return
    if _job.phase not in {"downloading_runtime", "downloading_model", "verifying"}:
        raise LocalSttRuntimeError("The local speech model is already being installed.")
    _task.cancel()


def dismiss_error() -> None:
    if _job is not None and _job.phase == "failed":
        _set_job(None)


def uninstall_runtime() -> None:
    if _task is not None and not _task.done():
        raise LocalSttRuntimeError("Local speech assets are still being installed.")
    home = runtime_home()
    if home.exists():
        shutil.rmtree(home)


__all__ = [
    "InstallJob",
    "InstalledRuntime",
    "LocalSttRuntimeError",
    "RuntimeStatus",
    "cancel_install",
    "check_runtime",
    "dismiss_error",
    "installed_runtime_for_use",
    "runtime_home",
    "runtime_status",
    "start_install",
    "uninstall_runtime",
]
