"""Tests for _kick_auto_index — background index build on session resolve."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.routes.team.chat import _kick_auto_index


class _FakeJobs:
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.started: list[tuple] = []

    def is_running(self, workspace_id) -> bool:
        return self.running

    async def start(self, *, workspace_id, root_path, languages, full):
        self.started.append((workspace_id, root_path, languages, full))
        return object(), True


class _FakeCrossRepoJobs:
    def __init__(self) -> None:
        self.started: list[tuple] = []

    async def start(self, *, project_id, wait_for_workspaces):
        self.started.append((project_id, wait_for_workspaces))
        return object(), True


@pytest.fixture
def fake_jobs(monkeypatch):
    from app.services.code_graph import jobs as jobs_mod

    fake = _FakeJobs()
    monkeypatch.setattr(jobs_mod, "index_jobs", fake)
    return fake


def _patch_svc(monkeypatch, *, workspace_id, files: int):
    from app.services import code_graph_service as svc

    async def _resolve(db, *, path):
        return workspace_id

    async def _status(db, *, workspace_id):
        return {"files": files, "nodes": 0, "edges": 0}

    monkeypatch.setattr(svc, "resolve_workspace_id", _resolve)
    monkeypatch.setattr(svc, "get_index_status", _status)


@pytest.mark.asyncio
async def test_starts_index_for_unindexed_workspace(monkeypatch, fake_jobs):
    ws_id = uuid4()
    _patch_svc(monkeypatch, workspace_id=ws_id, files=0)

    await _kick_auto_index(None, ["/repo/a"])

    assert fake_jobs.started == [(ws_id, "/repo/a", None, False)]


@pytest.mark.asyncio
async def test_skips_already_indexed_workspace(monkeypatch, fake_jobs):
    _patch_svc(monkeypatch, workspace_id=uuid4(), files=42)

    await _kick_auto_index(None, ["/repo/a"])

    assert fake_jobs.started == []


@pytest.mark.asyncio
async def test_skips_unregistered_workspace(monkeypatch, fake_jobs):
    from app.services import code_graph_service as svc

    async def _resolve(db, *, path):
        return None

    monkeypatch.setattr(svc, "resolve_workspace_id", _resolve)

    await _kick_auto_index(None, ["/repo/a"])

    assert fake_jobs.started == []


@pytest.mark.asyncio
async def test_skips_when_job_already_running(monkeypatch, fake_jobs):
    fake_jobs.running = True
    _patch_svc(monkeypatch, workspace_id=uuid4(), files=0)

    await _kick_auto_index(None, ["/repo/a"])

    assert fake_jobs.started == []


@pytest.mark.asyncio
async def test_disabled_by_setting(monkeypatch, fake_jobs):
    _patch_svc(monkeypatch, workspace_id=uuid4(), files=0)

    from app.core import runtime_settings as rs

    settings = rs.load_runtime_settings()
    settings.code_graph.auto_index_enabled = False
    monkeypatch.setattr(rs, "load_runtime_settings", lambda: settings)

    await _kick_auto_index(None, ["/repo/a"])

    assert fake_jobs.started == []


@pytest.mark.asyncio
async def test_dedupes_paths_and_never_raises(monkeypatch, fake_jobs):
    ws_id = uuid4()
    _patch_svc(monkeypatch, workspace_id=ws_id, files=0)

    await _kick_auto_index(None, ["/repo/a", "/repo/a"])
    assert len(fake_jobs.started) == 1

    # Failures are swallowed (best-effort) — no exception escapes.
    from app.services import code_graph_service as svc

    async def _boom(db, *, path):
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "resolve_workspace_id", _boom)
    await _kick_auto_index(None, ["/repo/b"])  # must not raise


@pytest.mark.asyncio
async def test_project_auto_index_chains_cross_repo_resolution(monkeypatch, fake_jobs):
    from app.services import code_graph_service as svc
    from app.services.code_graph import cross_repo_jobs as cross_jobs_module

    project_id = uuid4()
    workspace_ids = {"/repo/a": uuid4(), "/repo/b": uuid4()}
    cross_jobs = _FakeCrossRepoJobs()

    async def _resolve(db, *, path):
        return workspace_ids[path]

    async def _status(db, *, workspace_id):
        return {"files": 0, "nodes": 0, "edges": 0}

    monkeypatch.setattr(svc, "resolve_workspace_id", _resolve)
    monkeypatch.setattr(svc, "get_index_status", _status)
    monkeypatch.setattr(cross_jobs_module, "cross_repo_jobs", cross_jobs)

    await _kick_auto_index(None, ["/repo/a", "/repo/b"], project_id=project_id)

    assert len(fake_jobs.started) == 2
    assert cross_jobs.started == [(project_id, list(workspace_ids.values()))]


@pytest.mark.asyncio
async def test_project_rebuilds_index_that_predates_membership(monkeypatch, fake_jobs):
    from app.services import code_graph_service as svc
    from app.services.code_graph import cross_repo_jobs as cross_jobs_module

    project_id = uuid4()
    workspace_ids = {"/repo/a": uuid4(), "/repo/b": uuid4()}
    cross_jobs = _FakeCrossRepoJobs()

    async def _resolve(db, *, path):
        return workspace_ids[path]

    async def _status(db, *, workspace_id):
        return {"files": 4, "nodes": 10, "edges": 5}

    async def _needs_bootstrap(db, *, project_id, workspace_id):
        return True

    monkeypatch.setattr(svc, "resolve_workspace_id", _resolve)
    monkeypatch.setattr(svc, "get_index_status", _status)
    monkeypatch.setattr(svc, "requires_project_graph_bootstrap", _needs_bootstrap)
    monkeypatch.setattr(cross_jobs_module, "cross_repo_jobs", cross_jobs)

    await _kick_auto_index(None, ["/repo/a", "/repo/b"], project_id=project_id)

    assert len(fake_jobs.started) == 2
    assert all(full is True for _, _, _, full in fake_jobs.started)
    assert len(cross_jobs.started) == 1
