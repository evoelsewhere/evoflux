"""Pure compiler for raw agent frontmatter and code-owned defaults."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.config import AgentConfig, apply_tool_opt_outs
from app.core.app_mode import AppMode, parse_app_mode

_IMPLICIT_TOOLS = ("skill",)
_LEAD_IMPLICIT_TOOLS = ("todo_manage", "schedule_task", "note")


def compile_agent_config(
    raw: AgentConfig,
    *,
    mode: str | AppMode,
    tool_registry: Mapping[str, Any] | None = None,
) -> AgentConfig:
    """Compile one effective config without reading or writing the filesystem.

    Precedence is deterministic: code-owned role profile, then user-authored
    additive frontmatter/body, then explicit opt-outs.  Both the runtime and
    the settings API call this function, preventing their views from drifting.
    """

    from app.agent.builtin_prompts import (
        EVOFLUX_description_for_mode,
        apply_EVOFLUX_extra_prompt,
        apply_member_extra_prompt,
        builtin_member_profile,
        tier_tools,
    )

    resolved_mode = parse_app_mode(mode).value
    config = raw.model_copy(deep=True)

    if config.role == "lead" and config.name.casefold() == "evoflux":
        config.description = config.description or EVOFLUX_description_for_mode(
            resolved_mode
        )
        config.system_prompt = apply_EVOFLUX_extra_prompt(
            resolved_mode, config.system_prompt
        )
    elif config.role == "member":
        profile = builtin_member_profile(resolved_mode, config.name)
        if profile is not None:
            config.description = config.description or profile["description"]
            config.mcp = [*profile["mcp"], *config.mcp]
            config.system_prompt = apply_member_extra_prompt(
                config.name, profile["prompt"], config.system_prompt
            )

    implicit = [*_IMPLICIT_TOOLS]
    if config.role == "lead":
        implicit.extend(_LEAD_IMPLICIT_TOOLS)
    granted = (
        tier_tools(tool_registry, mode=resolved_mode, role=config.role)
        if tool_registry is not None
        else []
    )
    # Implicit lifecycle tools are runtime invariants and cannot be opted out.
    explicit_and_granted = [*granted, *config.tools]
    config.tools = explicit_and_granted
    apply_tool_opt_outs(config)
    config.tools = list(dict.fromkeys([*implicit, *config.tools]))

    config.skills = list(dict.fromkeys(config.skills))
    config.mcp = list(dict.fromkeys(config.mcp))
    return config
