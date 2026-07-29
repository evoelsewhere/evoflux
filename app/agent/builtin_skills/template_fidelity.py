"""Shared helpers for template-first Office Open XML edits.

The helpers deliberately operate at package-part level.  Unselected parts are
copied without changing their bytes, which makes preservation auditable and
avoids broad rewrites by high-level authoring libraries.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as package:
        return {name: sha256(package.read(name)) for name in package.namelist()}


def patch_package(
    source: Path,
    output: Path,
    replacements: Mapping[str, bytes],
) -> None:
    """Copy *source* to *output*, replacing only explicitly selected parts."""
    if source.resolve() == output.resolve():
        raise ValueError("Refusing to overwrite the source template")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as incoming:
        source_names = set(incoming.namelist())
        missing = sorted(set(replacements) - source_names)
        if missing:
            raise KeyError(f"Package parts do not exist: {', '.join(missing)}")
        with zipfile.ZipFile(output, "w") as outgoing:
            for item in incoming.infolist():
                payload = replacements.get(item.filename, incoming.read(item.filename))
                outgoing.writestr(item, payload)


def _allowed(part: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(part, pattern) for pattern in patterns)


def fidelity_report(
    source: Path,
    output: Path,
    allowed_parts: Sequence[str],
    *,
    protected_patterns: Sequence[str] = (),
) -> dict[str, object]:
    """Report package-level changes and reject unplanned/protected mutations."""
    before = package_hashes(source)
    after = package_hashes(output)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        part for part in set(before) & set(after) if before[part] != after[part]
    )
    unexpected = sorted(
        part
        for part in (*added, *removed, *changed)
        if not _allowed(part, allowed_parts)
    )
    protected = sorted(
        part
        for part in (*added, *removed, *changed)
        if _allowed(part, protected_patterns)
    )
    errors = []
    if unexpected:
        errors.append(f"Unplanned package changes: {', '.join(unexpected)}")
    if protected:
        errors.append(f"Protected template parts changed: {', '.join(protected)}")
    unchanged = len(set(before) & set(after)) - len(changed)
    total = max(len(set(before) | set(after)), 1)
    return {
        "errors": errors,
        "allowed_parts": sorted(set(allowed_parts)),
        "added_parts": added,
        "removed_parts": removed,
        "changed_parts": changed,
        "unchanged_parts": unchanged,
        "preservation_ratio": round(unchanged / total, 6),
    }


def planned_output_report(
    source: Path,
    expected: Path,
    output: Path,
    allowed_parts: Sequence[str],
    *,
    protected_patterns: Sequence[str] = (),
) -> dict[str, object]:
    """Verify that output exactly matches the plan-replayed expected package."""
    report = fidelity_report(
        source,
        output,
        allowed_parts,
        protected_patterns=protected_patterns,
    )
    expected_hashes = package_hashes(expected)
    output_hashes = package_hashes(output)
    mismatches = sorted(
        part
        for part in set(expected_hashes) | set(output_hashes)
        if expected_hashes.get(part) != output_hashes.get(part)
    )
    report["plan_mismatches"] = mismatches
    if mismatches:
        cast(list[str], report["errors"]).append(
            f"Output does not match the declared mutation plan: {', '.join(mismatches)}"
        )
    return report


def load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("edits"), list):
        raise ValueError("Plan must be a JSON object containing an 'edits' list")
    return payload
