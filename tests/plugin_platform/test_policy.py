from __future__ import annotations

import pytest

from app.plugin_platform.models import PluginPolicy
from app.plugin_platform.policy import authorize_policy, evaluate_policy


def test_policy_evaluates_all_and_any_with_nested_context() -> None:
    policy = PluginPolicy.model_validate(
        {
            "all": [
                {"attribute": "workspace.authorized", "operator": "eq", "value": True}
            ],
            "any": [
                {"attribute": "role", "operator": "eq", "value": "admin"},
                {"attribute": "role", "operator": "eq", "value": "analyst"},
            ],
        }
    )

    assert evaluate_policy(
        policy, {"workspace": {"authorized": True}, "role": "analyst"}
    ).allowed
    assert not evaluate_policy(
        policy, {"workspace": {"authorized": True}, "role": "viewer"}
    ).allowed


def test_policy_rejects_unknown_provenance_and_untrusted_prompt_context() -> None:
    policy = PluginPolicy.model_validate(
        {
            "all": [
                {"attribute": "provenance.verified", "operator": "eq", "value": True},
                {"attribute": "tenant", "operator": "eq", "value": "tenant-a"},
            ]
        }
    )

    assert not evaluate_policy(
        policy,
        {
            "tenant": "tenant-a",
            "prompt": {"requested_tenant": "tenant-b", "requested_operation": "export"},
        },
    ).allowed


def test_policy_rate_and_quota_fail_closed() -> None:
    policy = PluginPolicy.model_validate({"rateLimit": 2, "quota": 5})

    assert evaluate_policy(policy, {"usage": {"rate": 1, "quota": 4}}).allowed
    assert (
        evaluate_policy(policy, {"usage": {"rate": 2, "quota": 0}}).reason
        == "rate limit exceeded"
    )
    assert (
        evaluate_policy(policy, {"usage": {"rate": 0, "quota": 5}}).reason
        == "quota exceeded"
    )


def test_policy_deny_takes_precedence_and_missing_fails_closed() -> None:
    policy = PluginPolicy.model_validate(
        {
            "all": [{"attribute": "tenant", "operator": "eq", "value": "a"}],
            "deny": [
                {"attribute": "classification", "operator": "eq", "value": "restricted"}
            ],
        }
    )

    denied = evaluate_policy(policy, {"tenant": "a", "classification": "restricted"})
    assert not denied.allowed
    assert denied.matched_attribute == "classification"
    assert not evaluate_policy(policy, {"classification": "public"}).allowed
    with pytest.raises(PermissionError):
        authorize_policy(policy, {"tenant": "b"})
