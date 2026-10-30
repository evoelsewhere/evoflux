from pathlib import Path

import pytest

from scripts.migration import check_paths

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "scripts" / "migration"

BOARD = """# Board
| lane | status |
| --- | --- |
| quote | open |
| other | open |
"""
CHANGELOG = """# Changelog
## [Unreleased]
### Changed
- existing
## [1.0.0] - 2026-01-01
- released
"""


def test_changelog_addition_only_under_unreleased():
    assert check_paths.valid_changelog(
        CHANGELOG, CHANGELOG.replace("- existing\n", "- existing\n- added\n")
    )


def test_changelog_rejects_released_or_modified_lines():
    assert not check_paths.valid_changelog(
        CHANGELOG, CHANGELOG.replace("- released", "- changed")
    )
    assert not check_paths.valid_changelog(
        CHANGELOG, CHANGELOG.replace("- existing", "- changed")
    )
    assert not check_paths.valid_changelog(
        CHANGELOG, CHANGELOG + "- new release item\n"
    )


def test_board_own_row_only():
    assert check_paths.valid_board_change(
        BOARD, BOARD.replace("| quote | open |", "| quote | claimed |"), "quote"
    )


def test_board_rejects_other_row_and_prose():
    assert not check_paths.valid_board_change(
        BOARD, BOARD.replace("| other | open |", "| other | claimed |"), "quote"
    )
    assert not check_paths.valid_board_change(
        BOARD, BOARD.replace("# Board", "# Other"), "quote"
    )
    assert not check_paths.valid_board_change(
        BOARD, BOARD.replace("| lane | status |", "| lane | state |"), "quote"
    )


def test_owned_path():
    assert check_paths.allowed_path(
        "server/crates/area-quote/src/lib.rs", ["server/crates/area-quote/**"]
    )
    assert not check_paths.allowed_path(
        "server/crates/area-other/src/lib.rs", ["server/crates/area-quote/**"]
    )


def _row(lane: str, owned: str, status: str) -> dict[str, str]:
    return {"lane": lane, "owned_paths": owned, "status": status}


@pytest.fixture
def check_board_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MIGRATION_DIR))


def test_path_contested_by_open_row_is_rejected(check_board_on_path: None) -> None:
    rows = [
        _row("quote", "server/crates/area-quote/**", "open"),
        _row("gateway", "contract-tests/gateway/**", "open"),
    ]

    assert check_paths.contested_by_others(
        "contract-tests/gateway/test_remote_claim.py", rows, "quote"
    )


def test_path_released_by_merged_row_is_allowed(check_board_on_path: None) -> None:
    rows = [
        _row("quote", "server/crates/area-quote/**", "open"),
        _row("gateway", "contract-tests/gateway/**", "merged"),
    ]

    assert not check_paths.contested_by_others(
        "contract-tests/gateway/test_remote_claim.py", rows, "quote"
    )


def test_workflow_requires_no_new_python_gate_failures():
    from pathlib import Path

    workflow = (Path(__file__).resolve().parents[2] / "server" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "no new failures compared with the base branch" in workflow


UNITS = """| unit | phase | adapter_call_sites | what it holds |
|---|---|---|---|
| `edge-stateless` | 1 | `app/api/routes/quote.py`, `app/services/quote_*.py` | x |
| `import` | 2 | - | y |
"""


def test_unit_call_sites():
    assert check_paths.unit_call_sites(UNITS, "edge-stateless") == [
        "app/api/routes/quote.py",
        "app/services/quote_*.py",
    ]
    assert check_paths.unit_call_sites(UNITS, "import") == []
    assert check_paths.unit_call_sites(UNITS, "nope") is None


def test_cutover_allows_declared_paths():
    sites = ["app/api/routes/quote.py", "app/services/quote_*.py"]
    for path in (
        "server/routing.toml",
        "app/core/rust_bridge/edge_stateless.py",
        "app/services/quote_service.py",
        "contract-tests/edge-stateless/test_quote.py",
    ):
        assert check_paths.cutover_allowed(path, "edge-stateless", sites), path


def test_cutover_rejects_everything_else():
    sites = ["app/api/routes/quote.py"]
    for path in (
        "app/api/routes/health.py",
        "app/core/rust_bridge/import_.py",
        "app/core/rust_bridge/other.py",
        "contract-tests/import/test_x.py",
        "server/crates/gateway/src/lib.rs",
        "server/MIGRATION_BOARD.md",
    ):
        assert not check_paths.cutover_allowed(path, "edge-stateless", sites), path
    assert not check_paths.cutover_allowed("app/api/routes/quote.py", "import", [])


def test_cutover_changelog_still_unreleased_only():
    assert not check_paths.valid_changelog(
        CHANGELOG, CHANGELOG.replace("- released", "- changed")
    )


def test_explicit_push_base_used_for_diff_and_changelog(monkeypatch, capsys):
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args[:2] == ("diff", "--name-only"):
            return "CHANGELOG.md\n"
        if args[0] == "show":
            return (
                CHANGELOG
                if args[1].startswith("before:")
                else CHANGELOG.replace("- existing\n", "- existing\n- added\n")
            )
        raise AssertionError(args)

    monkeypatch.setenv("GATES_DIFF_BASE", "before")
    monkeypatch.setattr(check_paths, "git", fake_git)
    monkeypatch.setattr(check_paths.sys, "argv", ["check_paths.py", "shared"])
    assert check_paths.main() == 0
    assert ("diff", "--name-only", "before..HEAD") in calls
    assert ("show", "before:CHANGELOG.md") in calls
    assert "CHANGELOG.md" in capsys.readouterr().out
