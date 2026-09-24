"""Resolves the project + role AI provider/tool allow-list Conductor governs.

The raw rows are synced periodically by :mod:`app.conductor.service` into
``RuntimeSettings.conductor.ai_policy_rows`` (Phase 1, T1.2) — this module
never talks to Conductor itself, it only merges what is already cached
locally, so resolving a policy never adds latency to session start.

No row for a scope means unrestricted at that tier: absence of
configuration must never silently deny something that worked yesterday. A
role row narrows (intersects) the project row's allowance, never widens
past it.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.runtime_settings import load_runtime_settings


class ResolvedAiPolicy(BaseModel):
    default_provider: str | None = None
    default_model: str | None = None
    allowed_providers: list[str] = []
    allowed_tools: list[str] = []

    def provider_allowed(self, provider: str) -> bool:
        return not self.allowed_providers or provider in self.allowed_providers

    def tool_allowed(self, tool: str) -> bool:
        return not self.allowed_tools or tool in self.allowed_tools


def _merge_allowed(project: list[str], role: list[str]) -> list[str]:
    if not project and not role:
        return []
    if not role:
        return list(project)
    if not project:
        return list(role)
    return [item for item in project if item in role]


def resolve_ai_policy() -> ResolvedAiPolicy:
    """Merge the synced project-scope row with the current member's role-scope row."""

    conductor = load_runtime_settings().conductor
    rows = conductor.ai_policy_rows
    role = conductor.member_primary_role
    project_row = next((r for r in rows if r.get("scope") == "project"), None) or {}
    role_row = (
        next(
            (r for r in rows if r.get("scope") == "role" and r.get("subject_id") == role),
            None,
        )
        or {}
        if role
        else {}
    )
    default_provider = role_row.get("default_provider") or project_row.get("default_provider")
    default_model = role_row.get("default_model") or project_row.get("default_model")
    return ResolvedAiPolicy(
        default_provider=default_provider,
        default_model=default_model,
        allowed_providers=_merge_allowed(
            project_row.get("allowed_providers") or [], role_row.get("allowed_providers") or []
        ),
        allowed_tools=_merge_allowed(
            project_row.get("allowed_tools") or [], role_row.get("allowed_tools") or []
        ),
    )
