from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from app.services.code_index.jobs import ProjectIndexJobCoordinator
from app.services.code_index.project import IndexProgress, RepositoryIndex


class _ControlledIndex:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def update(self, *, full: bool, progress: Any) -> None:
        assert full is True
        progress(IndexProgress("transform", 0.4, "Parsing source components"))
        self.started.set()
        await self.release.wait()
        progress(IndexProgress("ready", 1.0, "Repository target synchronized"))
        self.finished.set()


@pytest.mark.asyncio
async def test_project_index_jobs_report_progress_and_deduplicate_triggers() -> None:
    coordinator = ProjectIndexJobCoordinator()
    controlled = _ControlledIndex()
    repositories = (("api", cast(RepositoryIndex, controlled)),)

    started = coordinator.start("project-1", repositories, full=True)
    await controlled.started.wait()

    assert started.indexing is True
    assert started.already_running == 0
    assert coordinator.snapshot("project-1")["api"].progress == 0.4
    assert coordinator.snapshot("project-1")["api"].indexing is True

    duplicate = coordinator.start("project-1", repositories, full=True)
    assert duplicate.already_running == 1

    controlled.release.set()
    await controlled.finished.wait()

    final = coordinator.snapshot("project-1")["api"]
    assert final.indexing is False
    assert final.phase == "ready"
    assert final.progress == 1.0
