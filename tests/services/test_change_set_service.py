from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.change_set_service import (
    ChangeFileInput,
    ChangeSetError,
    ChangeSetStale,
    apply_change_set,
    clear_change_sets,
    create_change_set,
    get_change_file_contents,
    inputs_from_workspace_edit,
    reject_change_set,
    serialize_change_set,
)


@pytest.fixture(autouse=True)
def _clear_store():
    clear_change_sets()
    yield
    clear_change_sets()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.asyncio
async def test_multi_file_preview_partial_apply_and_reject(tmp_path: Path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 1\n", encoding="utf-8")
    record = create_change_set(
        tmp_path,
        origin="ai",
        title="Update values",
        files=[
            ChangeFileInput("first.py", "first = 2\n", _sha("first = 1\n"), 4),
            ChangeFileInput("second.py", "second = 2\n", _sha("second = 1\n"), 9),
        ],
    )

    preview = serialize_change_set(record)
    assert preview["files"][0]["base_hash"] == _sha("first = 1\n")
    assert preview["files"][0]["document_version"] == 4
    assert "+first = 2" in preview["files"][0]["diff"]
    contents = get_change_file_contents(record.id, tmp_path, "first.py")
    assert contents["original_content"] == "first = 1\n"
    assert contents["proposed_content"] == "first = 2\n"

    await apply_change_set(record.id, tmp_path, paths=["first.py"])
    reject_change_set(record.id, tmp_path, paths=["second.py"])

    assert first.read_text(encoding="utf-8") == "first = 2\n"
    assert second.read_text(encoding="utf-8") == "second = 1\n"
    assert record.status == "partial"
    assert [item.status for item in record.files] == ["applied", "rejected"]


@pytest.mark.asyncio
async def test_stale_file_blocks_entire_selected_apply(tmp_path: Path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 1\n", encoding="utf-8")
    record = create_change_set(
        tmp_path,
        origin="lsp",
        title="Rename",
        files=[
            ChangeFileInput("first.py", "first = 2\n"),
            ChangeFileInput("second.py", "second = 2\n"),
        ],
    )
    second.write_text("second = 3\n", encoding="utf-8")

    with pytest.raises(ChangeSetStale) as exc_info:
        await apply_change_set(record.id, tmp_path)

    assert exc_info.value.paths == ["second.py"]
    assert first.read_text(encoding="utf-8") == "first = 1\n"
    assert second.read_text(encoding="utf-8") == "second = 3\n"


@pytest.mark.asyncio
async def test_apply_rolls_back_when_later_atomic_write_fails(tmp_path: Path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 1\n", encoding="utf-8")
    record = create_change_set(
        tmp_path,
        origin="ai",
        title="Update",
        files=[
            ChangeFileInput("first.py", "first = 2\n"),
            ChangeFileInput("second.py", "second = 2\n"),
        ],
    )
    from app.services import change_set_service

    real_atomic_write = change_set_service.atomic_write_bytes
    writes = 0

    def fail_second(path: Path, data: bytes):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("disk full")
        real_atomic_write(path, data)

    with patch.object(
        change_set_service, "atomic_write_bytes", side_effect=fail_second
    ):
        with pytest.raises(ChangeSetError, match="rolled back"):
            await apply_change_set(record.id, tmp_path)

    assert first.read_text(encoding="utf-8") == "first = 1\n"
    assert second.read_text(encoding="utf-8") == "second = 1\n"
    assert all(item.status == "pending" for item in record.files)


def test_workspace_edit_converts_multiple_utf16_text_edits(tmp_path: Path):
    source = tmp_path / "emoji.ts"
    source.write_text('const face = "😀";\nconst value = 1;\n', encoding="utf-8")
    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": source.as_uri(), "version": 7},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 14},
                            "end": {"line": 0, "character": 16},
                        },
                        "newText": "🙂",
                    },
                    {
                        "range": {
                            "start": {"line": 1, "character": 6},
                            "end": {"line": 1, "character": 11},
                        },
                        "newText": "renamed",
                    },
                ],
            }
        ]
    }

    inputs = inputs_from_workspace_edit(tmp_path, edit)

    assert len(inputs) == 1
    assert inputs[0].document_version == 7
    assert inputs[0].proposed_content == 'const face = "🙂";\nconst renamed = 1;\n'


def test_workspace_edit_rejects_escape_and_overlapping_edits(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.py"
    outside.write_text("outside = 1\n", encoding="utf-8")

    with pytest.raises(ChangeSetError, match="escapes"):
        inputs_from_workspace_edit(
            tmp_path,
            {"changes": {outside.as_uri(): []}},
        )

    with pytest.raises(ChangeSetError, match="Overlapping"):
        inputs_from_workspace_edit(
            tmp_path,
            {
                "changes": {
                    source.as_uri(): [
                        {
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 5},
                            },
                            "newText": "first",
                        },
                        {
                            "range": {
                                "start": {"line": 0, "character": 3},
                                "end": {"line": 0, "character": 7},
                            },
                            "newText": "second",
                        },
                    ]
                }
            },
        )


@pytest.mark.asyncio
async def test_model_command_cannot_expand_verification_authority(tmp_path: Path):
    target = tmp_path / "notes.txt"
    target.write_text("before\n", encoding="utf-8")
    record = create_change_set(
        tmp_path,
        origin="ai",
        title="Update notes",
        files=[ChangeFileInput("notes.txt", "after\n")],
        verification_commands=[
            "python -c \"print('verified')\"",
            "git status; echo unsafe",
        ],
    )

    await apply_change_set(record.id, tmp_path)

    assert record.verification_commands == []
    assert record.verification == []


def test_verification_is_discovered_from_existing_project_contract(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    (tmp_path / "tests").mkdir()
    target = tmp_path / "app.py"
    target.write_text("value = 1\n", encoding="utf-8")

    record = create_change_set(
        tmp_path,
        origin="ai",
        title="Update app",
        files=[ChangeFileInput("app.py", "value = 2\n")],
        verification_commands=["python -c \"print('unsafe')\""],
    )

    assert record.verification_commands == ["uv run pytest --no-cov -q"]
