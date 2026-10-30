"""``EVOFLUX_TSNET_TARGET_PORT`` points the tailnet helper at the gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services import remote_use_service
from app.services.remote_use_service import _EmbeddedTailnetManager


class _FakeProcess:
    pid = 4242
    returncode = None

    def __init__(self) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(b'EVOFLUX_TAILNET_HANDSHAKE {"port": 40123}\n')
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()

    def kill(self) -> None:
        self.returncode = -9

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


async def _start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend_port: int
) -> list[str]:
    binary = tmp_path / "evoflux-tailnet"
    binary.write_text("")
    monkeypatch.setattr(
        remote_use_service, "embedded_tailnet_binary", lambda: str(binary)
    )
    monkeypatch.setattr(remote_use_service.settings, "EVOFLUX_STATE_DIR", str(tmp_path))
    spawned = AsyncMock(return_value=_FakeProcess())
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawned)
    manager = _EmbeddedTailnetManager()
    try:
        await manager.ensure_started(backend_port)
    finally:
        if manager._stderr_task is not None:
            manager._stderr_task.cancel()
    return [str(a) for a in spawned.await_args.args]


def _target(args: list[str]) -> str:
    return args[args.index("--target") + 1]


@pytest.mark.asyncio
async def test_tsnet_target_port_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVOFLUX_TSNET_TARGET_PORT", "51515")
    args = await _start(monkeypatch, tmp_path, 8765)
    assert _target(args) == "http://127.0.0.1:51515"


@pytest.mark.asyncio
async def test_tsnet_target_defaults_to_backend_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("EVOFLUX_TSNET_TARGET_PORT", raising=False)
    args = await _start(monkeypatch, tmp_path, 8765)
    assert _target(args) == "http://127.0.0.1:8765"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "abc", "0", "70000", "-1"])
async def test_invalid_tsnet_target_port_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad: str
) -> None:
    monkeypatch.setenv("EVOFLUX_TSNET_TARGET_PORT", bad)
    args = await _start(monkeypatch, tmp_path, 8765)
    assert _target(args) == "http://127.0.0.1:8765"
