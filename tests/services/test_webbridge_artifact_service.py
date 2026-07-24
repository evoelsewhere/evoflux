from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat import ChatSession, SessionMessage
from app.services.webbridge_artifact_service import (
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
async def test_cleanup_expired_artifacts_sweeps_unvisited_history(monkeypatch, tmp_path):
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
