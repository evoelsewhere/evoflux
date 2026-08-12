"""Portable EvoFlux mode scope for skill bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeAlias

SkillMode: TypeAlias = Literal["work", "coding"]
ALL_SKILL_MODES: tuple[SkillMode, ...] = ("work", "coding")
SKILL_SCOPE_FILENAME = ".evoflux.json"
MAX_SKILL_SCOPE_BYTES = 16 * 1024


def default_skill_modes() -> list[SkillMode]:
    """Return a fresh Pydantic-safe default list for API models."""

    return list(ALL_SKILL_MODES)


def normalize_skill_modes(value: object) -> tuple[SkillMode, ...]:
    """Canonicalize an external mode value, defaulting safely to both modes."""

    if not isinstance(value, (list, tuple)):
        return ALL_SKILL_MODES
    selected = {item for item in value if item in ALL_SKILL_MODES}
    if not selected:
        return ALL_SKILL_MODES
    return tuple(mode for mode in ALL_SKILL_MODES if mode in selected)


def read_skill_modes(skill_dir: Path) -> tuple[SkillMode, ...]:
    """Read optional EvoFlux UI/runtime metadata beside a portable SKILL.md."""

    modes, _diagnostic = read_skill_modes_with_diagnostic(skill_dir)
    return modes


def read_skill_modes_with_diagnostic(
    skill_dir: Path,
) -> tuple[tuple[SkillMode, ...], str | None]:
    """Read mode scope and preserve why a present sidecar was rejected.

    Discovery intentionally fails open to both modes so a corrupt EvoFlux-only
    sidecar cannot make an otherwise portable Agent Skill disappear.  The
    paired diagnostic lets the registry surface that fallback instead of
    silently changing runtime behaviour.
    """

    path = skill_dir / SKILL_SCOPE_FILENAME
    try:
        with path.open("rb") as handle:
            payload_bytes = handle.read(MAX_SKILL_SCOPE_BYTES + 1)
    except FileNotFoundError:
        return ALL_SKILL_MODES, None
    except OSError as exc:
        return ALL_SKILL_MODES, f"{SKILL_SCOPE_FILENAME} could not be read: {exc}"
    if len(payload_bytes) > MAX_SKILL_SCOPE_BYTES:
        return (
            ALL_SKILL_MODES,
            f"{SKILL_SCOPE_FILENAME} exceeds the {MAX_SKILL_SCOPE_BYTES}-byte limit.",
        )
    try:
        text = payload_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return ALL_SKILL_MODES, f"{SKILL_SCOPE_FILENAME} is not valid UTF-8: {exc}"
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        if isinstance(exc, json.JSONDecodeError):
            detail = f"{exc.msg} (line {exc.lineno}, column {exc.colno})"
        else:
            detail = "nesting is too deep"
        return (
            ALL_SKILL_MODES,
            f"{SKILL_SCOPE_FILENAME} is not valid JSON: {detail}.",
        )
    if not isinstance(payload, dict):
        return (
            ALL_SKILL_MODES,
            f"{SKILL_SCOPE_FILENAME} must contain a JSON object.",
        )

    raw_modes = payload.get("modes")
    if not isinstance(raw_modes, list) or not raw_modes:
        return (
            ALL_SKILL_MODES,
            f"{SKILL_SCOPE_FILENAME}.modes must be a non-empty array.",
        )
    invalid = [item for item in raw_modes if item not in ALL_SKILL_MODES]
    if invalid:
        return (
            ALL_SKILL_MODES,
            f"{SKILL_SCOPE_FILENAME}.modes contains unsupported values; "
            "expected only 'work' and/or 'coding'.",
        )
    return normalize_skill_modes(raw_modes), None


def serialize_skill_modes(modes: object) -> str:
    """Return deterministic sidecar content for one canonical mode scope."""

    return json.dumps({"modes": list(normalize_skill_modes(modes))}, indent=2) + "\n"
