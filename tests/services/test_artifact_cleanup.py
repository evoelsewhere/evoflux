from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest

from app.models.chat import ChatSession
from app.services.artifact_cleanup import cleanup_generated_artifacts

pytestmark = pytest.mark.usefixtures("setup_db")


@pytest.mark.asyncio
async def test_cleanup_targets_orphaned_session_artifacts(tmp_path, monkeypatch):
    from app.core import db as core_db
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    old_session_id = str(uuid.uuid4())
    artifact_dir = tmp_path / "data" / "sessions" / old_session_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / ".todos.json").write_text("{}", encoding="utf-8")
    old_time = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    artifact_dir.touch()
    (artifact_dir / ".todos.json").touch()
    os.utime(artifact_dir, (old_time, old_time))
    os.utime(artifact_dir / ".todos.json", (old_time, old_time))

    async with core_db.async_session_factory() as session:
        result = await cleanup_generated_artifacts(
            session, older_than_days=7, dry_run=True
        )

    assert artifact_dir in [candidate.path for candidate in result.candidates]
    assert any(
        candidate.reason == "orphaned session artifacts"
        for candidate in result.candidates
    )


@pytest.mark.asyncio
async def test_cleanup_keeps_live_session_artifacts(tmp_path, monkeypatch):
    from app.core import db as core_db
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    live_id = uuid.uuid4()
    artifact_dir = tmp_path / "data" / "sessions" / str(live_id)
    artifact_dir.mkdir(parents=True)
    old_time = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(artifact_dir, (old_time, old_time))

    async with core_db.async_session_factory() as session:
        session.add(ChatSession(id=live_id, agent_name="lead"))
        await session.commit()
        result = await cleanup_generated_artifacts(
            session, older_than_days=7, dry_run=True
        )

    assert artifact_dir not in [candidate.path for candidate in result.candidates]
