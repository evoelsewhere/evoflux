"""Small JSON-RPC 2.0 client for the ``imsg rpc`` stdio protocol.

The protocol is line-delimited JSON on stdin/stdout. This client deliberately
keeps provider details behind a narrow request surface: it never opens a TCP
socket, logs payloads, or treats a notification as a response.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import os
import json
from collections.abc import Mapping
from typing import Any

_DEFAULT_COMMAND = ("imsg", "rpc")
_DEFAULT_TIMEOUT_SECONDS = 30.0


class IMessageRpcError(Exception):
    """A provider-level JSON-RPC error."""

    def __init__(self, *, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"imsg RPC error {code}: {message}")


class IMessageRpcProtocolError(Exception):
    """The child emitted malformed or otherwise unusable JSON-RPC data."""


class IMessageRpcClient:
    """Long-lived, serialized JSON-RPC client for one ``imsg rpc`` child."""

    def __init__(
        self,
        *,
        command: tuple[str, ...] = _DEFAULT_COMMAND,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._command = command
        self._timeout = timeout
        self._env = {**os.environ, **env} if env is not None else None
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._request_ids = itertools.count(1)
        self._closed = False

    @property
    def running(self) -> bool:
        """Whether the child process is currently available for requests."""
        return self._process is not None and self._process.returncode is None

    async def start(self) -> dict[str, Any]:
        """Start the child and return the provider's readiness snapshot."""
        if self.running:
            return await self.request("status")
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self._closed = False
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
        except OSError as exc:
            self._process = None
            raise IMessageRpcProtocolError(
                f"Unable to start imsg provider ({type(exc).__name__})."
            ) from exc
        assert self._process.stdout is not None
        self._reader_task = asyncio.create_task(self._read_responses())
        return await self.request("initialize", params={"protocol_version": 1})

    async def stop(self) -> None:
        """Close stdin and await the child, cancelling outstanding requests."""
        self._closed = True
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
            with contextlib.suppress(BrokenPipeError):
                await process.stdin.wait_closed()
        try:
            await asyncio.wait_for(process.wait(), timeout=self._timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        finally:
            self._fail_pending("imsg provider stopped")
            if self._reader_task is not None:
                self._reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader_task
                self._reader_task = None

    async def request(
        self,
        method: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one request and await its matching JSON-RPC response."""
        process = self._process
        if self._closed or process is None or process.stdin is None:
            raise IMessageRpcProtocolError("imsg provider is not running")
        request_id = str(next(self._request_ids))
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[request_id] = future
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = dict(params)
        try:
            async with self._write_lock:
                process.stdin.write(
                    (json.dumps(payload, separators=(",", ":")) + "\n").encode()
                )
                await process.stdin.drain()
            response = await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise IMessageRpcProtocolError(f"imsg request timed out: {method}") from exc
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            error = response["error"]
            if not isinstance(error, dict):
                raise IMessageRpcProtocolError("imsg returned an invalid error object")
            raise IMessageRpcError(
                code=int(error.get("code", -32603)),
                message=str(error.get("message", "provider error")),
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise IMessageRpcProtocolError("imsg returned a non-object result")
        return result

    async def _read_responses(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            async for line in process.stdout:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._fail_pending("imsg returned malformed JSON")
                    raise IMessageRpcProtocolError(
                        "imsg returned malformed JSON"
                    ) from exc
                if not isinstance(record, dict):
                    continue
                response_id = record.get("id")
                if response_id is None:
                    continue
                future = self._pending.get(str(response_id))
                if future is not None and not future.done():
                    future.set_result(record)
        except (asyncio.CancelledError, IMessageRpcProtocolError):
            raise
        except Exception:
            self._fail_pending("imsg provider stream closed")

    def _fail_pending(self, message: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(IMessageRpcProtocolError(message))
