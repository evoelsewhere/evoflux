"""Concurrency and metadata regressions for the automatic code-graph watcher."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.services.code_graph.watcher import CodeGraphWatcher, _is_graph_metadata
from app.services.code_graph_service import ReindexStats


@asynccontextmanager
async def _fake_session():
    yield object()


def _fake_factory():
    return _fake_session()


def test_graph_metadata_detection_covers_resolution_inputs() -> None:
    assert _is_graph_metadata("tsconfig.json")
    assert _is_graph_metadata("packages/shared/package.json")
    assert _is_graph_metadata("src/App.csproj")
    assert _is_graph_metadata(".gitignore")
    assert not _is_graph_metadata("README.md")


@pytest.mark.asyncio
async def test_metadata_event_requests_full_reindex() -> None:
    watcher = CodeGraphWatcher(db_factory=_fake_factory)
    watcher._extensions = {".py"}
    watcher._reindex_debounce_ms = 60_000

    await watcher._on_change("/repo", [{"type": "modified", "path": "tsconfig.json"}])

    assert "/repo" in watcher._full_reindex_pending
    task = watcher._debounce_tasks.pop("/repo")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_explicit_flush_runs_while_watcher_is_paused(
    monkeypatch, tmp_path
) -> None:
    watcher = CodeGraphWatcher(db_factory=_fake_factory)
    workspace = str(tmp_path.resolve())
    watcher._pause_count = 1
    watcher._dirty_workspaces.add(workspace)
    calls: list[str] = []

    async def record_reindex(path: str) -> None:
        calls.append(path)

    monkeypatch.setattr(watcher, "_reindex", record_reindex)

    await watcher.flush_incremental(workspace)

    assert watcher.is_paused
    assert calls == [workspace]
    assert workspace not in watcher._dirty_workspaces


@pytest.mark.asyncio
async def test_explicit_flush_waits_for_in_flight_reindex(
    monkeypatch, tmp_path
) -> None:
    watcher = CodeGraphWatcher(db_factory=_fake_factory)
    workspace = str(tmp_path.resolve())
    lock = watcher._reindex_locks.setdefault(workspace, asyncio.Lock())
    await lock.acquire()

    async def mark_follow_up(path: str) -> None:
        assert path == workspace
        watcher._reindex_pending.add(path)

    monkeypatch.setattr(watcher, "_reindex", mark_follow_up)
    flush = asyncio.create_task(watcher.flush_incremental(workspace))
    await asyncio.sleep(0)
    assert not flush.done()

    lock.release()
    await asyncio.wait_for(flush, timeout=1)


@pytest.mark.asyncio
async def test_new_save_does_not_cancel_in_flight_reindex(monkeypatch) -> None:
    watcher = CodeGraphWatcher(db_factory=_fake_factory)
    watcher._extensions = {".py"}
    watcher._reindex_debounce_ms = 0
    entered = asyncio.Event()
    release = asyncio.Event()
    active_tasks: list[asyncio.Task] = []

    async def blocking_reindex(workspace: str) -> None:
        task = asyncio.current_task()
        assert task is not None
        active_tasks.append(task)
        entered.set()
        await release.wait()

    monkeypatch.setattr(watcher, "_reindex", blocking_reindex)
    event = [{"type": "modified", "path": "main.py"}]
    await watcher._on_change("/repo", event)
    await asyncio.wait_for(entered.wait(), timeout=1)

    first = active_tasks[0]
    await watcher._on_change("/repo", event)
    await asyncio.sleep(0)
    assert not first.cancelling()

    release.set()
    await asyncio.sleep(0.01)
    pending = list(watcher._debounce_tasks.values())
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_event_during_background_index_is_retried(monkeypatch) -> None:
    from app.services.code_graph import jobs as jobs_module
    from app.services.code_graph import watcher as watcher_module

    watcher = CodeGraphWatcher(db_factory=_fake_factory)
    workspace_id = uuid4()
    job_running = True
    reindexed = asyncio.Event()

    class _Jobs:
        def is_running(self, candidate) -> bool:
            assert candidate == workspace_id
            return job_running

    async def resolve_workspace_id(db, *, path):
        return workspace_id

    async def reindex_workspace(db, **kwargs):
        reindexed.set()
        return ReindexStats(0, 0, 0, 0, [])

    monkeypatch.setattr(jobs_module, "index_jobs", _Jobs())
    monkeypatch.setattr(watcher_module, "resolve_workspace_id", resolve_workspace_id)
    monkeypatch.setattr(watcher_module, "reindex_workspace", reindex_workspace)

    await watcher._reindex("/repo")
    assert not reindexed.is_set()

    job_running = False
    await asyncio.wait_for(reindexed.wait(), timeout=1)
