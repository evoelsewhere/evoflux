from __future__ import annotations

from datetime import datetime, timezone

from app.services.import_service import _import_skill, detect_conflicts
from app.services.importers.base import ImportBundle, ImportItem
from app.services.importers.claude_code import (
    _parse_session_jsonl,
    parse_claude_code_export,
)
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


def test_skill_conflicts_from_other_local_roots_are_visible(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.agent.skills.models import Skill
    from app.agent.skills import registry
    from app.core.config import settings

    target_root = tmp_path / "evoflux-skills"
    provider_file = tmp_path / ".claude" / "skills" / "release-notes" / "SKILL.md"
    provider_file.parent.mkdir(parents=True)
    provider_file.write_text(
        "---\nname: release-notes\ndescription: Claude release helper\n---\nUse changelog conventions.",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "SKILLS_DIR", str(target_root))
    skill = Skill(
        name="release-notes",
        description="Claude release helper",
        location=provider_file,
        root=provider_file.parent.parent,
        source="user",
    )
    monkeypatch.setattr(
        registry,
        "discover_skills",
        lambda: SimpleNamespace(get=lambda name: skill if name == skill.name else None),
    )
    bundle = ImportBundle(
        source="claude_code",
        detected_format="claude_code",
        items=[
            ImportItem(
                kind="skill",
                source="claude_code",
                source_id="skill:release-notes",
                data={"name": "release-notes"},
                label="Skill: release-notes",
            )
        ],
    )

    import asyncio

    asyncio.run(detect_conflicts(None, bundle))  # type: ignore[arg-type]

    item = bundle.items[0]
    assert item.action == "skip"
    assert item.conflicts == ["Skill already exists in Claude Code skills"]
    assert item.data["preview_origin"] == "Claude Code skills"
    assert not (target_root / "release-notes").exists()


def test_renamed_skill_copy_uses_a_free_evoflux_target(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.import_service import _rename_skill_target

    skills_root = tmp_path / "skills"
    (skills_root / "release-notes-evoflux").mkdir(parents=True)
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    provider_skill = tmp_path / "provider" / "release-notes" / "SKILL.md"
    provider_skill.parent.mkdir(parents=True)
    provider_skill.write_text("provider-owned content", encoding="utf-8")
    original_source = provider_skill.read_text(encoding="utf-8")
    item = ImportItem(
        kind="skill",
        source="claude_code",
        source_id="skill:release-notes",
        data={"name": "release-notes"},
        label="Skill: release-notes",
    )

    target_name = _rename_skill_target(item)

    assert target_name == "release-notes-evoflux-2"
    assert item.data["name"] == target_name
    _import_skill(item, datetime.now(timezone.utc))
    imported_copy = skills_root / target_name / "SKILL.md"
    assert imported_copy.is_file()
    assert "name: release-notes-evoflux-2" in imported_copy.read_text(encoding="utf-8")
    assert provider_skill.read_text(encoding="utf-8") == original_source


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


def test_claude_desktop_type_rows_work_without_embedded_roles(tmp_path):
    import json

    session_file = tmp_path / "desktop.jsonl"
    rows = [
        {
            "type": "human",
            "timestamp": "2026-10-06T01:00:00Z",
            "message": {"content": "Hello from Desktop"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-06T01:00:01Z",
            "message": {"content": [{"type": "text", "text": "Hello back"}]},
        },
    ]
    session_file.write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )

    parsed = _parse_session_jsonl(session_file)

    assert parsed is not None
    assert [
        (message["role"], message["content"]) for message in parsed["messages"]
    ] == [
        ("user", "Hello from Desktop"),
        ("assistant", "Hello back"),
    ]


def test_claude_session_preserves_task_sidechain_and_tool_result(tmp_path):
    import json

    session_file = tmp_path / "session.jsonl"
    rows = [
        {
            "type": "user",
            "uuid": "user-1",
            "timestamp": "2026-10-06T01:00:00Z",
            "message": {"role": "user", "content": "Delegate this task"},
        },
        {
            "type": "assistant",
            "uuid": "assistant-1",
            "parentUuid": "user-1",
            "timestamp": "2026-10-06T01:00:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "task-call-1",
                        "name": "Task",
                        "input": {"description": "Inspect the issue"},
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "uuid": "agent-message-1",
            "parentUuid": "assistant-1",
            "isSidechain": True,
            "agentId": "reviewer",
            "timestamp": "2026-10-06T01:00:02Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "I found the cause."}],
            },
        },
        {
            "type": "user",
            "uuid": "tool-result-event-1",
            "parentUuid": "assistant-1",
            "timestamp": "2026-10-06T01:00:03Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "task-call-1",
                        "content": "The review is complete.",
                    }
                ],
            },
        },
        {
            "type": "progress",
            "data": {"message": "internal progress should not be a chat row"},
        },
    ]
    session_file.write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )

    parsed = _parse_session_jsonl(session_file)

    assert parsed is not None
    assert [message["role"] for message in parsed["messages"]] == [
        "user",
        "assistant",
        "assistant",
        "tool",
    ]
    task_call = parsed["messages"][1]
    assert task_call["content"] == ""
    assert task_call["tool_calls"][0]["id"] == "task-call-1"
    assert task_call["tool_calls"][0]["function"]["name"] == "Task"
    subagent = parsed["messages"][2]
    assert subagent["name"] == "reviewer"
    assert subagent["exclude_from_context"] is True
    assert subagent["extra"]["visible_when_excluded"] is True
    assert subagent["extra"]["import_source"]["is_sidechain"] is True
    assert subagent["extra"]["import_source"]["parent_event_id"] == "assistant-1"
    assert parsed["messages"][3]["tool_call_id"] == "task-call-1"
    assert parsed["messages"][3]["content"] == "The review is complete."


