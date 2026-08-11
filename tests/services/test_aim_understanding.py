from pathlib import Path
from uuid import uuid7

import pytest
import yaml

from app.services.aim.kb_store import write_unit
from app.services.aim.understanding import (
    UnderstandingEvidenceError,
    has_understanding_evidence,
    snapshot_understanding,
    verify_understanding,
)


def _substantive_body(label: str = "unit") -> str:
    detail = (
        f"The {label} behavior is derived from cited source paths and preserves "
        "interfaces, error ordering, side effects, and externally visible state. "
    )
    return (
        f"# {label}\n\n## Purpose\n\n{detail * 4}\n\n"
        f"## Control flow and interfaces\n\n{detail * 4}\n\n"
        f"## Dependencies and ambiguities\n\n{detail * 4}\n"
    )


def test_verify_understanding_accepts_substantive_unchanged_review(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "API",
        kind="component",
        phase="inventory",
        body=_substantive_body("API contract"),
    )
    execution_id = str(uuid7())
    baseline = snapshot_understanding(tmp_path, ["core/API"])

    paths = verify_understanding(
        tmp_path,
        ["core/API"],
        baseline,
        execution_id=execution_id,
    )

    evidence = yaml.safe_load(paths[0].read_text())
    assert evidence["change_kind"] == "reviewed_unchanged"
    assert evidence["quality"]["substantive"] is True
    assert has_understanding_evidence(tmp_path, "core/API", execution_id)


def test_verify_understanding_rejects_unchanged_stub(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "API",
        kind="component",
        phase="inventory",
        body="# API\n\n## Purpose\n\nShort assessment stub.",
    )
    baseline = snapshot_understanding(tmp_path, ["core/API"])

    with pytest.raises(UnderstandingEvidenceError, match="still a stub"):
        verify_understanding(
            tmp_path,
            ["core/API"],
            baseline,
            execution_id=str(uuid7()),
        )


def test_understanding_evidence_invalidates_after_document_changes(tmp_path: Path):
    write_unit(
        tmp_path,
        "core",
        "API",
        kind="component",
        phase="inventory",
        body=_substantive_body("API contract"),
    )
    execution_id = str(uuid7())
    baseline = snapshot_understanding(tmp_path, ["core/API"])
    verify_understanding(
        tmp_path,
        ["core/API"],
        baseline,
        execution_id=execution_id,
    )
    write_unit(tmp_path, "core", "API", body=_substantive_body("Changed API"))

    assert not has_understanding_evidence(tmp_path, "core/API", execution_id)
