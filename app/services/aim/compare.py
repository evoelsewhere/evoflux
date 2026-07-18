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

from app.services.aim.canonicalize import canonicalize_text, mask_text
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


def _values_close(a: str, b: str, tolerance: float) -> bool:
    """String equality, or numeric equality within *tolerance* when both
    sides parse as numbers — the text-side counterpart of
    :func:`_numbers_close`."""
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) <= tolerance
    except ValueError:
        return False


def _line_equal(a: str, b: str, tolerance: float) -> bool:
    """Whole-line equality, tolerating per-token numeric drift within
    *tolerance* (currency/decimal rounding in fixed-report text). Falls back
    to strict equality when tolerance is 0 or the token counts differ."""
    if a == b:
        return True
    if tolerance <= 0:
        return False
    a_tokens, b_tokens = a.split(), b.split()
    if len(a_tokens) != len(b_tokens):
        return False
    return all(_values_close(x, y, tolerance) for x, y in zip(a_tokens, b_tokens))


def _split_fixed_width(line: str, fields: list) -> dict[str, str]:
    """Slice a record *line* into its declared fixed-width fields, stripping
    each field's padding."""
    out: dict[str, str] = {}
    pos = 0
    for spec in fields:
        raw = line[pos : pos + spec.width]
        pos += spec.width
        out[spec.field] = raw.strip()
    return out


def _compare_fixed_width(
    rel_path: str,
    expected_lines: list[str],
    actual_lines: list[str],
    profile: CanonicalProfile,
) -> FileDiff:
    """Field-level compare of two fixed-width record files, applying the
    profile's ``decimal_tolerance`` to numeric fields."""
    if len(expected_lines) != len(actual_lines):
        return FileDiff(
            path=rel_path,
            status="diff",
            detail=f"line count {len(expected_lines)} != {len(actual_lines)}",
        )
    diffs: list[str] = []
    for index, (exp_line, act_line) in enumerate(zip(expected_lines, actual_lines)):
        exp_fields = _split_fixed_width(exp_line, profile.fixed_width_fields)
        act_fields = _split_fixed_width(act_line, profile.fixed_width_fields)
        for spec in profile.fixed_width_fields:
            exp_val = exp_fields.get(spec.field, "")
            act_val = act_fields.get(spec.field, "")
            if not _values_close(exp_val, act_val, profile.decimal_tolerance):
                diffs.append(
                    f"line {index + 1} field {spec.field}: "
                    f"expected={exp_val!r} actual={act_val!r}"
                )
    if diffs:
        return FileDiff(path=rel_path, status="diff", detail="\n".join(diffs))
    return FileDiff(path=rel_path, status="match")


def _read_text(path: Path, profile: CanonicalProfile) -> str:
    """Read *path*, trying the profile's default encoding, then its legacy
    fallback (EBCDIC/windows-1252/...), then a lossy default-encoding read so
    a stray byte never aborts a compare."""
    try:
        return path.read_text(encoding=profile.encoding_default)
    except (UnicodeDecodeError, LookupError):
        pass
    if profile.encoding_legacy_fallback:
        try:
            return path.read_text(encoding=profile.encoding_legacy_fallback)
        except (UnicodeDecodeError, LookupError):
            pass
    return path.read_text(encoding=profile.encoding_default, errors="replace")


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
    if profile.fixed_width_fields:
        # Column positions are load-bearing here, so apply masks only — never
        # whitespace/decimal normalization, which would shift field offsets.
        # Field-level tolerance is applied after slicing instead.
        expected_lines = mask_text(expected_text, profile).splitlines()
        actual_lines = mask_text(actual_text, profile).splitlines()
        if _matches_any(rel_path, profile.sort_before_diff_paths):
            expected_lines = sorted(expected_lines)
            actual_lines = sorted(actual_lines)
        return _compare_fixed_width(rel_path, expected_lines, actual_lines, profile)

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
    # A tolerant second pass catches currency/decimal rounding the raw string
    # compare flagged; only fall through to a real diff when it can't.
    if profile.decimal_tolerance > 0 and len(expected_lines) == len(actual_lines):
        if all(
            _line_equal(exp, act, profile.decimal_tolerance)
            for exp, act in zip(expected_lines, actual_lines)
        ):
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
        if p.is_file() and not _matches_any(p.relative_to(expected_dir).as_posix(), profile.ignore)
    }
    actual_paths = (
        {
            p.relative_to(actual_dir).as_posix()
            for p in actual_dir.rglob("*")
            if p.is_file() and not _matches_any(p.relative_to(actual_dir).as_posix(), profile.ignore)
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
        expected_text = _read_text(expected_dir / rel_path, profile)
        actual_text = _read_text(actual_dir / rel_path, profile)
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
