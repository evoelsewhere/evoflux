"""Native Agent Skills tool facade.

Discovery, prompt rendering, and activation are intentionally separate:

* :mod:`app.agent.skills.discovery` reads Tier-1 metadata only;
* :class:`app.agent.hooks.skill_catalog.SkillCatalogHook` exposes a bounded
  model-visible catalog;
* this tool loads one exact skill or one exact resource on demand.

No user request is converted into a search query and no keyword router lives
here. Selection is made by the model from portable skill descriptions or by an
explicit ``/skill:<name>`` directive.
"""

from __future__ import annotations

import json
import textwrap
import time
from difflib import get_close_matches
from pathlib import Path
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.skills.activation import (
    SkillDependencyError,
    activate_skill,
    activate_skill_with_runtime,
    is_skill_activation_content,
    read_skill_instructions,
    read_skill_resource,
    render_path_tokens,
)
from app.agent.skills.catalog import render_skill_catalog
from app.agent.skills.discovery import (
    _walk_skill_paths,
    builtin_skills_dir,
    discover_skill_records,
    discover_skill_records_cached,
    parse_frontmatter,
    select_skill_records_for_mode,
    skills_tree_signature,
    standard_skill_roots,
)
from app.agent.skills.models import SkillRecord
from app.agent.tools.registry import InjectedArg, tool


def _default_skills_dir() -> Path:
    from app.core.config import settings

    return Path(settings.SKILLS_DIR)


_SKILLS_DIR: Path = _default_skills_dir()


def _project_root() -> Path:
    try:
        return get_sandbox().workspace_root
    except Exception:
        return Path.cwd()


def _workspace_roots() -> list[Path]:
    try:
        return list(get_sandbox().allowed_workspace_roots)
    except Exception:
        return [_project_root()]


def _iter_skill_roots() -> list[Path]:
    """Return project/user/admin/bundled roots in precedence order."""

    return standard_skill_roots(
        workspace_roots=_workspace_roots(),
        evoflux_global=_SKILLS_DIR,
    )


def _builtin_skills_dir() -> Path:
    return builtin_skills_dir()


# Compatibility aliases for existing cache invalidation and extension imports.
_parse_frontmatter = parse_frontmatter
_render_tokens = render_path_tokens
_iter_skill_paths = _walk_skill_paths
_skills_dir_signature = skills_tree_signature
_discover_skills_cached = discover_skill_records_cached


def discover_skill_records_runtime(
    skills_dir: Path | None = None,
    *,
    mode: str | None = None,
) -> dict[str, SkillRecord]:
    if skills_dir is not None:
        # An explicit directory is an isolated discovery request used by
        # package tooling and compatibility callers; global plugin Skills must
        # not leak into that result.
        records = discover_skill_records([skills_dir])
    else:
        from app.plugin_platform.skills import discover_skill_records_with_plugins

        records = discover_skill_records_with_plugins(
            root for root in _iter_skill_roots() if root.is_dir()
        )
    return select_skill_records_for_mode(records, mode) if mode is not None else records


def discover_skills(skills_dir: Path | None = None) -> dict[str, dict]:
    """Return the compatibility catalog shape backed by the typed registry."""

    return {
        name: record.as_legacy_dict()
        for name, record in discover_skill_records_runtime(skills_dir).items()
    }


def skills_for_mode(skills: dict[str, dict], mode: str) -> dict[str, dict]:
    resolved = "coding" if mode == "coding" else "work"
    return {
        name: info
        for name, info in skills.items()
        if resolved in info.get("modes", ("work", "coding"))
    }


def _short_description(description: str, *, max_len: int = 90) -> str:
    return textwrap.shorten(description.strip(), width=max_len, placeholder="…")


def format_available_skills(
    *,
    verbose: bool = False,
    mode: str | None = None,
    implicit_only: bool = True,
) -> str:
    """Render the bounded runtime catalog; never include skill bodies."""

    resolved_mode = "coding" if mode == "coding" else "work"
    records = [
        record
        for record in discover_skill_records_runtime(mode=resolved_mode).values()
        if record.valid and (record.allow_implicit_invocation or not implicit_only)
    ]
    if not records:
        return "No skills are currently available."
    if verbose:
        rendered = render_skill_catalog(records, mode=resolved_mode)
        return rendered.text or "No skills fit within the catalog budget."
    return "\n".join(
        ["## Available Skills"]
        + [
            f"- **{record.name}**: {_short_description(record.description)}"
            for record in sorted(records, key=lambda item: item.name)
        ]
    )


def _skill_tool_description() -> str:
    return (
        "Load one exact skill workflow or one resource from a skill named in "
        "the model-visible Skills catalog. Use action='load' before "
        "applying a selected workflow, action='read_resource' only when its "
        "loaded instructions direct you to a bundled text file, and "
        "action='list' only for catalog recovery. Do not pass the user's "
        "request as a skill name or search query. Load at most once per selected "
        "skill and reuse instructions already visible in the conversation."
    )


