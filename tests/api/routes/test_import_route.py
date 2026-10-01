from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import get_session
from app.api.routes.import_route import router
from app.services.import_service import get_bundle, remove_bundle, store_bundle
from app.services.importers.base import ImportBundle, ImportItem


@pytest.fixture
async def import_client():
    app = FastAPI()
    app.include_router(router, prefix="/api/import")

    async def test_session():
        from app.core import db

        async with db.async_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_bulk_action_validates_every_index_before_mutating(import_client):
    bundle = ImportBundle(
        source="generic",
        detected_format="generic",
        items=[
            ImportItem(
                "session",
                "generic",
                "one",
                {"title": "One"},
                "One",
                conflicts=["exists"],
                action="skip",
            ),
            ImportItem(
                "session",
                "generic",
                "two",
                {"title": "Two"},
                "Two",
                conflicts=["exists"],
                action="skip",
            ),
        ],
    )
    store_bundle("bulk-action-test", bundle)
    try:
        response = await import_client.patch(
            "/api/import/preview/bulk-action-test/items",
            json={"indexes": [0, 99], "action": "reimport"},
        )
        assert response.status_code == 400
        assert [item.action for item in get_bundle("bulk-action-test").items] == [
            "skip",
            "skip",
        ]

        response = await import_client.patch(
            "/api/import/preview/bulk-action-test/items",
            json={"indexes": [0, 1], "action": "reimport"},
        )
        assert response.status_code == 200
        assert response.json()["updated"] == 2
        assert [item.action for item in get_bundle("bulk-action-test").items] == [
            "reimport",
            "reimport",
        ]
    finally:
        remove_bundle("bulk-action-test")


@pytest.mark.asyncio
async def test_import_history_detail_hides_undo_snapshot(import_client):
    from app.core import db
    from app.models.import_job import ImportJob
    from app.models.import_job_item import ImportJobItem

    async with db.async_session_factory() as session:
        session.add(
            ImportJob(
                id="legacy-history-item",
                source="generic",
                source_path="/local/export",
                detected_format="generic",
                origin="manual",
                undo_state="unavailable",
                status="completed",
                imported_counts="{}",
                skipped_counts="{}",
                error_count=0,
                item_count=1,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            ImportJobItem(
                id="secret-journal-row",
                job_id="legacy-history-item",
                source_item_id="session:1",
                kind="session",
                label="Imported session",
                operation="reimported",
                outcome="imported",
                before_snapshot='{"messages":[{"content":"private"}]}',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    detail = await import_client.get("/api/import/history/legacy-history-item")
    undo = await import_client.post("/api/import/history/legacy-history-item/undo")

    assert detail.status_code == 200
    assert detail.json()["undo_state"] == "unavailable"
    assert "before_snapshot" not in detail.text
    assert "private" not in detail.text
    assert undo.status_code == 200
    assert undo.json()["state"] == "unavailable"


@pytest.mark.asyncio
async def test_api_import_reimport_and_undo_round_trip(import_client):
    from sqlmodel import select

    from app.core import db
    from app.models.chat import ChatSession, SessionMessage

    store_bundle(
        "create-session",
        ImportBundle(
            source="generic",
            detected_format="generic",
            items=[
                ImportItem(
                    "session",
                    "generic",
                    "round-trip-id",
                    {
                        "title": "Original",
                        "messages": [{"role": "user", "content": "Original message"}],
                    },
                    "Original",
                )
            ],
        ),
    )
    created = await import_client.post(
        "/api/import/execute/create-session", json={"origin": "manual"}
    )
    assert created.status_code == 200
    create_job_id = created.json()["import_id"]

    store_bundle(
        "replace-session",
        ImportBundle(
            source="generic",
            detected_format="generic",
            items=[
                ImportItem(
                    "session",
                    "generic",
                    "round-trip-id",
                    {
                        "title": "Updated",
                        "messages": [
                            {"role": "assistant", "content": "Updated message"}
                        ],
                    },
                    "Updated",
                    action="reimport",
                )
            ],
        ),
    )
    replaced = await import_client.post(
        "/api/import/execute/replace-session", json={"origin": "manual"}
    )
    assert replaced.status_code == 200
    replace_job_id = replaced.json()["import_id"]

    restored = await import_client.post(f"/api/import/history/{replace_job_id}/undo")
    assert restored.json()["state"] == "undone"
    async with db.async_session_factory() as session:
        rows = (await session.execute(select(ChatSession))).scalars().all()
        messages = (await session.execute(select(SessionMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Original"
    assert [message.content for message in messages] == ["Original message"]

    removed = await import_client.post(f"/api/import/history/{create_job_id}/undo")
    assert removed.json()["state"] == "undone"
    async with db.async_session_factory() as session:
        assert (await session.execute(select(ChatSession))).scalars().all() == []