def test_claude_session_preserves_multiple_tool_calls_without_parent_text(tmp_path):
    import json

    session_file = tmp_path / "session.jsonl"
    rows = [
        {
            "type": "user",
            "uuid": "user-multi",
            "timestamp": "2026-10-06T01:00:00Z",
            "message": {"role": "user", "content": "Run two independent checks."},
        },
        {
            "type": "assistant",
            "uuid": "assistant-multi",
            "parentUuid": "user-multi",
            "timestamp": "2026-10-06T01:00:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "task-reviewer",
                        "name": "Task",
                        "input": {"subagent_type": "reviewer"},
                    },
                    {
                        "type": "tool_use",
                        "id": "task-explorer",
                        "name": "Task",
                        "input": {"subagent_type": "explorer"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "uuid": "results-multi",
            "parentUuid": "assistant-multi",
            "timestamp": "2026-10-06T01:00:02Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "task-reviewer",
                        "content": "Reviewer complete.",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "task-explorer",
                        "content": "Explorer complete.",
                    },
                ],
            },
        },
    ]
    session_file.write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )

    parsed = _parse_session_jsonl(session_file)

    assert parsed is not None
    parent = parsed["messages"][1]
    assert parent["role"] == "assistant"
    assert parent["content"] == ""
    assert [call["id"] for call in parent["tool_calls"]] == [
        "task-reviewer",
        "task-explorer",
    ]
    assert [message["tool_call_id"] for message in parsed["messages"][2:]] == [
        "task-reviewer",
        "task-explorer",
    ]
    assert [message["content"] for message in parsed["messages"][2:]] == [
        "Reviewer complete.",
        "Explorer complete.",
    ]


def test_claude_tool_results_are_bounded_and_binary_fields_are_omitted(tmp_path):
    import json

    session_file = tmp_path / "session.jsonl"
    row = {
        "type": "user",
        "uuid": "tool-result-event",
        "timestamp": "2026-10-06T01:00:00Z",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "x" * 21_000,
                }
            ],
        },
        "toolUseResult": {"file": {"base64": "never import this"}},
    }
    session_file.write_text(json.dumps(row), encoding="utf-8")

    parsed = _parse_session_jsonl(session_file)

    assert parsed is not None
    result = parsed["messages"][0]
    assert result["role"] == "tool"
    assert len(result["content"]) == 20_000
    assert result["extra"]["import_source"]["truncated"] is True
    assert "base64" not in str(result)


