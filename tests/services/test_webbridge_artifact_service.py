from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat import ChatSession, SessionMessage
from app.services.webbridge_artifact_service import (
    _apply_artifact_cleanup,
    _plan_expired_artifact_cleanup,
    cleanup_expired_artifacts,
    resolve_attachment_path,
)


def test_resolve_attachment_path_uses_canonical_app_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path))
    canonical = tmp_path / "historical-upload" / "uploads" / "image.png"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"png")
    value = {
        "filename": "image.png",
        "path": str(canonical),
        "workspace_path": str(canonical),
    }
    assert resolve_attachment_path("different-message-session", value) == canonical


def test_resolve_attachment_path_rejects_external_canonical_path(monkeypatch, tmp_path):
    from app.core.config import settings

    storage = tmp_path / "storage"
    external = tmp_path / "external" / "image.png"
    external.parent.mkdir(parents=True)
    external.write_bytes(b"png")
    monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(storage))
    with pytest.raises(ValueError, match="escapes"):
        resolve_attachment_path(
            "session",
            {"filename": "image.png", "path": str(external)},
        )


@pytest.mark.asyncio
async def test_cleanup_expired_artifacts_sweeps_unvisited_history(
    monkeypatch, tmp_path
):
    from app.core import db as db_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path))
    session = ChatSession(title="Artifact history")
    async with db_module.async_session_factory() as db:
        db.add(session)
        await db.flush()
        path = tmp_path / str(session.id) / "uploads" / "expired.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"expired")
        row = SessionMessage(
            session_id=session.id,
            role="user",
            content="Old capture",
            extra={
                "attachments": [
                    {
                        "filename": "expired.png",
                        "path": str(path),
                        "category": "image",
                        "webbridge_artifact": {
                            "expires_at": (
                                datetime.now(timezone.utc) - timedelta(days=1)
                            ).isoformat()
                        },
                    }
                ]
            },
        )
        db.add(row)
        await db.commit()
        cleaned = await cleanup_expired_artifacts(db)
        await db.refresh(row)
    assert cleaned == 1
    assert not path.exists()
    assert row.extra["attachments"][0]["deleted_at"]


@pytest.mark.asyncio
async def test_cleanup_preserves_concurrent_message_metadata(monkeypatch, tmp_path):
    from app.core import db as db_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path))
    session = ChatSession(title="Concurrent artifact metadata")
    async with db_module.async_session_factory() as db:
        db.add(session)
        await db.flush()
        row = SessionMessage(
            session_id=session.id,
            role="tool",
            content="capture",
            extra={
                "attachments": [
                    {
                        "filename": "expired.png",
                        "webbridge_artifact": {
                            "expires_at": (
                                datetime.now(timezone.utc) - timedelta(days=1)
                            ).isoformat()
                        },
                    }
                ],
                "original": True,
            },
        )
        db.add(row)
        await db.commit()
        message_id = row.id

    async with db_module.read_session_factory() as db:
        plan = await _plan_expired_artifact_cleanup(db)
    async with db_module.async_session_factory() as db:
        current = await db.get(SessionMessage, message_id)
        assert current is not None
        current.extra = {**(current.extra or {}), "concurrent": True}
        await db.commit()
    async with db_module.async_session_factory() as db:
        cleaned = await _apply_artifact_cleanup(db, plan)

    assert cleaned == 0
    async with db_module.async_session_factory() as db:
        current = await db.get(SessionMessage, message_id)
        assert current is not None
        assert current.extra and current.extra["concurrent"] is True
        cleaned = await cleanup_expired_artifacts(db)
        await db.refresh(current)
        assert current.extra["concurrent"] is True
        assert current.extra["attachments"][0]["deleted_at"]
    assert cleaned == 1


# ---------------------------------------------------------------------------
# The sweep must not scan every message's metadata, or run at startup
# ---------------------------------------------------------------------------


def test_candidate_query_asks_the_database_for_artifact_rows_only():
    """``extra IS NOT NULL`` matched ~every row (usage metadata), so the sweep
    fetched and JSON-decoded the whole history on each pass."""
    from app.services.webbridge_artifact_service import _candidate_rows_statement

    sql = str(
        _candidate_rows_statement().compile(compile_kwargs={"literal_binds": True})
    )

    assert "IS NOT NULL" not in sql.upper()
    assert "LIKE" in sql.upper()
    assert "webbridge_artifact" in sql


@pytest.mark.asyncio
async def test_only_rows_with_an_artifact_window_are_materialized(
    monkeypatch, tmp_path
):
    from app.core import db as db_module
    from app.core.config import settings
    from app.services.webbridge_artifact_service import _candidate_rows_statement

    monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path))
    session = ChatSession(title="Mostly usage metadata")
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    async with db_module.async_session_factory() as db:
        db.add(session)
        await db.flush()
        noise = [
            SessionMessage(
                session_id=session.id,
                role="assistant",
                content=f"reply {index}",
                extra={"usage": {"input": index, "output": 1}, "model": "m"},
            )
            for index in range(25)
        ]
        # An ordinary upload: attachments, but no retention window.
        upload = SessionMessage(
            session_id=session.id,
            role="user",
            content="upload",
            extra={"attachments": [{"filename": "a.png", "category": "image"}]},
        )
        capture = SessionMessage(
            session_id=session.id,
            role="tool",
            content="capture",
            extra={
                "attachments": [
                    {
                        "filename": "b.png",
                        "webbridge_artifact": {"expires_at": expired},
                    }
                ]
            },
        )
        db.add_all([*noise, upload, capture])
        await db.commit()
        capture_id = capture.id

    async with db_module.read_session_factory() as db:
        candidates = (await db.exec(_candidate_rows_statement())).all()
        plan = await _plan_expired_artifact_cleanup(db)

    assert [row[0] for row in candidates] == [capture_id]
    assert [item.message_id for item in plan] == [capture_id]


@pytest.mark.asyncio
async def test_cleanup_loop_waits_before_the_first_sweep(monkeypatch):
    """Startup is already busy; the first sweep must not join it."""
    import asyncio

    from app.services import webbridge_artifact_service as service

    events: list[tuple[str, float | None]] = []

    async def fake_sleep(seconds: float) -> None:
        events.append(("sleep", seconds))
        if len([e for e in events if e[0] == "sleep"]) >= 2:
            raise asyncio.CancelledError

    async def fake_plan(db, *, now=None):
        events.append(("sweep", None))
        return []

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_exc):
            return None

    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(service, "_plan_expired_artifact_cleanup", fake_plan)
    from app.core import db as db_module

    monkeypatch.setattr(db_module, "read_session_factory", lambda: _Session())

    with pytest.raises(asyncio.CancelledError):
        await service.run_artifact_cleanup_loop()

    assert events == [
        ("sleep", service._STARTUP_DELAY_SECONDS),
        ("sweep", None),
        ("sleep", service._CLEANUP_INTERVAL_SECONDS),
    ]
