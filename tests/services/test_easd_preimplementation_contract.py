"""Authoring and planning need a contract too.

`build_easd_runtime_contract` requires an accepted specification, so the phases
that run before one exists were handed nothing. Measured consequence in a live
specify phase: the agent globbed `.local/runs/**/*.json` against a tree that
only holds YAML, probed the run directory by its bare id when the real name is
`<slug>--<run_id>`, and hunted for `pyproject.toml`, `setup.py`, `setup.cfg`
and `requirements*.txt` one at a time.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.models.trace import TraceRun
from app.services.easd_setup_service import EASD_MANIFEST
from app.services.trace_service import build_easd_preimplementation_contract


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def _run(workspace, **overrides) -> TraceRun:
    payload = {
        "id": uuid4(),
        "workspace": str(workspace),
        "title": "Implement per-client rate limiting",
        "status": "authoring",
        "risk_tier": "standard",
    }
    payload.update(overrides)
    return TraceRun(**payload)


def _write_manifest(workspace, data_directory="documents/easd"):
    path = workspace / EASD_MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"data_directory": data_directory}), encoding="utf-8")


class TestRunIdentity:
    def test_names_the_real_on_disk_run_directory(self, workspace):
        run = _run(workspace)
        block = build_easd_preimplementation_contract(run)
        assert (
            f".evoflux/easd/.local/runs/implement-per-client-rate-limiting--{run.id}"
            in block
        )

    def test_uses_posix_separators(self, workspace):
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "\\" not in block

    def test_states_the_phase_and_marks_risk_provisional(self, workspace):
        block = build_easd_preimplementation_contract(
            _run(workspace, status="planning")
        )
        assert "Phase: planning" in block
        assert "provisional" in block

    def test_tells_the_agent_not_to_probe(self, workspace):
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "Do not probe" in block


class TestKnowledgeBase:
    def test_names_the_configured_sections(self, workspace):
        _write_manifest(workspace)
        block = build_easd_preimplementation_contract(_run(workspace))
        for section in ("specs", "features", "architecture", "reference"):
            assert f"documents/easd/{section}/" in block

    def test_honours_a_custom_data_directory(self, workspace):
        _write_manifest(workspace, data_directory="docs/contracts")
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "docs/contracts/specs/" in block

    def test_says_run_state_is_yaml_not_json(self, workspace):
        _write_manifest(workspace)
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "no JSON documents" in block

    def test_a_missing_manifest_does_not_raise(self, workspace):
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "Run:" in block

    def test_a_corrupt_manifest_does_not_raise(self, workspace):
        path = workspace / EASD_MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "Run:" in block


class TestToolchain:
    @pytest.mark.parametrize(
        ("marker", "expected"),
        [
            ("pyproject.toml", "pyproject.toml"),
            ("package.json", "package.json"),
            ("Cargo.toml", "cargo"),
            ("go.mod", "go module"),
            ("Makefile", "make"),
        ],
    )
    def test_reports_what_the_repository_configures(self, workspace, marker, expected):
        (workspace / marker).write_text("", encoding="utf-8")
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "Detected toolchain:" in block
        assert expected in block

    def test_names_the_project_interpreter_first(self, workspace):
        interpreter = workspace / ".venv" / "bin" / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("", encoding="utf-8")
        (workspace / "pyproject.toml").write_text("", encoding="utf-8")
        block = build_easd_preimplementation_contract(_run(workspace))
        toolchain = block.split("Detected toolchain:", 1)[1]
        assert toolchain.strip().splitlines()[0].startswith("- project interpreter:")
        assert "a `python …` verification command resolves to this" in block

    def test_an_empty_repository_says_so_instead_of_staying_silent(self, workspace):
        block = build_easd_preimplementation_contract(_run(workspace))
        assert "none of the usual manifests are present" in block
