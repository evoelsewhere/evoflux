"""Internal source snapshot and reconciliation invariants."""

from __future__ import annotations

from pathlib import Path

from app.services.codeindex.reconcile import plan_reconciliation
from app.services.codeindex.chunks import build_source_chunks
from app.services.code_graph.indexer import index_workspace
from app.services.codeindex.source import (
    fingerprint_source,
    read_source_records,
    walk_source_records,
)


def test_reconcile_plan_is_deterministic_and_tracks_desired_absence() -> None:
    plan = plan_reconciliation(
        {"new.py": "n", "same.py": "s", "changed.py": "c2"},
        {"old.py": "o", "same.py": "s", "changed.py": "c1"},
    )

    assert plan.adds == ("new.py",)
    assert plan.updates == ("changed.py",)
    assert plan.deletes == ("old.py",)
    assert plan.unchanged == ("same.py",)
    assert plan.reprocess == ("new.py", "changed.py")
    assert plan.affected == frozenset({"new.py", "changed.py", "old.py"})


def test_force_reprocess_preserves_add_vs_update_identity() -> None:
    plan = plan_reconciliation(
        {"existing.py": "same", "new.py": "new"},
        {"existing.py": "same", "deleted.py": "old"},
        force=True,
    )

    assert plan.adds == ("new.py",)
    assert plan.updates == ("existing.py",)
    assert plan.deletes == ("deleted.py",)
    assert plan.unchanged == ()


def test_source_snapshot_is_stable_filtered_and_content_addressed(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "ignored").mkdir()
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("B = 2\n", encoding="utf-8")
    (tmp_path / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "src" / "image.png").write_bytes(b"png")
    (tmp_path / "ignored" / "hidden.py").write_text("X = 1\n", encoding="utf-8")

    records = list(walk_source_records(tmp_path, extensions=frozenset({".py"})))

    assert [record.key for record in records] == ["src/a.py", "src/b.py"]
    assert records[0].fingerprint == fingerprint_source(b"A = 1\n")
    assert len(records[0].fingerprint) == 64
    named = list(
        read_source_records(
            tmp_path,
            ["src/b.py", "src/a.py", "src/image.png", "../outside.py"],
            extensions=frozenset({".py"}),
        )
    )
    assert [record.key for record in named] == ["src/b.py", "src/a.py"]


def test_source_chunks_partition_oversized_files_at_symbol_ranges(
    tmp_path: Path,
) -> None:
    source = (
        "module_value = 1\n"
        "\n"
        "def first_function():\n"
        "    first_value = 'alpha'\n"
        "    return first_value\n"
        "\n"
        "def second_function():\n"
        "    second_value = 'beta'\n"
        "    return second_value\n"
    )
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    index = index_workspace(tmp_path)

    chunks = build_source_chunks(
        tmp_path,
        ["sample.py"],
        index.nodes,
        extensions=frozenset({".py"}),
        max_chars=70,
    )

    assert len(chunks) >= 3
    assert any(chunk.qualified_name == "first_function" for chunk in chunks)
    assert any(chunk.qualified_name == "second_function" for chunk in chunks)
    assert all(
        left.line_end < right.line_start
        for left, right in zip(chunks, chunks[1:], strict=False)
    )
    assert "".join(chunk.content for chunk in chunks).replace("\n", "") == source.replace(
        "\n", ""
    )
