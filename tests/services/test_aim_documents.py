from pathlib import Path

import pytest

from app.services.aim.documents import (
    DocumentConflictError,
    DocumentError,
    create_document,
    read_document,
    search_documents,
    update_document,
)


def test_document_round_trip_uses_revision_conflict_check(tmp_path: Path):
    path = tmp_path / "decisions" / "ADR-001.md"
    path.parent.mkdir()
    path.write_text("# Original\n", encoding="utf-8")

    original = read_document(tmp_path, "decisions/ADR-001.md")
    saved = update_document(
        tmp_path,
        original.path,
        "# Updated\n",
        expected_revision=original.revision,
    )

    assert saved.content == "# Updated\n"
    assert saved.revision != original.revision
    with pytest.raises(DocumentConflictError):
        update_document(
            tmp_path,
            original.path,
            "# Stale\n",
            expected_revision=original.revision,
        )


def test_create_document_rejects_generated_and_escaping_paths(tmp_path: Path):
    created = create_document(tmp_path, "decisions/ADR-002.md", "# Decision\n")
    assert created.path == "decisions/ADR-002.md"

    with pytest.raises(DocumentError, match="read-only"):
        create_document(tmp_path, "state/manual.md", "no")
    with pytest.raises(DocumentError, match="safe KB-relative"):
        create_document(tmp_path, "../escape.md", "no")


def test_structured_documents_are_validated_before_write(tmp_path: Path):
    with pytest.raises(DocumentError, match="invalid structured document"):
        create_document(tmp_path, "aim.yaml", "phase: [broken")
    with pytest.raises(DocumentError, match="frontmatter requires unit"):
        create_document(
            tmp_path,
            "business-rules/BR-001.md",
            "---\nstatus: candidate\n---\n\n# Rule\n",
        )


def test_search_documents_returns_path_and_line_matches(tmp_path: Path):
    (tmp_path / "modules" / "core").mkdir(parents=True)
    (tmp_path / "modules" / "core" / "PAY.md").write_text(
        "# Payroll\n\nPreserve rounding behavior at month end.\n",
        encoding="utf-8",
    )
    (tmp_path / "mapping").mkdir()
    (tmp_path / "mapping" / "PAY.md").write_text(
        "# Payroll mapping\n",
        encoding="utf-8",
    )

    content_results = search_documents(tmp_path, "rounding month")
    path_results = search_documents(tmp_path, "pay", path_prefix="mapping")

    assert [(item.path, item.line) for item in content_results] == [
        ("modules/core/PAY.md", 3)
    ]
    assert path_results[0].path == "mapping/PAY.md"
    assert path_results[0].line == 0