def test_claude_skill_origins_and_duplicate_names_are_preserved(tmp_path):
    import json
    from pathlib import Path

    def write_skill(root, relative_path, name):
        skill_dir = root / relative_path
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: helper\n---\nInstructions.",
            encoding="utf-8",
        )

    write_skill(tmp_path, Path("skills") / "release-notes", "release-notes")
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "release-notes.md").write_text(
        "# Command helper\nCommand instructions.", encoding="utf-8"
    )
    plugin_root = tmp_path / "plugin-cache" / "release-plugin"
    write_skill(plugin_root, Path("skills") / "release-notes", "release-notes")
    installed = tmp_path / "plugins" / "installed_plugins.json"
    installed.parent.mkdir(parents=True)
    installed.write_text(
        json.dumps(
            {"plugins": {"release-plugin@market": [{"installPath": str(plugin_root)}]}}
        ),
        encoding="utf-8",
    )
    standalone_root = tmp_path / "review-tools"
    write_skill(standalone_root, Path("skills") / "release-notes", "release-notes")

    bundle = parse_claude_code_export(tmp_path)
    skills = [item for item in bundle.items if item.kind == "skill"]

    origins = {item.data["source_metadata"]["kind"] for item in skills}
    names = [item.data["name"] for item in skills]
    assert origins == {
        "command",
        "global_skill",
        "installed_plugin_skill",
        "standalone_plugin_skill",
    }
    assert len(names) == len(set(names))
    assert all(len(name) <= 64 for name in names)
    assert any(
        item.data["source_metadata"].get("plugin") == "review-tools" for item in skills
    )

    for item in skills:
        origin = item.data["source_metadata"]
        assert item.data["preview_origin"]
        assert item.data["name"] in item.label
        assert origin["provider"] == "claude_code"


def test_imported_claude_skill_persists_origin_frontmatter(tmp_path, monkeypatch):
    from app.core.config import settings

    skills_root = tmp_path / "registry-skills"
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills_root))
    item = ImportItem(
        kind="skill",
        source="claude_code",
        source_id="release-helper@market:skill:release-notes",
        data={
            "name": "release-notes-release-helper-market",
            "description": "Changelog helper",
            "body": "Use the project's changelog.",
            "source_metadata": {
                "provider": "claude_code",
                "kind": "installed_plugin_skill",
                "plugin": "release-helper@market",
                "original_name": "release-notes",
                "resolved_name": "release-notes-release-helper-market",
            },
        },
        label="Skill: release-notes-release-helper-market",
    )

    _import_skill(item, datetime.now(timezone.utc))

    skill_file = skills_root / item.data["name"] / "SKILL.md"
    definition = parse_skill(
        skill_file.read_text(encoding="utf-8"),
        directory_name=item.data["name"],
    )
    assert definition.valid
    assert definition.metadata["provider"] == "claude_code"
    assert definition.metadata["kind"] == "installed_plugin_skill"
    assert definition.metadata["plugin"] == "release-helper@market"
    assert definition.metadata["original_name"] == "release-notes"


async def test_import_session_persists_claude_tool_metadata():
    from app.core.db import async_session_factory
    from app.services.import_service import _import_session
    from app.services.chat_service import get_messages, get_messages_for_llm
    from app.models.chat import SessionMessage
    from sqlmodel import select

    item = ImportItem(
        kind="session",
        source="claude_code",
        source_id="project:demo:session:session-1",
        data={
            "title": "Claude import",
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "created_at": "2026-10-06T01:00:01Z",
                    "tool_calls": [
                        {
                            "id": "task-call-1",
                            "type": "function",
                            "function": {
                                "name": "Task",
                                "arguments": '{"description":"Inspect"}',
                            },
                        }
                    ],
                    "name": "orchestrator",
                    "extra": {
                        "import_source": {
                            "provider": "claude_code",
                            "event_id": "assistant-1",
                        }
                    },
                },
                {
                    "role": "assistant",
                    "content": "Found the cause.",
                    "name": "reviewer",
                    "exclude_from_context": True,
                    "extra": {
                        "visible_when_excluded": True,
                        "import_source": {
                            "provider": "claude_code",
                            "is_sidechain": True,
                            "agent_id": "reviewer",
                        },
                    },
                },
                {
                    "role": "tool",
                    "content": "Done",
                    "tool_call_id": "task-call-1",
                    "name": "Task",
                    "extra": {"import_source": {"provider": "claude_code"}},
                },
            ],
        },
        label="Claude import",
    )

    async with async_session_factory() as db:
        session = await _import_session(db, item, datetime.now(timezone.utc))
        await db.commit()
        messages = list(
            (
                await db.exec(
                    select(SessionMessage).where(
                        SessionMessage.session_id == session.id
                    )
                )
            ).all()
        )
        visible = await get_messages(db, session.id)
        context = await get_messages_for_llm(db, session.id)

    assert messages[0].tool_calls[0]["id"] == "task-call-1"
    assert messages[0].name == "orchestrator"
    assert messages[0].extra["import_source"]["event_id"] == "assistant-1"
    assert messages[1].exclude_from_context is True
    assert messages[1].extra["visible_when_excluded"] is True
    assert len(visible) == 3
    assert any(message.content == "Found the cause." for message in visible)
    assert len(context) == 2
    assert context[0].tool_calls[0].id == "task-call-1"
    assert context[1].tool_call_id == "task-call-1"


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


