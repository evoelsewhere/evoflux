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
    suppress_problem,
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
