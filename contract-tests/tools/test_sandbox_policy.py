"""Saved policy regressions; Python validates the policy and explicit paths.

Discovery filtering is separately pinned as ticket-authorized Rust hardening:
Python's ls/glob/grep scans do not consult denied_patterns on each entry.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import runner


def call(target, workspace, config, tool, args):
    request = {
        "workspace": str(workspace),
        "config_dir": str(config),
        "cases": [{"tool": tool, "args": args}],
    }
    command = (
        [
            "cargo",
            "run",
            "--quiet",
            "--manifest-path",
            str(runner.ROOT / "server/Cargo.toml"),
            "-p",
            "evoflux-area-tools",
            "--example",
            "run_cases",
        ]
        if target == "rust"
        else [sys.executable, str(runner.HERE / "py_driver.py")]
    )
    done = subprocess.run(
        command,
        input=json.dumps(request).encode(),
        capture_output=True,
        cwd=runner.ROOT,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(done.stdout)[0]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("read", {"path": "secret.txt"}),
        ("ls", {"path": "secrets"}),
        ("glob", {"pattern": "*", "directory": "secrets"}),
        ("grep", {"pattern": "payload", "directory": "secrets"}),
    ],
)
def test_saved_patterns_deny_explicit_paths(target, tmp_path, tool, args):
    ws = tmp_path / "ws"
    (ws / "secrets").mkdir(parents=True)
    (ws / "secret.txt").write_text("payload")
    (tmp_path / "sandbox.yaml").write_text("denied_patterns: ['**/secret*', '  ']\n")
    out = call(target, ws, tmp_path, tool, args)
    assert out["is_error"]
    assert "is inside a denied sandbox root: **/secret*" in out["content"]
    assert "payload" not in out["content"]


@pytest.mark.parametrize("mode", ["path", "name"])
def test_rust_glob_filters_denied_hits(target, tmp_path, mode):
    if target != "rust":
        pytest.skip("DS3-003 Rust hardening: Python only validates the search root")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ok.txt").write_text("ok")
    (ws / "secret.txt").write_text("hidden")
    (tmp_path / "sandbox.yaml").write_text("denied_patterns: ['**/secret*']\n")
    out = call(target, ws, tmp_path, "glob", {"pattern": "*.txt", "match": mode})
    assert out == {"content": "ok.txt", "is_error": False}


def test_rust_listing_hides_outside_junction_targets(target, tmp_path):
    if target != "rust":
        pytest.skip("DS3-004 Rust hardening: Python exposes outside-link metadata")
    workspace = runner.Workspace(
        tmp_path,
        {
            "files": {"ok.txt": {"text": "ok"}},
            "dirs": [],
            "links": [{"path": "out", "target": "<OUT>"}],
        },
        {"id_rsa": "private"},
    )
    if not workspace.links_ok:
        pytest.skip("cannot create a workspace directory link")
    assert call(target, workspace.ws, tmp_path, "ls", {}) == {
        "content": "[f] ok.txt  (2 bytes)",
        "is_error": False,
    }
    for pattern in ["**/*", "out/*", "*/id_rsa"]:
        out = call(target, workspace.ws, tmp_path, "glob", {"pattern": pattern})
        assert not out["is_error"]
        if pattern == "**/*":
            assert out["content"] == "ok.txt"
        else:
            assert out["content"].startswith("No files matching")
