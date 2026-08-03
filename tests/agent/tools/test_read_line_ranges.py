"""Line-numbering consistency tests for the ``read`` tool.

``read`` numbers lines with ``str.split("\\n")`` on the unpaginated path but
sliced the file with ``str.splitlines(keepends=True)`` on the offset/limit
path. ``splitlines`` also breaks on ``\\x0b``, ``\\x0c``, ``\\x1c``-``\\x1e``,
``\\x85``, ``U+2028`` and ``U+2029``, so the two paths disagreed about which
line is line N for any file containing one of those characters — including
every binary file read through the latin-1 fallback.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.tools.builtin.filesystem.read import _read_file


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    set_sandbox(SandboxConfig(workspace=str(root), denied_roots=[], denied_patterns=[]))
    return root


def _numbered(output: str) -> dict[int, str]:
    """Parse ``NNNNN| body`` rows out of a read result into {line_no: body}."""
    body = output.split("\n", 1)[1] if output.startswith("[") else output
    rows: dict[int, str] = {}
    for row in body.split("\n"):
        m = re.match(r"^(\d{5})\| (.*)$", row)
        if m:
            rows[int(m.group(1))] = m.group(2)
    return rows


def _header_total(output: str) -> int:
    m = re.match(r"^\[(\d+)-(\d+)/(\d+)\]", output)
    assert m is not None, output
    return int(m.group(3))


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("form_feed", b"L1\nL2\x0cL3\nL4\nL5\n"),
        ("vertical_tab", b"L1\nL2\x0bL3\nL4\nL5\n"),
        ("group_separator", b"L1\nL2\x1dL3\nL4\nL5\n"),
        ("next_line_latin1", b"\xffL1\nL2\x85L3\nL4\nL5\n"),
        ("line_separator", "L1\nL2\u2028L3\nL4\nL5\n".encode("utf-8")),
    ],
)
async def test_paginated_lines_match_unpaginated(
    workspace: Path, name: str, payload: bytes
) -> None:
    """offset/limit must address the same lines the unpaginated read numbers."""
    target = workspace / f"{name}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    full = _numbered(await _read_file(f"{name}.txt"))
    assert len(full) == 4, full

    paged_output = await _read_file(f"{name}.txt", offset=1, limit=99)
    assert _header_total(paged_output) == len(full)
    assert _numbered(paged_output) == full

    for line_no, body in full.items():
        one = await _read_file(f"{name}.txt", offset=line_no, limit=1)
        assert _numbered(one) == {line_no: body}, (line_no, one)


async def test_crlf_offsets_are_line_based(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "crlf.txt").write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")

    assert _numbered(await _read_file("crlf.txt")) == {
        1: "alpha",
        2: "beta",
        3: "gamma",
    }
    out = await _read_file("crlf.txt", offset=2, limit=1)
    assert out.startswith("[2-2/3]\n")
    assert _numbered(out) == {2: "beta"}


async def test_lone_cr_offsets_are_line_based(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "cr.txt").write_bytes(b"one\rtwo\rthree\r")

    assert _numbered(await _read_file("cr.txt")) == {1: "one", 2: "two", 3: "three"}
    out = await _read_file("cr.txt", offset=3, limit=1)
    assert out.startswith("[3-3/3]\n")
    assert _numbered(out) == {3: "three"}


async def test_file_without_trailing_newline_keeps_last_line(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "noeol.txt").write_bytes(b"first\nsecond")

    full = _numbered(await _read_file("noeol.txt"))
    assert full == {1: "first", 2: "second"}

    out = await _read_file("noeol.txt", offset=1, limit=99)
    assert _header_total(out) == 2
    assert _numbered(out) == full
