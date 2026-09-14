from __future__ import annotations

from pathlib import Path

import pytest

from app.services.problems_service import (
    ProblemError,
    ProblemInput,
    clear_problems,
    dismiss_problem,
    list_problems,
    publish_problems,
    restore_problem,
    suppress_problem,
    suppression_blast_radius,
)


@pytest.fixture(autouse=True)
def _clear():
    clear_problems()
    yield
    clear_problems()


def test_scope_replacement_and_severity_order(tmp_path: Path):
    publish_problems(
        tmp_path,
        source="lsp",
        scope="lsp:main.py",
        problems=[
            ProblemInput(message="warning", severity="warning", path="main.py"),
            ProblemInput(message="error", severity="error", path="main.py"),
        ],
    )
    assert [row.message for row in list_problems(tmp_path)] == ["error", "warning"]

    publish_problems(
        tmp_path,
        source="lsp",
        scope="lsp:main.py",
        problems=[ProblemInput(message="new", severity="info", path="main.py")],
    )

    assert [row.message for row in list_problems(tmp_path)] == ["new"]


def test_dismiss_and_suppress_are_preserved_on_republish(tmp_path: Path):
    rows = publish_problems(
        tmp_path,
        source="ai_review",
        scope="review:head",
        problems=[
            ProblemInput(message="one", code="rule-one"),
            ProblemInput(message="two", code="rule-two"),
        ],
    )
    dismiss_problem(tmp_path, rows[0].id)
    suppress_problem(tmp_path, rows[1].id)

    assert list_problems(tmp_path) == []
    all_rows = list_problems(tmp_path, include_resolved=True)
    assert {row.status for row in all_rows} == {"dismissed", "suppressed"}

    publish_problems(
        tmp_path,
        source="ai_review",
        scope="review:head",
        problems=[
            ProblemInput(message="one", code="rule-one"),
            ProblemInput(message="two", code="rule-two"),
        ],
    )
    assert {row.status for row in list_problems(tmp_path, include_resolved=True)} == {
        "dismissed",
        "suppressed",
    }


def test_problem_path_must_stay_inside_repository(tmp_path: Path):
    with pytest.raises(ProblemError, match="escapes"):
        publish_problems(
            tmp_path,
            source="security",
            scope="security:scan",
            problems=[ProblemInput(message="outside", path="../outside.py")],
        )


def test_supersedes_prefix_retires_sibling_scopes(tmp_path: Path):
    """A per-run scope must not strand the previous run's findings.

    Producers that hash a command or a content digest into the scope land
    every run in a scope of its own, so the plain same-scope sweep never
    reaches the run before it.
    """
    publish_problems(
        tmp_path,
        source="test",
        scope="shell:test:aaaa",
        problems=[ProblemInput(message="boom", path="a.py", line=1)],
        supersedes_prefix="shell:test:",
    )
    assert len(list_problems(tmp_path)) == 1

    publish_problems(
        tmp_path,
        source="test",
        scope="shell:test:bbbb",
        problems=[],
        supersedes_prefix="shell:test:",
    )
    assert list_problems(tmp_path) == []


def test_supersedes_prefix_leaves_other_sources_alone(tmp_path: Path):
    publish_problems(
        tmp_path,
        source="lsp",
        scope="lsp:a.py",
        problems=[ProblemInput(message="kept", path="a.py", line=1)],
    )
    publish_problems(
        tmp_path,
        source="test",
        scope="shell:test:bbbb",
        problems=[],
        supersedes_prefix="shell:test:",
    )
    assert [row.message for row in list_problems(tmp_path)] == ["kept"]


def test_restore_reopens_a_dismissed_problem(tmp_path: Path):
    rows = publish_problems(
        tmp_path,
        source="lsp",
        scope="lsp:a.py",
        problems=[ProblemInput(message="boom", path="a.py", line=1)],
    )
    dismiss_problem(tmp_path, rows[0].id)
    assert list_problems(tmp_path) == []

    restore_problem(tmp_path, rows[0].id)
    assert [row.message for row in list_problems(tmp_path)] == ["boom"]


def test_restore_lifts_the_whole_suppression(tmp_path: Path):
    """Suppression is workspace-wide, so undoing it has to be too."""
    rows = publish_problems(
        tmp_path,
        source="static",
        scope="static:ruff:a.py",
        problems=[
            ProblemInput(message="unused", path="a.py", line=1, code="F401"),
            ProblemInput(message="unused", path="b.py", line=9, code="F401"),
        ],
    )
    suppress_problem(tmp_path, rows[0].id)
    assert list_problems(tmp_path) == []

    restore_problem(tmp_path, rows[0].id)
    assert len(list_problems(tmp_path)) == 2

    # A later run of the same producer must not re-suppress them.
    publish_problems(
        tmp_path,
        source="static",
        scope="static:ruff:a.py",
        problems=[ProblemInput(message="unused", path="a.py", line=1, code="F401")],
    )
    assert len(list_problems(tmp_path)) == 1


def test_suppression_blast_radius_counts_what_would_vanish(tmp_path: Path):
    rows = publish_problems(
        tmp_path,
        source="static",
        scope="static:ruff:a.py",
        problems=[
            ProblemInput(message="unused", path="a.py", line=1, code="F401"),
            ProblemInput(message="unused", path="b.py", line=9, code="F401"),
            ProblemInput(message="long line", path="c.py", line=3, code="E501"),
        ],
    )
    assert suppression_blast_radius(tmp_path, rows[0].id) == 2
