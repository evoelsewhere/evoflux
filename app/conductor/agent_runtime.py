"""Apply installation-owned runtime preferences to managed Agent bundles."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.conductor.provenance import managed_resource_provider
from app.core.agent_settings import read_agent_runtime_settings
from app.core.config import settings

if TYPE_CHECKING:
    from app.agent.config import AgentConfig
    from app.conductor.models import ManagedResourceProvider


def agent_model_override(provider: ManagedResourceProvider) -> str | None:
    return read_agent_runtime_settings(
        project_id=provider.project_id,
        resource_id=provider.resource_id,
    ).model


def apply_managed_agent_runtime_model(
    config: AgentConfig,
    *,
    provider: ManagedResourceProvider | None = None,
    source_path: Path | None = None,
) -> AgentConfig:
    owner = provider or managed_agent_provider_for_path(source_path)
    if owner is None:
        return config
    local = read_agent_runtime_settings(
        project_id=owner.project_id,
        resource_id=owner.resource_id,
    )
    update: dict[str, Any] = {
        "tools": _additive(config.tools, local.extra_tools),
        "skills": _additive(config.skills, local.extra_skills),
        "mcp": _additive(config.mcp, local.extra_mcp),
    }
    if local.model is not None:
        # Reasoning controls are model-specific. Let the selected provider use
        # its safe default instead of carrying a bundle setting across models.
        update.update({"model": local.model, "thinking_level": None})
    return config.model_copy(update=update)


def _additive(base: list[str], additions: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys([*base, *additions]))


def managed_agent_provider_for_path(
    source_path: Path | None,
) -> ManagedResourceProvider | None:
    if source_path is None:
        return None
    try:
        relative = source_path.resolve().relative_to(
            Path(settings.AGENTS_DIR).resolve()
        )
    except (OSError, ValueError):
        return None
    return managed_resource_provider("agent", relative.with_suffix("").as_posix())


__all__ = [
    "agent_model_override",
    "apply_managed_agent_runtime_model",
    "managed_agent_provider_for_path",
]
