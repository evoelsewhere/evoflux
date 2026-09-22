"""Fail-closed evaluation for declarative plugin policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.plugin_platform.models import (
    PluginPolicy,
    PluginPolicyCondition,
    PluginRunContext,
)

_MISSING = object()


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    matched_attribute: str | None = None
    policy_version: str = "1"


@dataclass(frozen=True, slots=True)
class ResourceOwnership:
    kind: Literal["connection", "credential", "cache", "report", "destination"]
    installation_id: str | None
    content_sha256: str | None
    workspace_id: str | None
    project_id: str | None
    tenant: str | None


def _lookup(context: dict[str, Any], attribute: str) -> Any:
    value: Any = context
    for part in attribute.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _matches(condition: PluginPolicyCondition, context: dict[str, Any]) -> bool:
    actual = _lookup(context, condition.attribute)
    if actual is _MISSING:
        return False
    expected: Any = condition.value
    try:
        if condition.operator == "eq":
            return actual == expected
        if condition.operator == "neq":
            return actual != expected
        if condition.operator == "in":
            return actual in expected
        if condition.operator == "not_in":
            return actual not in expected
        if condition.operator == "contains":
            return expected in actual
        if condition.operator == "not_contains":
            return expected not in actual
        if condition.operator == "starts_with":
            return isinstance(actual, str) and actual.startswith(str(expected))
        if condition.operator == "ends_with":
            return isinstance(actual, str) and actual.endswith(str(expected))
    except (TypeError, ValueError):
        return False
    return False


def evaluate_policy(
    policy: PluginPolicy | None, context: dict[str, Any]
) -> PolicyDecision:
    """Evaluate deny-first, then all/any policy clauses."""

    if policy is None:
        return PolicyDecision(True, "no policy declared")
    for condition in policy.deny:
        if _matches(condition, context):
            return PolicyDecision(
                False, "deny condition matched", condition.attribute, policy.version
            )
    if policy.all_conditions and not all(
        _matches(condition, context) for condition in policy.all_conditions
    ):
        return PolicyDecision(
            False, "required condition missing or failed", policy_version=policy.version
        )
    if policy.any_conditions and not any(
        _matches(condition, context) for condition in policy.any_conditions
    ):
        return PolicyDecision(
            False, "no any-condition matched", policy_version=policy.version
        )
    usage = context.get("usage", {})
    if policy.rate_limit is not None and (
        not isinstance(usage, dict) or usage.get("rate", 0) >= policy.rate_limit
    ):
        return PolicyDecision(
            False, "rate limit exceeded", policy_version=policy.version
        )
    if policy.quota is not None and (
        not isinstance(usage, dict) or usage.get("quota", 0) >= policy.quota
    ):
        return PolicyDecision(False, "quota exceeded", policy_version=policy.version)
    return PolicyDecision(True, "policy allowed", policy_version=policy.version)


def enforce_resource_ownership(
    context: PluginRunContext, resource: ResourceOwnership
) -> None:
    """Reject resources whose immutable owner does not match the run context."""

    expected = {
        "installation_id": context.installation_id,
        "content_sha256": context.content_sha256,
        "workspace_id": context.workspace_id,
        "project_id": context.project_id,
        "tenant": context.tenant,
    }
    for field, value in expected.items():
        owner = getattr(resource, field)
        if owner is None or owner != value:
            raise PermissionError(
                f"Resource ownership mismatch: {resource.kind}.{field}"
            )


def authorize_policy(policy: PluginPolicy | None, context: dict[str, Any]) -> None:
    decision = evaluate_policy(policy, context)
    if not decision.allowed:
        raise PermissionError(decision.reason)


__all__ = [
    "PolicyDecision",
    "ResourceOwnership",
    "authorize_policy",
    "enforce_resource_ownership",
    "evaluate_policy",
]
