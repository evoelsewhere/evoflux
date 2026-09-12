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


def agent_model_override(
    provider: ManagedResourceProvider, agent: str
) -> str | None:
    return read_agent_runtime_settings(
        project_id=provider.project_id,
        resource_id=provider.resource_id,
        agent=agent,
    ).model


def apply_managed_agent_runtime_model(
    config: AgentConfig,
    *,
    provider: ManagedResourceProvider | None = None,
    source_path: Path | None = None,
    agent: str | None = None,
) -> AgentConfig:
    """Union the installation's own runtime layer onto a managed Agent.

    ``agent`` is the Agent target that addresses the runtime record — the
    path stem under ``AGENTS_DIR`` ("reviewer", "coding/reviewer"), not the
    frontmatter name. It is derived from *source_path* when omitted; a caller
    passing *provider* directly must pass it too, since a Team's Agents all
    share one ``resource_id``.
    """
    owner = provider or managed_agent_provider_for_path(source_path)
    target = agent or managed_agent_target_for_path(source_path)
    if owner is None or target is None:
        return config
    local = read_agent_runtime_settings(
        project_id=owner.project_id,
        resource_id=owner.resource_id,
        agent=target,
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


def managed_agent_target_for_path(source_path: Path | None) -> str | None:
    """The Agent target that addresses one ``.md`` under ``AGENTS_DIR``."""
    if source_path is None:
        return None
    try:
        relative = source_path.resolve().relative_to(
            Path(settings.AGENTS_DIR).resolve()
        )
    except (OSError, ValueError):
        return None
    return relative.with_suffix("").as_posix()


def managed_agent_setup_action(source_path: Path | None) -> dict[str, Any] | None:
    """CTA for an ``agent_not_configured`` failure on a managed Agent.

    A Conductor-published Team ships without a model on purpose — the model
    is an installation choice. Pointing that failure at Settings → Providers
    sends the user to a page that is already correct; the fix lives on the
    Agent's own runtime-model control.  Returns ``None`` for unmanaged
    Agents so the caller keeps the provider CTA.
    """
    name = managed_agent_target_for_path(source_path)
    if name is None:
        return None
    provider = managed_resource_provider("agent_team", name)
    if provider is None:
        return None
    return {
        "type": "open_agent_settings",
        "agent": name,
        "project": provider.project_name,
    }


def _additive(base: list[str], additions: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys([*base, *additions]))


def managed_agent_provider_for_path(
    source_path: Path | None,
) -> ManagedResourceProvider | None:
    target = managed_agent_target_for_path(source_path)
    if target is None:
        return None
    return managed_resource_provider("agent_team", target)


__all__ = [
    "agent_model_override",
    "apply_managed_agent_runtime_model",
    "managed_agent_provider_for_path",
    "managed_agent_target_for_path",
    "managed_agent_setup_action",
]
