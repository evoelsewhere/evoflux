"""Deterministic compare engine for AIM test-compare
(``documents/research/aim-framework.md`` §3.8).

Canonicalizes both sides first (see :mod:`app.services.aim.canonicalize`),
then diffs: JSON-aware with a configurable numeric tolerance and
sort-before-diff for unordered arrays, falling back to a canonicalized
line diff for non-JSON text. Compare is deliberately pure computation —
judgment about whether a diff is a real defect belongs to the
``aim-triage-analyst`` skill/agent, not this module.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.services.aim.canonicalize import canonicalize_text
from app.services.aim.models import CanonicalProfile

FileStatus = Literal["match", "diff", "missing", "extra"]


@dataclass
class FileDiff:
    path: str
    status: FileStatus
    detail: str = ""


@dataclass
class CompareReport:
    verdict: Literal["pass", "fail"]
    diff_count: int
    files: list[FileDiff] = field(default_factory=list)

    def to_dict(self) -> dict:
        """The tool-node output contract: a compact JSON-serializable dict
        so a Workflows tool node can template ``{{nodes.compare.output.verdict}}``.
        """
        return {
            "verdict": self.verdict,
            "diff_count": self.diff_count,
            "clusters": [
                {"path": f.path, "status": f.status, "detail": f.detail}
                for f in self.files
                if f.status != "match"
            ],
        }

    def to_markdown(self) -> str:
        lines = [f"# Compare report — verdict: {self.verdict}", ""]
        for f in self.files:
            lines.append(f"## {f.path} — {f.status}")
            if f.detail:
                lines.append("")
                lines.append("```")
                lines.append(f.detail)
                lines.append("```")
                lines.append("")
        return "\n".join(lines)


def _matches_any(rel_path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in globs)


def _numbers_close(a: Any, b: Any, tolerance: float) -> bool:
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(
        b, (int, float)
    ) and not isinstance(b, bool):
        return abs(float(a) - float(b)) <= tolerance
    return a == b


def _json_diff(a: Any, b: Any, tolerance: float, path: str = "$") -> list[str]:
    diffs: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                diffs.append(f"{path}.{key}: missing in expected, present in actual")
            elif key not in b:
                diffs.append(f"{path}.{key}: present in expected, missing in actual")
            else:
                diffs.extend(_json_diff(a[key], b[key], tolerance, f"{path}.{key}"))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: length {len(a)} != {len(b)}")
        else:
            for index, (x, y) in enumerate(zip(a, b)):
                diffs.extend(_json_diff(x, y, tolerance, f"{path}[{index}]"))
    elif not _numbers_close(a, b, tolerance):
        diffs.append(f"{path}: expected={a!r} actual={b!r}")
    return diffs


def _compare_file(
    rel_path: str, expected_text: str, actual_text: str, profile: CanonicalProfile
) -> FileDiff:
    canon_expected = canonicalize_text(expected_text, profile)
    canon_actual = canonicalize_text(actual_text, profile)

    try:
        expected_json = json.loads(canon_expected)
        actual_json = json.loads(canon_actual)
    except (json.JSONDecodeError, ValueError):
        expected_json = actual_json = None

    if expected_json is not None and actual_json is not None:
        if _matches_any(rel_path, profile.sort_before_diff_paths):
            if isinstance(expected_json, list):
                expected_json = sorted(expected_json, key=json.dumps)
            if isinstance(actual_json, list):
                actual_json = sorted(actual_json, key=json.dumps)
        diffs = _json_diff(expected_json, actual_json, profile.decimal_tolerance)
        if not diffs:
            return FileDiff(path=rel_path, status="match")
        return FileDiff(path=rel_path, status="diff", detail="\n".join(diffs))

    expected_lines = canon_expected.splitlines()
    actual_lines = canon_actual.splitlines()
    if _matches_any(rel_path, profile.sort_before_diff_paths):
        expected_lines = sorted(expected_lines)
        actual_lines = sorted(actual_lines)
    if expected_lines == actual_lines:
        return FileDiff(path=rel_path, status="match")
    diff_text = "\n".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected",
            tofile="actual",
            lineterm="",
        )
    )
    return FileDiff(path=rel_path, status="diff", detail=diff_text)


def compare_dirs(
    expected_dir: Path, actual_dir: Path, profile: CanonicalProfile
) -> CompareReport:
    """Compare every file under *expected_dir* against its counterpart in
    *actual_dir*, canonicalizing both sides first per *profile*.
    """
    expected_paths = {
        p.relative_to(expected_dir).as_posix()
        for p in expected_dir.rglob("*")
        if p.is_file()
    }
    actual_paths = (
        {
            p.relative_to(actual_dir).as_posix()
            for p in actual_dir.rglob("*")
            if p.is_file()
        }
        if actual_dir.exists()
        else set()
    )

    files: list[FileDiff] = []
    for rel_path in sorted(expected_paths - actual_paths):
        files.append(FileDiff(path=rel_path, status="missing"))
    for rel_path in sorted(actual_paths - expected_paths):
        files.append(FileDiff(path=rel_path, status="extra"))
    for rel_path in sorted(expected_paths & actual_paths):
        expected_text = (expected_dir / rel_path).read_text(
            encoding=profile.encoding_default, errors="replace"
        )
        actual_text = (actual_dir / rel_path).read_text(
            encoding=profile.encoding_default, errors="replace"
        )
        files.append(_compare_file(rel_path, expected_text, actual_text, profile))

    diff_count = sum(1 for f in files if f.status != "match")
    verdict: Literal["pass", "fail"] = "pass" if diff_count == 0 else "fail"
    return CompareReport(verdict=verdict, diff_count=diff_count, files=files)


def write_report(report: CompareReport, report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "report.json"
    md_path = report_dir / "report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, md_path
