from __future__ import annotations

from datetime import datetime, timezone

from app.services.import_service import _import_skill, detect_conflicts
from app.services.importers.base import ImportBundle, ImportItem
from app.services.importers.claude_code import parse_claude_code_export
from app.services.importers.codex import parse_codex_export
from app.agent.skills.spec import parse_skill


def test_imported_skill_uses_registry_root_and_valid_frontmatter(tmp_path, monkeypatch):
    from app.core.config import settings

    skills_root = tmp_path / "registry-skills"
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    item = ImportItem(
        kind="skill",
        source="generic",
        source_id="skill:release-notes",
        data={
            "name": "release-notes",
            "description": "Write release notes: concise and clear",
            "body": "Use the project's changelog.",
        },
        label="Skill: release-notes",
    )

    _import_skill(item, datetime.now(timezone.utc))

    skill_file = skills_root / "release-notes" / "SKILL.md"
    assert skill_file.is_file()
    definition = parse_skill(
        skill_file.read_text(encoding="utf-8"), directory_name="release-notes"
    )
    assert definition.valid
    assert definition.description == "Write release notes: concise and clear"
    assert definition.body == "Use the project's changelog."


def test_skill_conflicts_check_registry_root(tmp_path, monkeypatch):
    from app.core.config import settings

    skills_root = tmp_path / "registry-skills"
    (skills_root / "release-notes").mkdir(parents=True)
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    bundle = ImportBundle(
        source="generic",
        detected_format="generic",
        items=[
            ImportItem(
                kind="skill",
                source="generic",
                source_id="skill:release-notes",
                data={"name": "release-notes"},
                label="Skill: release-notes",
            )
        ],
    )

    # Skill conflicts do not use the DB session.
    import asyncio

    asyncio.run(detect_conflicts(None, bundle))  # type: ignore[arg-type]

    assert bundle.items[0].action == "skip"
    assert bundle.items[0].conflicts == ["Skill already exists"]


def test_claude_code_import_reads_global_skills(tmp_path):
    skill_dir = tmp_path / "skills" / "release-notes"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: release-notes\ndescription: Changelog helper\n---\nUse changelog conventions.",
        encoding="utf-8",
    )

    bundle = parse_claude_code_export(tmp_path)

    assert [(item.kind, item.data["name"]) for item in bundle.items] == [
        ("skill", "release-notes")
    ]


def test_codex_import_reads_sibling_agents_skills(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    skill_dir = tmp_path / ".agents" / "skills" / "release-notes"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: release-notes\ndescription: Changelog helper\n---\nUse changelog conventions.",
        encoding="utf-8",
    )

    bundle = parse_codex_export(codex_dir)

    assert [(item.kind, item.data["name"]) for item in bundle.items] == [
        ("skill", "release-notes")
    ]


async def test_distinct_source_item_ids_with_same_title_do_not_conflict():
    from app.core.db import async_session_factory
    from app.models.chat import ChatSession

    async with async_session_factory() as db:
        db.add(
            ChatSession(
                title="Same title",
                source="claude_code",
                source_item_id="source-item-1",
            )
        )
        await db.commit()
        bundle = ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            items=[
                ImportItem(
                    kind="session",
                    source="claude_code",
                    source_id="source-item-2",
                    data={"title": "Same title", "messages": []},
                    label="Same title",
                )
            ],
        )

        await detect_conflicts(db, bundle)

    assert bundle.items[0].action == "import"
    assert bundle.items[0].conflicts == []


