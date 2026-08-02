"""Request/response bridge to the EvoFlux Desktop presentation renderer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

_CHUNK_CHARS = 256_000


class DesktopPresentationRendererUnavailable(RuntimeError):
    """Raised when a task has no connected EvoFlux Desktop WebView renderer."""


@dataclass
class _Connection:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    response_chunks: dict[str, dict[int, str]] = field(default_factory=dict)
    response_chunk_totals: dict[str, int] = field(default_factory=dict)
    ready: bool = False

    def fail_pending(self, message: str) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(DesktopPresentationRendererUnavailable(message))
        self.pending.clear()
        self.response_chunks.clear()
        self.response_chunk_totals.clear()


class DesktopPresentationBridge:
    """Routes HTML slide render jobs to the task's desktop WebView."""

    def __init__(self) -> None:
        self._connections: dict[str, _Connection] = {}

    def is_connected(self, session_id: str) -> bool:
        connection = self._connections.get(session_id)
        return bool(connection and connection.ready)

    async def attach(self, session_id: str, websocket: WebSocket) -> None:
        connection = _Connection(websocket)
        previous = self._connections.get(session_id)
        if previous is not None:
            previous.fail_pending("Desktop presentation renderer reconnected")
        self._connections[session_id] = connection
        logger.info("desktop_presentation_renderer_connected session_id={}", session_id)

        try:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "ready":
                    connection.ready = True
                    logger.info(
                        "desktop_presentation_renderer_ready session_id={}",
                        session_id,
                    )
                    continue
                if message.get("type") == "response_chunk":
                    message = self._accept_response_chunk(connection, message)
                    if message is None:
                        continue
                request_id = message.get("id")
                if not isinstance(request_id, str):
                    continue
                future = connection.pending.get(request_id)
                if future is None or future.done():
                    continue
                if message.get("ok") is True:
                    future.set_result(message.get("result"))
                else:
                    error = message.get("error")
                    future.set_exception(
                        RuntimeError(
                            error
                            if isinstance(error, str)
                            else "Desktop presentation render failed"
                        )
                    )
        except WebSocketDisconnect:
            pass
        finally:
            if self._connections.get(session_id) is connection:
                self._connections.pop(session_id, None)
            connection.fail_pending("Desktop presentation renderer disconnected")
            logger.info(
                "desktop_presentation_renderer_disconnected session_id={}",
                session_id,
            )

    async def render(
        self,
        session_id: str,
        *,
        document: str,
        inspection_script: str,
        inspection_params: dict[str, Any],
        timeout: float = 90.0,
    ) -> Any:
        connection = self._connections.get(session_id)
        if connection is None or not connection.ready:
            raise DesktopPresentationRendererUnavailable(
                "PPTX rendering requires an active EvoFlux Desktop task"
            )

        request_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        connection.pending[request_id] = future
        try:
            async with connection.send_lock:
                await self._send_request(
                    connection.websocket,
                    {
                        "id": request_id,
                        "action": "render_slide",
                        "params": {
                            "document": document,
                            "inspectionScript": inspection_script,
                            "inspectionParams": inspection_params,
                        },
                    },
                )
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError("Desktop presentation render timed out") from exc
        finally:
            connection.pending.pop(request_id, None)
            connection.response_chunks.pop(request_id, None)
            connection.response_chunk_totals.pop(request_id, None)

    @staticmethod
    async def _send_request(websocket: WebSocket, message: dict[str, Any]) -> None:
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if len(raw) <= _CHUNK_CHARS:
            await websocket.send_text(raw)
            return
        chunks = [
            raw[index : index + _CHUNK_CHARS]
            for index in range(0, len(raw), _CHUNK_CHARS)
        ]
        request_id = str(message["id"])
        for index, chunk in enumerate(chunks):
            await websocket.send_json(
                {
                    "type": "request_chunk",
                    "id": request_id,
                    "index": index,
                    "total": len(chunks),
                    "data": chunk,
                }
            )

    @staticmethod
    def _accept_response_chunk(
        connection: _Connection, message: dict[str, Any]
    ) -> dict[str, Any] | None:
        request_id = message.get("id")
        index = message.get("index")
        total = message.get("total")
        data = message.get("data")
        if (
            not isinstance(request_id, str)
            or not isinstance(index, int)
            or not isinstance(total, int)
            or not isinstance(data, str)
            or total < 1
            or total > 4096
            or index < 0
            or index >= total
        ):
            raise ValueError("Invalid desktop presentation response chunk")
        expected = connection.response_chunk_totals.setdefault(request_id, total)
        if expected != total:
            raise ValueError("Desktop presentation response chunk count changed")
        chunks = connection.response_chunks.setdefault(request_id, {})
        chunks[index] = data
        if len(chunks) != total:
            return None
        raw = "".join(chunks[position] for position in range(total))
        connection.response_chunks.pop(request_id, None)
        connection.response_chunk_totals.pop(request_id, None)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Invalid desktop presentation response")
        return parsed


desktop_presentation_bridge = DesktopPresentationBridge()
