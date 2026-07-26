"""Lightweight agent frontmatter schema and parse-only team validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

PROVIDER_MODEL_TOKEN = "__PROVIDER_MODEL__"
_FRONTMATTER_RE = re.compile(r"^\s*---\r?\n(.*?)\r?\n---\r?\n?(.*)", re.DOTALL)


class AgentConfig(BaseModel):
    """Schema for a single agent defined in a Markdown frontmatter block."""

    name: str
    role: Literal["lead", "member"] = "member"
    description: str | None = None
    system_prompt: str = ""
    tools: list[str] = []
    mcp: list[str] = []
    skills: list[str] = []
    model: str | None = None
    fallback_model: str | None = None
    temperature: float | None = None
    thinking_level: str | None = None
    responses_api: bool | None = None

    @model_validator(mode="after")
    def _validate(self) -> "AgentConfig":
        if self.model and self.model != PROVIDER_MODEL_TOKEN and ":" not in self.model:
            raise ValueError(
                f"Agent '{self.name}': invalid model '{self.model}' "
                f"(expected 'provider:model', e.g. 'googlegenai:gemini-3.1-flash')."
            )
        return self


def member_model_is_configured(model: str | None) -> bool:
    """Return whether a member model is configured enough to join a team."""
    return bool(model and model.strip() and model.strip() != PROVIDER_MODEL_TOKEN)


def parse_agent_md(path: Path) -> AgentConfig:
    """Parse one agent Markdown file without importing runtime agent machinery."""
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(
            f"Agent file '{path}' is missing YAML frontmatter. "
            "Expected '---\\n<yaml>\\n---\\n<system prompt>'."
        )
    raw_meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(raw_meta, dict):
        raise ValueError(f"Agent file '{path}' frontmatter must be a YAML mapping.")
    body = match.group(2).strip()
    raw_meta.setdefault("name", path.stem)
    raw_meta["system_prompt"] = body or "You are a helpful assistant."
    return AgentConfig.model_validate(raw_meta)


def validate_agent_config_dir(agents_dir: Path) -> str | None:
    """Parse a team directory and return its lead name without building a team."""
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

    leads = [(config, path) for config, path in configs if config.role == "lead"]
    if not leads:
        raise ValueError(
            f"No agent with 'role: lead' found in '{agents_dir}'. "
            "Exactly one agent must have 'role: lead'."
        )
    if len(leads) > 1:
        names = [config.name for config, _path in leads]
        raise ValueError(
            f"Multiple agents with 'role: lead' found in '{agents_dir}': {names}. "
            "Exactly one agent must have 'role: lead'."
        )

    lead_name = leads[0][0].name
    seen = {lead_name}
    for config, path in configs:
        if config.role != "member":
            continue
        if "#" in config.name:
            raise ValueError(
                f"Member blueprint '{config.name}' in '{path.name}' contains '#'. "
                "Reserved character — instances are named 'blueprint#N'."
            )
        if config.name in seen:
            raise ValueError(f"Duplicate agent name '{config.name}' in '{path.name}'.")
        seen.add(config.name)
    return lead_name


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