async def test_undo_created_session_removes_session_and_messages():
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.models.chat import ChatSession, SessionMessage
    from app.services.import_service import execute_import, undo_import

    bundle = ImportBundle(
        source="claude_code",
        detected_format="claude_code",
        items=[
            ImportItem(
                kind="session",
                source="claude_code",
                source_id="undo-created-session",
                data={
                    "title": "Undo me",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                label="Undo me",
            )
        ],
    )

    async with async_session_factory() as db:
        result = await execute_import(db, bundle)
        sessions = (await db.execute(select(ChatSession))).scalars().all()
        messages = (await db.execute(select(SessionMessage))).scalars().all()
        assert result.imported == {"session": 1}
        assert result.import_id
        assert len(sessions) == 1
        assert len(messages) == 1

        undo = await undo_import(db, result.import_id)

        assert undo.undone == 1, undo.items
        assert (await db.execute(select(ChatSession))).scalars().all() == []
        assert (await db.execute(select(SessionMessage))).scalars().all() == []


async def test_reimport_updates_matching_session_in_place():
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.models.chat import ChatSession, SessionMessage
    from app.services.import_service import execute_import

    async with async_session_factory() as db:
        first = ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            items=[
                ImportItem(
                    kind="session",
                    source="claude_code",
                    source_id="stable-session-id",
                    data={
                        "title": "Before",
                        "messages": [{"role": "user", "content": "Old"}],
                    },
                    label="Before",
                )
            ],
        )
        await execute_import(db, first)

        second = ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            items=[
                ImportItem(
                    kind="session",
                    source="claude_code",
                    source_id="stable-session-id",
                    data={
                        "title": "After",
                        "messages": [{"role": "assistant", "content": "New"}],
                    },
                    label="After",
                    action="replace",
                )
            ],
        )
        await detect_conflicts(db, second)
        second.items[0].action = "reimport"

        result = await execute_import(db, second)
        sessions = (await db.execute(select(ChatSession))).scalars().all()
        messages = (await db.execute(select(SessionMessage))).scalars().all()

    assert result.imported == {"session": 1}
    assert len(sessions) == 1
    assert sessions[0].title == "After"
    assert sessions[0].source_item_id == "stable-session-id"
    assert len(messages) == 1
    assert messages[0].content == "New"


async def test_undo_reimport_restores_previous_session_content():
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.models.chat import ChatSession, SessionMessage
    from app.services.import_service import execute_import, undo_import

    async with async_session_factory() as db:
        original = ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            items=[
                ImportItem(
                    kind="session",
                    source="claude_code",
                    source_id="restore-session-id",
                    data={
                        "title": "Original",
                        "messages": [{"role": "user", "content": "Original text"}],
                    },
                    label="Original",
                )
            ],
        )
        await execute_import(db, original)

        replacement = ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            items=[
                ImportItem(
                    kind="session",
                    source="claude_code",
                    source_id="restore-session-id",
                    data={
                        "title": "Replacement",
                        "messages": [
                            {"role": "assistant", "content": "Replacement text"}
                        ],
                    },
                    label="Replacement",
                    action="reimport",
                )
            ],
        )
        replaced = await execute_import(db, replacement)
        undo = await undo_import(db, replaced.import_id or "")
        sessions = (await db.execute(select(ChatSession))).scalars().all()
        messages = (await db.execute(select(SessionMessage))).scalars().all()

    assert undo.undone == 1
    assert len(sessions) == 1
    assert sessions[0].title == "Original"
    assert sessions[0].source_item_id == "restore-session-id"
    assert len(messages) == 1
    assert messages[0].content == "Original text"


async def test_undo_skips_session_changed_after_import():
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.models.chat import ChatSession
    from app.services.import_service import execute_import, undo_import

    bundle = ImportBundle(
        source="claude_code",
        detected_format="claude_code",
        items=[
            ImportItem(
                kind="session",
                source="claude_code",
                source_id="keep-edited-session",
                data={"title": "Imported title", "messages": []},
                label="Imported title",
            )
        ],
    )
    async with async_session_factory() as db:
        imported = await execute_import(db, bundle)
        session = (await db.execute(select(ChatSession))).scalars().one()
        session.title = "User edited title"
        await db.commit()

        undo = await undo_import(db, imported.import_id or "")
        session = await db.get(ChatSession, session.id)

    assert undo.state == "partially_undone"
    assert undo.skipped == 1
    assert session is not None
    assert session.title == "User edited title"


async def test_ambiguous_legacy_session_match_requires_manual_resolution():
    from app.core.db import async_session_factory
    from app.models.chat import ChatSession

    async with async_session_factory() as db:
        db.add_all(
            [
                ChatSession(title="Legacy title", source="claude_code"),
                ChatSession(title="Legacy title", source="claude_code"),
            ]
        )
        await db.commit()
        bundle = ImportBundle(
            source="claude_code",
            detected_format="claude_code",
            items=[
                ImportItem(
                    kind="session",
                    source="claude_code",
                    source_id="unknown-new-source-id",
                    data={"title": "Legacy title", "messages": []},
                    label="Legacy title",
                )
            ],
        )

        await detect_conflicts(db, bundle)

    assert bundle.items[0].action == "skip"
    assert bundle.items[0].data["_conflict_reason"] == "ambiguous_legacy_match"


