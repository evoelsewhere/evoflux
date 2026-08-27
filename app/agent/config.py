"""Lightweight agent frontmatter schema and parse-only team validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError, model_validator

PROVIDER_MODEL_TOKEN = "__PROVIDER_MODEL__"
_FRONTMATTER_RE = re.compile(r"^\s*---\r?\n(.*?)\r?\n---\r?\n?(.*)", re.DOTALL)


class AgentConfig(BaseModel):
    """Schema for a single agent defined in a Markdown frontmatter block."""

    name: str
    role: Literal["lead", "member"] = "member"
    lead: str | None = None
    description: str | None = None
    system_prompt: str = ""
    tools: list[str] = []
    tools_opt_out: list[str] = []
    mcp: list[str] = []
    skills: list[str] = []
    model: str | None = None
    fallback_model: str | None = None
    thinking_level: str | None = None
    responses_api: bool | None = None

    @model_validator(mode="after")
    def _validate(self) -> "AgentConfig":
        if self.lead is not None:
            self.lead = self.lead.strip()
            if not self.lead:
                raise ValueError(f"Agent '{self.name}': lead owner cannot be blank.")
        if self.role == "lead" and self.lead is not None:
            raise ValueError(
                f"Lead agent '{self.name}' cannot be owned by another lead."
            )
        if self.model and self.model != PROVIDER_MODEL_TOKEN and ":" not in self.model:
            raise ValueError(
                f"Agent '{self.name}': invalid model '{self.model}' "
                f"(expected 'provider:model', e.g. 'googlegenai:gemini-3.1-flash')."
            )
        return self


def apply_tool_opt_outs(config: AgentConfig) -> AgentConfig:
    """Apply explicit tool exclusions after mode defaults are compiled."""

    if config.tools_opt_out:
        opted_out = set(config.tools_opt_out)
        config.tools = [tool for tool in config.tools if tool not in opted_out]
    config.tools = list(dict.fromkeys(config.tools))
    return config


def member_model_is_configured(model: str | None) -> bool:
    """Return whether a member model is configured enough to join a team."""
    return bool(model and model.strip() and model.strip() != PROVIDER_MODEL_TOKEN)


def parse_agent_definition(
    text: str,
    *,
    default_name: str,
    source_label: str = "Agent definition",
) -> AgentConfig:
    """Parse Agent Markdown text using the same schema as runtime loading."""

    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(
            f"{source_label} is missing YAML frontmatter. "
            "Expected '---\\n<yaml>\\n---\\n<system prompt>'."
        )
    try:
        raw_meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(raw_meta, dict):
        raise ValueError(f"{source_label} frontmatter must be a YAML mapping.")
    body = match.group(2).strip()
    raw_meta.setdefault("name", default_name)
    raw_meta["system_prompt"] = body or "You are a helpful assistant."
    try:
        return AgentConfig.model_validate(raw_meta)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ValueError(errors) from exc


def parse_agent_md(path: Path) -> AgentConfig:
    """Parse one agent Markdown file without importing runtime agent machinery."""

    return parse_agent_definition(
        path.read_text(encoding="utf-8"),
        default_name=path.stem,
        source_label=f"Agent file '{path}'",
    )


def validate_agent_config_dir(agents_dir: Path) -> str | None:
    """Parse a team directory and return its default lead without building."""
    if not agents_dir.exists():
        return None
    paths = sorted(agents_dir.glob("*.md"))
    if not paths:
        return None

    configs: list[tuple[AgentConfig, Path]] = []
    errors: list[str] = []
    for path in paths:
        try:
            configs.append((parse_agent_md(path), path))
        except Exception as exc:  # noqa: BLE001 - aggregate all malformed files
            errors.append(f"  {path.name}: {exc}")
    if errors:
        raise ValueError(
            f"Failed to parse {len(errors)} agent file(s) in '{agents_dir}':\n"
            + "\n".join(errors)
        )

    _lead, _members, default_lead = resolve_agent_roster(configs)
    return default_lead


def resolve_agent_roster(
    configs: list[tuple[AgentConfig, Path]],
    lead_name: str | None = None,
) -> tuple[tuple[AgentConfig, Path], list[tuple[AgentConfig, Path]], str]:
    """Validate one mode directory and resolve a lead-owned member roster."""

    leads = [(config, path) for config, path in configs if config.role == "lead"]
    if not leads:
        directory = configs[0][1].parent if configs else "agent directory"
        raise ValueError(
            f"No agent with 'role: lead' found in '{directory}'. "
            "At least one lead is required."
        )

    by_name: dict[str, tuple[AgentConfig, Path]] = {}
    for config, path in configs:
        if config.name in by_name:
            existing_config, _existing_path = by_name[config.name]
            if "lead" in {existing_config.role, config.role}:
                raise ValueError(
                    f"Member '{config.name}' in '{path.name}' shares the lead's name."
                )
            raise ValueError(f"Duplicate agent name '{config.name}' in '{path.name}'.")
        by_name[config.name] = (config, path)
        if config.role == "member" and "#" in config.name:
            raise ValueError(
                f"Member blueprint '{config.name}' in '{path.name}' contains '#'. "
                "Reserved character — instances are named 'blueprint#N'."
            )

    lead_by_name = {config.name: (config, path) for config, path in leads}
    default_lead = "evoflux" if "evoflux" in lead_by_name else sorted(lead_by_name)[0]
    selected = lead_name or default_lead
    if selected not in lead_by_name:
        raise ValueError(
            f"Lead agent '{selected}' is not configured. "
            f"Available leads: {', '.join(sorted(lead_by_name))}."
        )

    members: list[tuple[AgentConfig, Path]] = []
    for config, path in configs:
        if config.role != "member":
            continue
        owner = config.lead or default_lead
        if owner not in lead_by_name:
            raise ValueError(
                f"Member '{config.name}' in '{path.name}' references unknown lead "
                f"'{owner}'."
            )
        if owner == selected:
            members.append((config, path))
    return lead_by_name[selected], members, default_lead


def list_agent_rosters(
    agents_dir: Path,
) -> tuple[str | None, list[tuple[AgentConfig, Path, list[tuple[AgentConfig, Path]]]]]:
    """Return every lead and its exact member configs for one mode directory."""

    if not agents_dir.exists():
        return None, []
    entries = [(parse_agent_md(path), path) for path in sorted(agents_dir.glob("*.md"))]
    if not entries:
        return None, []
    _lead, _members, default_lead = resolve_agent_roster(entries)
    leads = sorted(
        (entry for entry in entries if entry[0].role == "lead"),
        key=lambda entry: entry[0].name,
    )
    rosters = []
    for lead_config, lead_path in leads:
        _selected, members, _default = resolve_agent_roster(
            entries, lead_name=lead_config.name
        )
        rosters.append((lead_config, lead_path, members))
    return default_lead, rosters


def agent_dir_has_lead(agents_dir: Path) -> bool:
    """Return whether a directory contains a parseable lead config."""
    if not agents_dir.exists():
        return False
    for path in sorted(agents_dir.glob("*.md")):
        try:
            if parse_agent_md(path).role == "lead":
                return True
        except Exception:
            continue
    return False
