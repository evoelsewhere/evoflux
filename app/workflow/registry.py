"""Environment introspection for workflow validation + manifests.

The definition layer is pure (M1); this module supplies reality: which
registry tools exist, which ``role: member`` blueprints are available for
a given scope, and what tools each blueprint configures (for the lint and
the informational manifest display).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def known_tool_names() -> set[str]:
    from app.agent.loader import _default_tool_registry

    return set(_default_tool_registry().keys())


def _agents_dirs_for_scope(scope: str) -> list[Path]:
    """A scope's roster search dirs. Loaders keep work and coding separate:
    scope work → agents/, coding → agents/coding."""
    from app.services.team_manager import _resolve_agents_dir

    base = _resolve_agents_dir()
    if scope == "coding":
        return [base / "coding"]
    return [base]


def member_blueprints(scope: str) -> dict[str, set[str]]:
    """``role: member`` blueprint name → its configured tool names for the
    scope's roster dir. Unparseable files are skipped (the roster loader
    warns about them elsewhere)."""
    from app.agent.loader import parse_agent_md

    result: dict[str, set[str]] = {}
    for agents_dir in _agents_dirs_for_scope(scope):
        if not agents_dir.is_dir():
            continue
        for path in sorted(agents_dir.glob("*.md")):
            try:
                config = parse_agent_md(path)
            except Exception as exc:  # noqa: BLE001 — corrupt files skipped
                logger.debug("workflow_blueprint_skip path={} error={}", path, exc)
                continue
            if config.role == "member":
                result[config.name] = set(config.tools or [])
    return result


def lead_tools(scope: str) -> set[str]:
    """The scope lead's configured tools (for the destructive lint)."""
    from app.agent.loader import parse_agent_md

    for agents_dir in _agents_dirs_for_scope(scope):
        if not agents_dir.is_dir():
            continue
        for path in sorted(agents_dir.glob("*.md")):
            try:
                config = parse_agent_md(path)
            except Exception:  # noqa: BLE001
                continue
            if config.role == "lead":
                return set(config.tools or [])
    return set()