async def test_undo_does_not_remove_skill_file_modified_after_import(
    tmp_path, monkeypatch
):
    from app.core.config import settings
    from app.services.import_service import execute_import, undo_import

    skills_root = tmp_path / "skills"
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    bundle = ImportBundle(
        source="generic",
        detected_format="generic",
        items=[
            ImportItem(
                kind="skill",
                source="generic",
                source_id="skill:release-notes",
                data={
                    "name": "release-notes",
                    "description": "Release helper",
                    "body": "Original",
                },
                label="release-notes",
            )
        ],
    )
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        imported = await execute_import(db, bundle)
        skill_file = skills_root / "release-notes" / "SKILL.md"
        skill_file.write_text("User edited this skill", encoding="utf-8")

        undo = await undo_import(db, imported.import_id or "")

    assert undo.state == "partially_undone"
    assert undo.skipped == 1
    assert skill_file.read_text(encoding="utf-8") == "User edited this skill"


async def test_imported_agent_name_cannot_escape_agents_directory(
    tmp_path, monkeypatch
):
    from app.core.config import settings
    from app.core.db import async_session_factory
    from app.services.import_service import execute_import

    config_root = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_root))
    bundle = ImportBundle(
        source="generic",
        detected_format="generic",
        items=[
            ImportItem(
                kind="agent",
                source="generic",
                source_id="agent:unsafe-name",
                data={"name": "../../outside", "instructions": "safe"},
                label="Unsafe name",
            )
        ],
    )

    async with async_session_factory() as db:
        result = await execute_import(db, bundle)

    agents_dir = config_root / "agents"
    assert result.imported == {"agent": 1}
    assert list(agents_dir.glob("*.md"))
    assert not (tmp_path / "outside.md").exists()


async def test_mcp_import_does_not_copy_environment_or_auth_credentials(
    tmp_path, monkeypatch
):
    import json

    from app.core.config import settings
    from app.core.db import async_session_factory
    from app.services.import_service import execute_import

    config_root = tmp_path / "config"
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_root))
    bundle = ImportBundle(
        source="generic",
        detected_format="generic",
        items=[
            ImportItem(
                kind="mcp_server",
                source="generic",
                source_id="server:test",
                data={
                    "name": "test",
                    "server": {
                        "command": "tool",
                        "env": {"API_TOKEN": "imported-secret"},
                        "headers": {"Authorization": "Bearer imported-secret"},
                        "client_secret": "nested-imported-secret",
                    },
                },
                label="test server",
            )
        ],
    )

    async with async_session_factory() as db:
        result = await execute_import(db, bundle)

    assert result.errors == []
    config = json.loads((config_root / "mcp.json").read_text(encoding="utf-8"))
    assert result.imported == {"mcp_server": 1}
    assert "env" not in config["servers"]["test"]
    assert "headers" not in config["servers"]["test"]
    assert "imported-secret" not in json.dumps(config)
    assert "nested-imported-secret" not in json.dumps(config)


async def test_mcp_reimport_keeps_existing_credentials_out_of_journal_and_undo(
    tmp_path, monkeypatch
):
    import json

    from app.core.config import settings
    from app.core.db import async_session_factory
    from app.models.import_job_item import ImportJobItem
    from app.services.import_service import execute_import, undo_import
    from sqlmodel import select

    config_root = tmp_path / "config"
    config_root.mkdir()
    mcp_path = config_root / "mcp.json"
    original = {
        "servers": {
            "test": {
                "command": "old-tool",
                "env": {"API_TOKEN": "existing-secret"},
                "headers": {"Authorization": "Bearer existing-secret"},
                "client_secret": "existing-client-secret",
                "args": ["old"],
            }
        }
    }
    mcp_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config_root))
    bundle = ImportBundle(
        source="generic",
        detected_format="generic",
        items=[
            ImportItem(
                kind="mcp_server",
                source="generic",
                source_id="server:test",
                data={
                    "name": "test",
                    "server": {"command": "new-tool", "args": ["new"]},
                },
                label="test server",
                conflicts=["MCP server already exists"],
                action="reimport",
            )
        ],
    )

    async with async_session_factory() as db:
        imported = await execute_import(db, bundle)
        assert imported.errors == []
        journal = (await db.execute(select(ImportJobItem))).scalars().one()
        assert "existing-secret" not in (journal.before_snapshot or "")
        current = json.loads(mcp_path.read_text(encoding="utf-8"))
        assert current["servers"]["test"]["env"] == original["servers"]["test"]["env"]
        assert (
            current["servers"]["test"]["headers"]
            == original["servers"]["test"]["headers"]
        )
        assert current["servers"]["test"]["client_secret"] == "existing-client-secret"

        undone = await undo_import(db, imported.import_id or "")

    restored = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert undone.state == "undone"
    assert restored == original