def _loaded_skills_from_messages(state: Any) -> dict[str, str]:
    """Rehydrate durable activations from visible assistant/tool pairs."""

    loaded: dict[str, str] = {}
    pending_by_tool_call_id: dict[str, str] = {}
    for message in getattr(state, "messages_for_llm", []):
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = getattr(tool_call, "function", None)
            if function is None or getattr(function, "name", None) != "skill":
                continue
            try:
                arguments = json.loads(getattr(function, "arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            if arguments.get("action", "load") != "load":
                continue
            name = arguments.get("skill_name")
            call_id = getattr(tool_call, "id", None)
            if isinstance(name, str) and name and isinstance(call_id, str) and call_id:
                pending_by_tool_call_id[call_id] = name

        call_id = getattr(message, "tool_call_id", None)
        name = (
            pending_by_tool_call_id.get(call_id) if isinstance(call_id, str) else None
        )
        content = getattr(message, "content", None)
        if (
            name
            and isinstance(content, str)
            and is_skill_activation_content(content, name)
        ):
            loaded[name] = content
    return loaded


def _resolve_record(
    skill_name: str, mode: str
) -> tuple[SkillRecord | None, str | None]:
    all_records = discover_skill_records_runtime()
    winner = all_records.get(skill_name)
    if winner is None:
        matches = get_close_matches(skill_name, sorted(all_records), n=3, cutoff=0.5)
        suggestion = f" Did you mean: {', '.join(matches)}?" if matches else ""
        return None, (
            f"Skill '{skill_name}' not found.{suggestion} "
            "Use an exact name from the Skills catalog or call action='list' "
            "to recover the bounded catalog."
        )

    candidates = [winner, *winner.alternates]
    applicable = [candidate for candidate in candidates if mode in candidate.modes]
    record = next((candidate for candidate in applicable if candidate.valid), None)
    if record is not None:
        return record, None
    if applicable:
        invalid = applicable[0]
        details = "; ".join(
            item.message for item in invalid.diagnostics if item.severity == "error"
        )
        return None, (
            f"Skill '{skill_name}' is invalid: {details or 'metadata validation failed'}."
        )

    available_modes = sorted(
        {
            candidate_mode
            for candidate in candidates
            for candidate_mode in candidate.modes
        }
    )
    return None, (
        f"Skill '{skill_name}' is not available in {mode} mode. "
        f"Available modes: {', '.join(available_modes)}."
    )


@tool(
    name="skill",
    description=_skill_tool_description,
    max_calls_per_batch=5,
    deduplicate_in_batch=True,
)
async def load_skill(
    skill_name: Annotated[
        str | None,
        Field(
            description="Exact catalog skill name. Required except for action='list'."
        ),
    ] = None,
    action: Annotated[
        Literal["list", "load", "read_resource"],
        Field(
            description="List routing metadata, load SKILL.md, or read one bundled text resource."
        ),
    ] = "load",
    resource_path: Annotated[
        str | None,
        Field(
            description="POSIX path relative to the selected skill directory for action='read_resource'."
        ),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
    _mode: Annotated[Literal["work", "coding"], InjectedArg()] = "work",
) -> str:
    """Progressively disclose an exact skill or a referenced bundle resource."""

    if action == "list":
        return format_available_skills(verbose=True, mode=_mode, implicit_only=True)
    if not skill_name:
        return f"skill_name is required when action='{action}'."

    if not any(root.is_dir() for root in _iter_skill_roots()):
        return "Skills directory not found."

    record, error = _resolve_record(skill_name, _mode)
    if record is None:
        return error or f"Skill '{skill_name}' is unavailable."

    if _state is not None:
        loaded = _state.metadata.get("loaded_skills")
        if not isinstance(loaded, dict):
            loaded = _loaded_skills_from_messages(_state)
            _state.metadata["loaded_skills"] = loaded
    else:
        loaded = {}

    if action == "read_resource":
        if not resource_path:
            return "resource_path is required when action='read_resource'."
        if _state is not None and skill_name not in loaded:
            return (
                f"Load skill '{skill_name}' before reading its resources so the "
                "resource is interpreted under the correct workflow."
            )
        try:
            return await read_skill_resource(record, resource_path)
        except (OSError, UnicodeError, ValueError) as exc:
            return (
                f"Could not read resource '{resource_path}' from '{skill_name}': {exc}"
            )

    if skill_name in loaded:
        logger.info("skill_reused name={}", skill_name)
        return (
            f"Skill '{skill_name}' is already loaded; reuse its visible instructions."
        )

    started_at = time.perf_counter()
    try:
        rendered = (
            await activate_skill_with_runtime(_state, record)
            if _state is not None
            else await activate_skill(record)
        )
    except (OSError, UnicodeError, ValueError, SkillDependencyError) as exc:
        try:
            from app.conductor.telemetry import record_skill_usage

            record_skill_usage(
                skill_name,
                source="manual",
                mode=_mode,
                outcome="failure",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                failure_category=type(exc).__name__,
            )
        except Exception:  # noqa: BLE001 - telemetry cannot block activation
            pass
        return f"Could not load skill '{skill_name}': {exc}"
    try:
        from app.conductor.telemetry import record_skill_usage

        record_skill_usage(
            skill_name,
            source="manual",
            mode=_mode,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
    except Exception:  # noqa: BLE001 - telemetry cannot block activation
        pass
    logger.info("skill_loaded name={} file={}", skill_name, record.skill_file)
    if _state is not None:
        loaded[skill_name] = rendered
        return rendered

    # Preserve the historical direct-Python-call contract for extensions and
    # unit tests. Real tool execution always injects AgentState and therefore
    # receives the structured activation wrapper above.
    try:
        return await read_skill_instructions(record)
    except (OSError, UnicodeError, ValueError) as exc:
        return f"Could not load skill '{skill_name}': {exc}"


__all__ = [
    "_SKILLS_DIR",
    "_builtin_skills_dir",
    "_discover_skills_cached",
    "_iter_skill_paths",
    "_iter_skill_roots",
    "_parse_frontmatter",
    "_project_root",
    "_render_tokens",
    "_skill_tool_description",
    "_skills_dir_signature",
    "discover_skill_records_runtime",
    "discover_skills",
    "format_available_skills",
    "load_skill",
    "skills_for_mode",
]
