"""Tests for the code-graph background index job registry."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid7

import pytest

from app.services.code_graph.jobs import IndexJobRegistry


@asynccontextmanager
async def _fake_session():
    yield object()


def _fake_factory():
    return _fake_session()


@pytest.mark.asyncio
async def test_start_runs_and_marks_done(monkeypatch):
    reg = IndexJobRegistry()
    seen: dict[str, object] = {}

    async def fake_reindex(db, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(
        "app.services.code_graph.jobs.svc.reindex_workspace", fake_reindex
    )

    wid = uuid7()
    job, started = await reg.start(
        workspace_id=wid,
        root_path="/tmp/ws",
        languages=None,
        full=True,
        db_factory=_fake_factory,
    )
    assert started is True

    for _ in range(200):
        if not reg.is_running(wid):
            break
        await asyncio.sleep(0.01)

    snap = reg.snapshot(wid)
    assert snap is not None
    assert snap.status == "done"
    assert snap.error is None
    # full=True maps to incremental=False.
    assert seen["incremental"] is False
    assert seen["root_path"] == "/tmp/ws"


@pytest.mark.asyncio
async def test_second_start_reports_already_running(monkeypatch):
    reg = IndexJobRegistry()
    release = asyncio.Event()

    async def blocking_reindex(db, **kwargs):
        await release.wait()

    monkeypatch.setattr(
        "app.services.code_graph.jobs.svc.reindex_workspace", blocking_reindex
    )

    wid = uuid7()
    job1, started1 = await reg.start(
        workspace_id=wid,
        root_path="/tmp/ws",
        languages=None,
        full=False,
        db_factory=_fake_factory,
    )
    assert started1 is True
    assert reg.is_running(wid)

    job2, started2 = await reg.start(
        workspace_id=wid,
        root_path="/tmp/ws",
        languages=None,
        full=False,
        db_factory=_fake_factory,
    )
    assert started2 is False
    assert job2 is job1

    release.set()
    for _ in range(200):
        if not reg.is_running(wid):
            break
        await asyncio.sleep(0.01)
    snap = reg.snapshot(wid)
    assert snap is not None
    assert snap.status == "done"


@pytest.mark.asyncio
async def test_failure_is_recorded(monkeypatch):
    reg = IndexJobRegistry()

    async def boom(db, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("app.services.code_graph.jobs.svc.reindex_workspace", boom)

    wid = uuid7()
    await reg.start(
        workspace_id=wid,
        root_path="/tmp/ws",
        languages=None,
        full=False,
        db_factory=_fake_factory,
    )
    for _ in range(200):
        if not reg.is_running(wid):
            break
        await asyncio.sleep(0.01)
    snap = reg.snapshot(wid)
    assert snap is not None
    assert snap.status == "error"
    assert snap.error == "kaboom"