async def test_chatgpt_title_change_reimports_by_stable_conversation_id():
    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.models.chat import ChatSession
    from app.services.import_service import execute_import
    from app.services.importers.chatgpt import _parse_conversations

    conversation = {
        "id": "chatgpt-stable-conversation",
        "title": "First title",
        "create_time": 1_700_000_000,
        "mapping": {
            "root": {"children": ["message-1"]},
            "message-1": {
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hello"]},
                    "create_time": 1_700_000_000,
                },
                "children": [],
            },
        },
    }

    async with async_session_factory() as db:
        first = ImportBundle(
            source="chatgpt",
            detected_format="chatgpt",
            items=_parse_conversations([conversation]),
        )
        await execute_import(db, first)

        conversation["title"] = "Updated title"
        second = ImportBundle(
            source="chatgpt",
            detected_format="chatgpt",
            items=_parse_conversations([conversation]),
        )
        await detect_conflicts(db, second)
        assert second.items[0].action == "skip"
        assert second.items[0].conflicts == ["Already imported"]
        second.items[0].action = "reimport"
        await execute_import(db, second)
        sessions = (await db.execute(select(ChatSession))).scalars().all()

    assert len(sessions) == 1
    assert sessions[0].title == "Updated title"
    assert sessions[0].source_item_id == "chatgpt:chatgpt-stable-conversation"


async def test_chatgpt_stable_id_migrates_unique_legacy_import_after_title_change():
    from app.core.db import async_session_factory
    from app.models.chat import ChatSession
    from app.services.importers.chatgpt import _parse_conversations

    conversation = {
        "id": "chatgpt-migrated-conversation",
        "title": "New title",
        "create_time": 1_700_000_321,
        "mapping": {
            "root": {"children": ["legacy-message"]},
            "legacy-message": {
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hello"]},
                    "create_time": 1_700_000_321,
                },
                "children": [],
            },
        },
    }

    async with async_session_factory() as db:
        db.add(
            ChatSession(
                title="Old title",
                source="chatgpt",
                source_item_id="chatgpt:Old title:1700000321",
            )
        )
        await db.commit()
        bundle = ImportBundle(
            source="chatgpt",
            detected_format="chatgpt",
            items=_parse_conversations([conversation]),
        )
        await detect_conflicts(db, bundle)

    assert bundle.items[0].action == "skip"
    assert bundle.items[0].conflicts == ["Already imported"]


async def test_chatgpt_legacy_match_with_duplicate_timestamp_requires_review():
    from app.core.db import async_session_factory
    from app.models.chat import ChatSession
    from app.services.importers.chatgpt import _parse_conversations

    conversation = {
        "id": "chatgpt-ambiguous-conversation",
        "title": "Current title",
        "create_time": 1_700_000_322,
        "mapping": {
            "root": {"children": ["message"]},
            "message": {
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hello"]},
                    "create_time": 1_700_000_322,
                },
                "children": [],
            },
        },
    }

    async with async_session_factory() as db:
        db.add_all(
            [
                ChatSession(
                    title="Older title A",
                    source="chatgpt",
                    source_item_id="chatgpt:Older title A:1700000322",
                ),
                ChatSession(
                    title="Older title B",
                    source="chatgpt",
                    source_item_id="chatgpt:Older title B:1700000322",
                ),
            ]
        )
        await db.commit()
        bundle = ImportBundle(
            source="chatgpt",
            detected_format="chatgpt",
            items=_parse_conversations([conversation]),
        )
        await detect_conflicts(db, bundle)

    assert bundle.items[0].action == "skip"
    assert bundle.items[0].data["_conflict_reason"] == "ambiguous_legacy_match"
    assert bundle.items[0].conflicts == [
        "Multiple legacy ChatGPT imports share this creation time"
    ]


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
