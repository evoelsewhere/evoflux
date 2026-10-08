"""Bounded asynchronous client for the persistent local STT worker."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from pathlib import Path

from app.services.local_stt_runtime.installer import installed_runtime_for_use

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
IDLE_TIMEOUT_SECONDS = 300


class LocalWorkerError(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class LocalWhisperWorker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._runtime_key: tuple[str, str] | None = None
        self._idle_task: asyncio.Task[None] | None = None

    async def transcribe(
        self,
        *,
        audio: bytes,
        filename: str,
        content_type: str,
        language: str | None,
        timeout_seconds: float,
    ) -> str:
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise LocalWorkerError("invalid_request")
        installed = installed_runtime_for_use()
        runtime_key = (installed.runtime_version, installed.model_version)
        async with self._lock:
            self._cancel_idle_timer()
            await self._ensure_process(installed, runtime_key)
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise LocalWorkerError("runtime_unavailable")
            metadata = {
                "audio_bytes": len(audio),
                "filename": Path(filename).name[:255],
                "content_type": content_type[:128],
                "language": language[:32] if language else None,
            }
            header = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
            try:
                process.stdin.write(struct.pack(">I", len(header)) + header + audio)
                await asyncio.wait_for(process.stdin.drain(), timeout=min(timeout_seconds, 15.0))
                response_size = struct.unpack(
                    ">I", await asyncio.wait_for(process.stdout.readexactly(4), timeout=timeout_seconds)
                )[0]
                if not 1 <= response_size <= MAX_RESPONSE_BYTES:
                    raise LocalWorkerError("invalid_response")
                payload = json.loads(
                    await asyncio.wait_for(process.stdout.readexactly(response_size), timeout=timeout_seconds)
                )
            except asyncio.TimeoutError as exc:
                await self._stop_process()
                raise LocalWorkerError("timeout") from exc
            except (asyncio.IncompleteReadError, BrokenPipeError, ConnectionError, ValueError) as exc:
                await self._stop_process()
                raise LocalWorkerError("worker_crashed") from exc
            except asyncio.CancelledError:
                await self._stop_process()
                raise
            if not isinstance(payload, dict):
                await self._stop_process()
                raise LocalWorkerError("invalid_response")
            if payload.get("error"):
                category = str(payload.get("error"))[:64]
                if category == "model_load_failed":
                    await self._stop_process()
                raise LocalWorkerError(category)
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise LocalWorkerError("invalid_response")
            self._schedule_idle_stop()
            return text.strip()

    async def close(self) -> None:
        async with self._lock:
            self._cancel_idle_timer()
            await self._stop_process()

    async def _ensure_process(self, installed, runtime_key: tuple[str, str]) -> None:
        if self._process is not None and self._process.returncode is None and self._runtime_key == runtime_key:
            return
        await self._stop_process()
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["PYTHONPATH"] = str(installed.runtime_root / "site-packages") + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.services.local_stt_runtime.worker",
                "--serve",
                str(installed.model_root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
        except OSError as exc:
            raise LocalWorkerError("runtime_unavailable") from exc
        self._runtime_key = runtime_key

    async def _stop_process(self) -> None:
        process, self._process = self._process, None
        self._runtime_key = None
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if process.stdin is not None:
            process.stdin.close()

    def _cancel_idle_timer(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _schedule_idle_stop(self) -> None:
        async def stop_when_idle() -> None:
            try:
                await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
                async with self._lock:
                    await self._stop_process()
            except asyncio.CancelledError:
                return

        self._idle_task = asyncio.create_task(stop_when_idle(), name="local-stt-idle-shutdown")


worker = LocalWhisperWorker()


__all__ = ["LocalWorkerError", "LocalWhisperWorker", "worker"]
