"""Strict one-level plugin skill discovery and precedence integration."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.agent.skills.discovery import (
    _build_record,
    _finalize_runtime_settings,
    discover_skill_records,
)
from app.agent.skills.models import SkillRecord
from app.core.skill_settings import (
    read_skill_runtime_settings_snapshot,
    skill_settings_id,
)
from app.plugin_platform.registry import list_effective_installations, plugin_data_root
from app.plugin_platform.validator import inspect_plugin


def discover_plugin_skill_records() -> dict[str, SkillRecord]:
    """Discover valid skills from enabled plugins, immediate children only."""

    selected: dict[str, SkillRecord] = {}
    runtime_settings, settings_diagnostics = read_skill_runtime_settings_snapshot()
    for installation in list_effective_installations(enabled_only=True):
        root = Path(installation.root).resolve()
        inspection = inspect_plugin(root, data_root=plugin_data_root(installation.id))
        if not inspection.valid:
            continue
        valid_paths = {item.path for item in inspection.skills if item.valid}
        skills_root = root / "skills"
        for relative in sorted(valid_paths):
            skill_file = root / relative
            stem = skill_file.parent.name
            record = _build_record(skills_root, skill_file, stem)
            record.source = f"plugin:{installation.id}"
            record.editable = False
            record.settings_id = skill_settings_id(
                source=record.source,
                root=skills_root,
                stem=stem,
            )
            _finalize_runtime_settings(
                record,
                runtime_settings=runtime_settings,
                settings_diagnostics=settings_diagnostics,
            )
            previous = selected.get(record.name)
            if previous is None:
                selected[record.name] = record
                continue
            previous.shadowed_paths.append(str(record.skill_file))
            previous.alternates.append(record)
            previous.add_diagnostic(
                "shadowed-plugin-duplicate",
                f"A lower-precedence plugin skill was ignored: {record.skill_file}",
            )
    return selected


def _candidate_chain(record: SkillRecord) -> list[SkillRecord]:
    return [record, *record.alternates]


def discover_skill_records_with_plugins(
    roots: Iterable[Path],
) -> dict[str, SkillRecord]:
    """Merge plugins after project/user/admin roots and before built-ins."""

    base = discover_skill_records(roots)
    plugins = discover_plugin_skill_records()
    for name, plugin_winner in plugins.items():
        current = base.get(name)
        if current is None:
            base[name] = plugin_winner
            continue

        higher: list[SkillRecord] = []
        lower: list[SkillRecord] = []
        for candidate in _candidate_chain(current):
            (lower if candidate.source == "builtin" else higher).append(candidate)
        plugin_chain = _candidate_chain(plugin_winner)
        ordered = [*higher, *plugin_chain, *lower]
        winner, *alternates = ordered
        winner.alternates = alternates
        winner.shadowed_paths = [str(item.skill_file) for item in alternates]
        base[name] = winner
    return base


__all__ = [
    "discover_plugin_skill_records",
    "discover_skill_records_with_plugins",
]
