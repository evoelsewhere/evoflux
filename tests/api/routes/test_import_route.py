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
async def test_preview_can_keep_external_skill_as_a_renamed_evoflux_copy(
    import_client, tmp_path, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SKILLS_DIR", str(tmp_path / "skills"))
    bundle = ImportBundle(
        source="claude_code",
        detected_format="claude_code",
        items=[
            ImportItem(
                "skill",
                "claude_code",
                "release-notes",
                {"name": "release-notes"},
                "Skill: release-notes",
                conflicts=["Skill already exists in Claude Code skills"],
                action="skip",
            )
        ],
    )
    store_bundle("rename-skill-copy", bundle)
    try:
        response = await import_client.patch(
            "/api/import/preview/rename-skill-copy/items/0",
            json={"action": "rename"},
        )
        assert response.status_code == 200
        assert response.json()["target_name"] == "release-notes-evoflux"
        assert bundle.items[0].data["name"] == "release-notes-evoflux"
        assert bundle.items[0].action == "rename"
        assert not (tmp_path / "skills" / "release-notes-evoflux").exists()
    finally:
        remove_bundle("rename-skill-copy")


@pytest.mark.asyncio
async def test_external_skill_conflict_cannot_be_reimported_under_the_same_name(
    import_client,
):
    bundle = ImportBundle(
        source="claude_code",
        detected_format="claude_code",
        items=[
            ImportItem(
                "skill",
                "claude_code",
                "release-notes",
                {"name": "release-notes"},
                "Skill: release-notes",
                conflicts=["Skill already exists in Claude Code skills"],
                action="skip",
            )
        ],
    )
    store_bundle("reimport-skill-copy", bundle)
    try:
        response = await import_client.patch(
            "/api/import/preview/reimport-skill-copy/items/0",
            json={"action": "reimport"},
        )
        assert response.status_code == 400
        assert bundle.items[0].action == "skip"
        assert bundle.items[0].data["name"] == "release-notes"
        bulk = await import_client.patch(
            "/api/import/preview/reimport-skill-copy/items",
            json={"indexes": [0], "action": "reimport"},
        )
        assert bulk.status_code == 400
        assert bundle.items[0].action == "skip"
    finally:
        remove_bundle("reimport-skill-copy")


@pytest.mark.asyncio
async def test_preview_action_keeps_session_target_label(import_client):
    store_bundle(
        "session-action-label",
        ImportBundle(
            source="generic",
            detected_format="generic",
            items=[
                ImportItem(
                    "session",
                    "generic",
                    "session:1",
                    {"title": "Imported conversation"},
                    "Imported conversation",
                    conflicts=["Already imported"],
                    action="skip",
                )
            ],
        ),
    )
    try:
        response = await import_client.patch(
            "/api/import/preview/session-action-label/items/0",
            json={"action": "reimport"},
        )
        assert response.status_code == 200
        assert response.json()["target_name"] == "Imported conversation"
    finally:
        remove_bundle("session-action-label")


@pytest.mark.asyncio
async def test_unsupported_settings_are_read_only_in_preview(
    import_client, tmp_path, monkeypatch
):
    from app.api.routes import import_route

    source_file = tmp_path / "credentials.env"
    source_file.write_text("EXAMPLE_API_KEY=never-return-this", encoding="utf-8")
    bundle = ImportBundle(
        source="generic",
        detected_format="generic",
        items=[
            ImportItem(
                "setting",
                "generic",
                "credential:EXAMPLE_API_KEY",
                {"key": "EXAMPLE_API_KEY", "value": "never-return-this"},
                "Credential: EXAMPLE_API_KEY",
            )
        ],
    )
    monkeypatch.setattr(import_route, "parse_import", lambda path, source: bundle)

    response = await import_client.post(
        "/api/import/detect", json={"path": str(source_file), "source": "generic"}
    )

    assert response.status_code == 200
    body = response.json()
    item = body["items"][0]
    assert item["action"] == "skip"
    assert "not imported" in item["reason"].lower()
    assert body["summary"]["new_items"] == 0
    assert body["summary"]["already_imported"] == 0
    assert body["summary"]["not_importable"] == 1
    assert "never-return-this" not in response.text

    import_id = body["import_id"]
    rejected = await import_client.patch(
        f"/api/import/preview/{import_id}/items/0", json={"action": "import"}
    )
    assert rejected.status_code == 400
    assert "cannot be imported" in rejected.json()["detail"].lower()
    remove_bundle(import_id)


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
async def test_auto_sync_settings_persist_to_active_profile_and_merge(
    import_client, tmp_path, monkeypatch
):
    from app.core.config import settings
    from app.core.runtime_settings import (
        RuntimeSettings,
        load_runtime_settings_report,
        save_runtime_settings,
    )

    config_dir = tmp_path / "custom-profile" / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    save_runtime_settings(
        RuntimeSettings.model_validate(
            {
                "follow_up": {"delivery": "queue"},
                "import_auto_sync": {"notify_new_items": False},
            }
        )
    )

    response = await import_client.put(
        "/api/import/auto-sync", json={"enabled": True, "scan_interval_seconds": 90}
    )

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "scan_interval_seconds": 90,
        "notify_new_items": False,
    }
    persisted = await import_client.get("/api/import/auto-sync")
    assert persisted.json() == response.json()
    loaded, ignored = load_runtime_settings_report()
    assert not ignored
    assert loaded.follow_up.delivery == "queue"
    assert (config_dir / "settings.yaml").exists()


@pytest.mark.asyncio
async def test_auto_sync_settings_reject_invalid_interval_without_writing(
    import_client, tmp_path, monkeypatch
):
    from app.core.config import settings
    from app.core.runtime_settings import save_runtime_settings

    config_dir = tmp_path / "custom-profile" / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_dir))
    from app.core.runtime_settings import RuntimeSettings

    save_runtime_settings(RuntimeSettings())
    settings_path = config_dir / "settings.yaml"
    before = settings_path.read_text(encoding="utf-8")

    response = await import_client.put(
        "/api/import/auto-sync", json={"scan_interval_seconds": 2}
    )

    assert response.status_code == 422
    assert settings_path.read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_preview_shows_skill_origin_without_exposing_source_path(import_client):
    store_bundle(
        "skill-origin-preview",
        ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            metadata={"source_path": "C:/private/claude"},
            items=[
                ImportItem(
                    kind="skill",
                    source="claude_code",
                    source_id="plugin:release-helper:skill:release-notes",
                    data={
                        "name": "release-notes-plugin-release-helper",
                        "description": "Release helper",
                        "preview_origin": "Claude Code plugin · release-helper",
                    },
                    label="Skill: release-notes-plugin-release-helper",
                )
            ],
        ),
    )
    try:
        response = await import_client.get("/api/import/preview/skill-origin-preview")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["origin"] == "Claude Code plugin · release-helper"
        assert item["target_name"] == "release-notes-plugin-release-helper"
        assert "C:/private/claude" not in item["origin"]
    finally:
        remove_bundle("skill-origin-preview")


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
