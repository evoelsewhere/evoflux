"""Tests for prompt-snippet discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.snippets import discover_snippets


@pytest.fixture
def roots(tmp_path: Path, monkeypatch):
    cwd = tmp_path / "project"
    cwd.mkdir()
    project = cwd / ".evoflux" / "snippets"
    global_config = tmp_path / "config"
    global_root = global_config / "snippets"

    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings, "EVOFLUX_CONFIG_DIR", str(global_config)
    )
    return cwd, project, global_root


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


VALID = """\
---
description: Review staged changes.
---
Review the current diff.
"""


def test_discover_snippets_requires_workspace_and_finds_project_and_global(roots):
    cwd, project, global_root = roots
    _write(project / "review.md", VALID)
    _write(global_root / "explain.md", "Explain this code.\n")

    result = discover_snippets(cwd)

    assert set(result.keys()) == {"review", "explain"}
    assert result["review"].source == "project-EvoFlux"
    assert result["review"].description == "Review staged changes."
    assert result["explain"].source == "global-EvoFlux"
    assert result["explain"].body == "Explain this code."


def test_project_snippet_wins_over_global(roots):
    cwd, project, global_root = roots
    _write(project / "review.md", "project body\n")
    _write(global_root / "review.md", "global body\n")

    result = discover_snippets(cwd)

    assert result["review"].source == "project-EvoFlux"
    assert result["review"].body == "project body"


def test_nested_snippet_names_use_slash(roots):
    cwd, project, _ = roots
    _write(project / "git" / "commit.md", VALID)

    result = discover_snippets(cwd)

    assert set(result.keys()) == {"git/commit"}
