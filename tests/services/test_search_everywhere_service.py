from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.problems_service import ProblemInput, clear_problems, publish_problems
from app.services.search_everywhere_service import (
    SearchEverywhereItem,
    search_everywhere,
)


@pytest.mark.asyncio
async def test_search_aggregates_repository_paths_and_problems(tmp_path: Path):
    source = tmp_path / "app/services/auth_service.py"
    source.parent.mkdir(parents=True)
    source.write_text("def authenticate(): ...\n", encoding="utf-8")
    publish_problems(
        tmp_path,
        source="security",
        scope="security:review",
        problems=[
            ProblemInput(
                title="Auth callback risk",
                message="Validate callback URL",
                path="app/services/auth_service.py",
                code="SSRF",
            )
        ],
    )
    empty_async = AsyncMock(return_value=[])
    with (
        patch("app.services.search_everywhere_service._git_items", empty_async),
        patch("app.services.search_everywhere_service._skill_items", return_value=[]),
        patch(
            "app.services.search_everywhere_service._workflow_items", return_value=[]
        ),
    ):
        path_rows = await search_everywhere(tmp_path, "auth_service")
        problem_rows = await search_everywhere(tmp_path, "callback")

    assert any(
        item.kind == "file" and item.path == "app/services/auth_service.py"
        for item in path_rows
    )
    file_row = next(item for item in path_rows if item.kind == "file")
    assert file_row.metadata is not None
    assert file_row.metadata["size"] == source.stat().st_size
    assert file_row.metadata["mtime"] == source.stat().st_mtime
    assert file_row.metadata["mime"] == "text/x-python"
    assert any(
        item.kind == "problem" and item.path == "app/services/auth_service.py"
        for item in problem_rows
    )
    clear_problems()


@pytest.mark.asyncio
async def test_search_deduplicates_and_respects_global_limit(tmp_path: Path):
    duplicate = SearchEverywhereItem(
        id="file:app.py",
        kind="file",
        label="app.py",
        description="file",
        path="app.py",
    )
    async_rows = AsyncMock(return_value=[duplicate, duplicate])
    with (
        patch("app.services.search_everywhere_service._git_items", async_rows),
        patch(
            "app.services.search_everywhere_service._path_items",
            return_value=[duplicate],
        ),
        patch("app.services.search_everywhere_service._problem_items", return_value=[]),
        patch("app.services.search_everywhere_service._skill_items", return_value=[]),
        patch(
            "app.services.search_everywhere_service._workflow_items", return_value=[]
        ),
    ):
        rows = await search_everywhere(tmp_path, "app", limit=1)

    assert rows == [duplicate]


def test_skill_items_insert_dollar_mentions_for_user_invocable_skills(tmp_path: Path):
    from app.agent.skills.registry import invalidate_skill_cache
    from app.services.search_everywhere_service import _skill_items

    skills_root = tmp_path / ".evoflux" / "skills"
    for name, extra in (
        ("zq-release-audit", ""),
        ("zq-release-hidden", "user-invocable: false\n"),
    ):
        (skills_root / name).mkdir(parents=True)
        (skills_root / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Audits a zq release.\n{extra}---\n\n"
            "Audit it.\n",
            encoding="utf-8",
        )
    invalidate_skill_cache()

    rows = _skill_items(tmp_path, "zq-release", 10)

    assert rows == [
        SearchEverywhereItem(
            id="skill:zq-release-audit",
            kind="skill",
            label="zq-release-audit",
            description="Audits a zq release.",
            metadata={"name": "zq-release-audit", "insert_text": "$zq-release-audit "},
        )
    ]
