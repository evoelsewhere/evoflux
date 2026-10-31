import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "migration" / "checkpoint_lib.py"
spec = importlib.util.spec_from_file_location("checkpoint_lib", SCRIPT)
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


def test_override_routes_every_ready_unit_to_rust():
    assert lib.build_override(["edge-stateless", "observability"]) == (
        "edge-stateless=rust,observability=rust"
    )


def test_explicit_override_is_appended_last_so_it_wins():
    assert lib.build_override(
        ["edge-stateless", "import"], "edge-stateless=python"
    ) == ("edge-stateless=rust,import=rust,edge-stateless=python")


def test_empty_list_gives_only_the_explicit_override():
    assert lib.build_override([]) == ""
    assert lib.build_override([], "import=rust") == "import=rust"


def test_bad_unit_names_are_rejected():
    with pytest.raises(ValueError):
        lib.build_override(["bad,unit"])


def test_read_rust_ready(tmp_path):
    path = tmp_path / "rust-ready.toml"
    path.write_text('# comment\nunits = ["edge-stateless"]\n', encoding="utf-8")
    assert lib.read_rust_ready(path) == ["edge-stateless"]
    path.write_text("units = []\n", encoding="utf-8")
    assert lib.read_rust_ready(path) == []
    path.write_text("other = 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        lib.read_rust_ready(path)


def test_parse_counts_playwright_and_pytest():
    playwright = "  1 skipped\n  8 passed (1.6m)\n"
    assert lib.parse_counts("playwright", playwright) == {
        "passed": 8,
        "failed": 0,
        "skipped": 1,
    }
    failing = "  2 failed\n    e2e\\a.spec.ts:1:1 › x\n  6 passed (1.0m)\n"
    assert lib.parse_counts("playwright", failing)["failed"] == 2
    pytest_out = "== 3 failed, 120 passed, 4 skipped in 20.01s =="
    assert lib.parse_counts("pytest", pytest_out) == {
        "passed": 120,
        "failed": 3,
        "skipped": 4,
    }
    assert lib.parse_counts("pytest", "no summary here") == {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }


def test_extract_failures():
    out = "FAILED contract-tests/a.py::test_x - assert 1\n  ok 1 fine\n"
    assert lib.extract_failures("pytest", out) == [
        "FAILED contract-tests/a.py::test_x - assert 1"
    ]
    pw = "  x  1 e2e\\smoke\\a.spec.ts:3:1 › journey (1s)\n  ok 2 e2e\\smoke\\b.spec.ts › fine\n"
    assert lib.extract_failures("playwright", pw) == [
        "x  1 e2e\\smoke\\a.spec.ts:3:1 › journey (1s)"
    ]


def _step(name, exit_code, **counts):
    return {
        "name": name,
        "exit_code": exit_code,
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "failures": counts.get("failures", []),
    }


def test_report_lists_commit_units_counts_and_failures():
    text = lib.render_report(
        phase="p1-smoke",
        commit="abc1234",
        date="2026-10-31",
        units=["edge-stateless"],
        steps=[
            _step("e2e default", 0, passed=8, skipped=1),
            _step(
                "contract gateway", 1, passed=100, failed=2, failures=["FAILED a::b"]
            ),
        ],
    )
    assert "automated: not owner use" in text
    assert "abc1234" in text
    assert "edge-stateless" in text
    assert "| e2e default | PASS | 8 | 0 | 1 |" in text
    assert "| contract gateway | FAIL | 100 | 2 | 0 |" in text
    assert "FAILED a::b" in text
    assert "**Result: FAIL**" in text


def test_report_with_no_units_and_no_failures():
    text = lib.render_report(
        phase="p1-smoke",
        commit="abc1234",
        date="2026-10-31",
        units=[],
        steps=[_step("e2e default", 0, passed=1)],
    )
    assert "no Rust-ready units yet" in text
    assert "**Result: PASS**" in text
    assert "No failures." in text


def test_overall_exit_code_is_nonzero_on_any_failed_step():
    assert lib.overall_exit([_step("a", 0), _step("b", 0)]) == 0
    assert lib.overall_exit([_step("a", 0), _step("b", 3)]) == 1


def test_cli_override_prints_string_and_notice_for_empty_list(tmp_path):
    ready = tmp_path / "rust-ready.toml"
    ready.write_text("units = []\n", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "override", "--ready", str(ready)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout == ""
    assert "no Rust-ready units yet" in done.stderr
    ready.write_text('units = ["a-unit"]\n', encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "override",
            "--ready",
            str(ready),
            "--explicit",
            "a-unit=python",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "a-unit=rust,a-unit=python"


def test_cli_report_writes_file_and_exits_nonzero_on_failure(tmp_path):
    log = tmp_path / "e2e.log"
    log.write_text(
        "  x  1 e2e\\a.spec.ts › j\n  1 failed\n  2 passed (1s)\n", encoding="utf-8"
    )
    out = tmp_path / "report.md"
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "report",
            "--phase",
            "p1-smoke",
            "--commit",
            "abc1234",
            "--date",
            "2026-10-31",
            "--units",
            "",
            "--out",
            str(out),
            "--step",
            f"e2e default:1:playwright:{log}",
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1
    body = out.read_text(encoding="utf-8")
    assert "| e2e default | FAIL | 2 | 1 | 0 |" in body


def test_parse_step_allows_colons_in_names_and_windows_paths():
    assert lib.parse_step(r"contract subset: a::b:1:pytest:C:\tmp\x.log") == (
        "contract subset: a::b",
        1,
        "pytest",
        r"C:\tmp\x.log",
    )
    with pytest.raises(ValueError):
        lib.parse_step("garbage")


def test_parse_counts_pytest_without_summary_line_uses_progress_dots():
    out = "...F.s.E                                                    [100%]\n.\n"
    assert lib.parse_counts("pytest", out) == {"passed": 6, "failed": 2, "skipped": 1}
