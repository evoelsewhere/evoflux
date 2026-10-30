import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "migration" / "openapi_diff.py"
)
COLUMNS = (
    "| lane | unit | python_sources | routes | owned_paths | status "
    "| claimed_by | updated | gate_report |"
)


def board_with(tmp_path: Path, routes: str) -> Path:
    row = (
        f"| quote | edge-stateless | `-` | {routes} | `server/crates/area-quote/**` "
        "| open | - | 2026-10-30 | - |"
    )
    path = tmp_path / "board.md"
    path.write_text(
        "\n".join([COLUMNS, "|---|---|---|---|---|---|---|---|---|", row, ""]),
        encoding="utf-8",
    )
    return path


def spec(tmp_path: Path, name: str, op: str) -> Path:
    path = tmp_path / name
    paths = {"/api/quote/today": {"get": {"operationId": op}}, "/api/x": {}}
    path.write_text(json.dumps({"paths": paths}), encoding="utf-8")
    return path


def run(tmp_path: Path, board: Path, candidate: Path, lane: str = "quote"):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            lane,
            "--board",
            str(board),
            "--candidate",
            str(candidate),
            "--pinned",
            str(tmp_path / "pinned.json"),
        ],
        capture_output=True,
        text=True,
    )


def test_routes_come_from_board_row(tmp_path):
    spec(tmp_path, "pinned.json", "q")
    board = board_with(tmp_path, "`/api/quote/**`")
    assert run(tmp_path, board, spec(tmp_path, "c.json", "q")).returncode == 0


def test_difference_in_owned_routes_fails(tmp_path):
    spec(tmp_path, "pinned.json", "q")
    board = board_with(tmp_path, "`/api/quote/**`")
    assert run(tmp_path, board, spec(tmp_path, "c.json", "other")).returncode == 1


def test_unowned_difference_is_ignored_and_unknown_lane_errors(tmp_path):
    pinned = spec(tmp_path, "pinned.json", "q")
    board = board_with(tmp_path, "`/api/quote/**`")
    candidate = json.loads(pinned.read_text(encoding="utf-8"))
    candidate["paths"]["/api/x"] = {"get": {}}
    cand = tmp_path / "c2.json"
    cand.write_text(json.dumps(candidate), encoding="utf-8")
    assert run(tmp_path, board, cand).returncode == 0
    assert run(tmp_path, board, cand, lane="nope").returncode != 0


@pytest.mark.parametrize("routes", ["-", " "])
def test_lane_without_routes_errors(tmp_path, routes):
    spec(tmp_path, "pinned.json", "q")
    board = board_with(tmp_path, routes)
    assert run(tmp_path, board, spec(tmp_path, "c.json", "q")).returncode != 0
