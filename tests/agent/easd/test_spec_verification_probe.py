"""The runtime, not the authoring agent, measures verification commands.

Authoring is deliberately read-only, so the agent cannot execute anything.
Demanding execution evidence from it produced an unsatisfiable gate: the agent
looped between "the runtime blocks shell" and "the validator requires execution
evidence", and its only escape was to drop the commands entirely — which then
tripped the machine-required rule. The runtime runs them instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.agent.verification import (
    probe_verification_commands,
    project_interpreter,
)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return root


class TestProjectInterpreter:
    def test_returns_none_without_a_virtualenv(self, project):
        assert project_interpreter(project) is None

    @pytest.mark.parametrize(
        ("directory", "binary", "name"),
        [
            (".venv", "Scripts", "python.exe"),
            (".venv", "bin", "python"),
            ("venv", "bin", "python3"),
        ],
    )
    def test_finds_a_project_local_interpreter(self, project, directory, binary, name):
        target = project / directory / binary / name
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        found = project_interpreter(project)
        assert found is not None
        assert found.name == name

    def test_prefers_the_project_over_the_server_interpreter(self, project):
        target = project / ".venv" / "bin" / "python"
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        assert str(project_interpreter(project)) != sys.executable


class TestProbing:
    @pytest.mark.asyncio
    async def test_no_commands_produces_no_probes(self, project):
        assert await probe_verification_commands(project, []) == []

    @pytest.mark.asyncio
    async def test_a_passing_command_reports_exit_zero(self, project):
        results = await probe_verification_commands(
            project, ["python -m compileall -q tests"]
        )
        assert len(results) == 1
        command, exit_code, _detail = results[0]
        assert command == "python -m compileall -q tests"
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_a_failing_command_reports_a_nonzero_exit(self, project):
        (project / "tests" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        results = await probe_verification_commands(
            project, ["python -m compileall -q tests"]
        )
        assert results[0][1] != 0

    @pytest.mark.asyncio
    async def test_an_unapproved_command_is_reported_not_executed(self, project):
        results = await probe_verification_commands(project, ["rm -rf /"])
        command, exit_code, detail = results[0]
        assert command == "rm -rf /"
        assert exit_code == 126
        assert "not an approved command" in detail

    @pytest.mark.asyncio
    async def test_shell_composition_is_refused(self, project):
        results = await probe_verification_commands(
            project, ["python -m compileall tests && echo done"]
        )
        assert results[0][1] == 126

    @pytest.mark.asyncio
    async def test_every_command_gets_exactly_one_result(self, project):
        commands = [
            "python -m compileall -q tests",
            "rm -rf /",
            "python -m compileall -q tests",
        ]
        results = await probe_verification_commands(project, commands)
        assert [item[0] for item in results] == commands

    @pytest.mark.asyncio
    async def test_a_missing_program_is_reported_not_raised(self, project):
        results = await probe_verification_commands(project, ["cargo check"])
        # Either the program is absent (127) or cargo really runs and fails
        # in a directory with no manifest; neither may raise.
        assert results[0][1] != 0

    @pytest.mark.asyncio
    async def test_the_probe_runs_in_the_given_workspace(self, project):
        outside = project.parent / "elsewhere"
        outside.mkdir()
        # `tests` exists only inside `project`, so resolving the cwd wrongly
        # would surface as a non-zero exit.
        results = await probe_verification_commands(
            project, ["python -m compileall -q tests"]
        )
        assert results[0][1] == 0
        assert Path(project).is_dir()


class TestProbeDetailReadability:
    """Probe detail lands in the YAML evidence ledger a person has to read."""

    def test_terminal_colouring_is_stripped(self):
        from app.agent.verification import _ANSI_ESCAPE

        coloured = (
            "\x1b[1m\x1b[31mFAILED\x1b[0m tests/test_rate.py::"
            "\x1b[1mtest_eleventh_request_is_rejected\x1b[0m - NotImplementedError"
        )
        assert _ANSI_ESCAPE.sub("", coloured) == (
            "FAILED tests/test_rate.py::test_eleventh_request_is_rejected"
            " - NotImplementedError"
        )

    def test_ordinary_brackets_survive(self):
        from app.agent.verification import _ANSI_ESCAPE

        for text in ("list[int]", "dict[str, int]", "arr[0][1]", "a [b] c"):
            assert _ANSI_ESCAPE.sub("", text) == text

    @pytest.mark.asyncio
    async def test_probe_detail_carries_no_escape_codes(self, project):
        (project / "tests" / "test_fails.py").write_text(
            "def test_fails():\n    assert False\n", encoding="utf-8"
        )
        results = await probe_verification_commands(
            project, ["python -m compileall -q tests"]
        )
        assert "\x1b" not in results[0][2]
