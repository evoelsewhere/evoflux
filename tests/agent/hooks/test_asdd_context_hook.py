"""What an agent is told about the catalogue before it writes into it.

The block is the only place an agent learns the layout without probing, so it
has to name every directory the layout has. A directory the block omits is one
an agent will either not use or fill with the wrong kind of page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.hooks.asdd_context import AsddContextHook
from app.services.asdd_setup_service import AsddRepositoryTarget, initialize_repositories


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repositories(
        [AsddRepositoryTarget(path=str(root), name="repo", display_name="Repo")]
    )
    return root


def block(root: Path) -> str:
    hook = AsddContextHook(workspace=str(root), agent_name="coder", role="builder")
    summary = hook._read_catalogue()
    assert summary is not None
    return summary[0]


def test_the_block_names_every_durable_home(repository: Path) -> None:
    text = block(repository)

    for directory in (
        "specs/<capability>/spec.md",
        "architecture/",
        "architecture/decisions/",
        "reference/",
        "analysis/",
        "changes/<change-id>/",
    ):
        assert directory in text, f"context block does not name {directory}"


def test_the_block_sends_the_agent_to_each_directory_s_own_rules(
    repository: Path,
) -> None:
    """Saying a directory exists is not saying what belongs in it."""
    assert "README.md" in block(repository)


def test_a_repository_without_asdd_gets_no_block(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    hook = AsddContextHook(workspace=str(root), agent_name="coder", role="builder")

    assert hook._read_catalogue() is None
