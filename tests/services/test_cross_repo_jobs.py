"""Lossless coalescing for cross-repo background resolution jobs."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.services.code_graph import cross_repo_jobs as jobs_module
from app.services.code_graph.cross_repo import CrossRepoResolveStats
from app.services.code_graph.cross_repo_jobs import CrossRepoResolveJobRegistry
from app.services.code_graph.cross_repo_lexical import TierBStats


@asynccontextmanager
async def _fake_session():
    yield object()


def _fake_factory():
    return _fake_session()


@pytest.mark.asyncio
async def test_request_during_resolve_runs_follow_up_pass(monkeypatch) -> None:
    registry = CrossRepoResolveJobRegistry()
    project_id = uuid4()
    first_workspace = uuid4()
    second_workspace = uuid4()
    first_pass_entered = asyncio.Event()
    release_first_pass = asyncio.Event()
    changed_seen: list[set | None] = []

    async def fake_resolve(db, *, project_id, changed_workspaces):
        changed_seen.append(changed_workspaces)
        if len(changed_seen) == 1:
            first_pass_entered.set()
            await release_first_pass.wait()
        return CrossRepoResolveStats()

    async def fake_tier_b(db, *, project_id):
        return TierBStats()

    monkeypatch.setattr(jobs_module, "resolve_project", fake_resolve)
    monkeypatch.setattr(jobs_module, "resolve_project_tier_b", fake_tier_b)

    first_job, started = await registry.start(
        project_id=project_id,
        db_factory=_fake_factory,
        changed_workspaces={first_workspace},
    )
    assert started
    await asyncio.wait_for(first_pass_entered.wait(), timeout=1)

    same_job, started = await registry.start(
        project_id=project_id,
        db_factory=_fake_factory,
        changed_workspaces={second_workspace},
    )
    assert not started
    assert same_job is first_job

    release_first_pass.set()
    for _ in range(100):
        if not registry.is_running(project_id):
            break
        await asyncio.sleep(0.01)

    assert not registry.is_running(project_id)
    assert changed_seen == [{first_workspace}, {second_workspace}]
