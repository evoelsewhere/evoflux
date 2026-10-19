from __future__ import annotations

import pytest

from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
    HookMode,
    HookRegistration,
    HookSettingsPolicy,
    HookSource,
    HookTarget,
)
from app.agent.plugins.hook_resolution import (
    HookOutcome,
    resolve_event_hooks,
    merge_hook_outputs,
)


def _definition(
    hook_id: str,
    event: HookEvent,
    *,
    output_fields: tuple[str, ...] = (),
    overrides: tuple[HookTarget, ...] = (),
) -> HookDefinition:
    return HookDefinition(
        hook_id=hook_id,
        event=event,
        command=("python", "./hooks/run.py"),
        timeout_seconds=5,
        input_fields=(),
        output_fields=output_fields,
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
        overrides=overrides,
    )


def _plugin(
    plugin_id: str,
    hook_id: str,
    *,
    event: HookEvent = HookEvent.TOOL_BEFORE,
    trusted: bool = True,
    enabled: bool = True,
) -> HookRegistration:
    definition = _definition(
        hook_id,
        event,
        output_fields=("arguments", "deny", "reason")
        if event is HookEvent.TOOL_BEFORE
        else (),
    )
    return HookRegistration(
        hook_id=hook_id,
        event=event,
        source=HookSource.MANAGED_PLUGIN,
        plugin_id=plugin_id,
        definition=definition,
        digest="a" * 64,
        trusted=trusted,
        enabled=enabled,
    )


def _settings(
    hook_id: str,
    *,
    event: HookEvent = HookEvent.TOOL_BEFORE,
    overrides: tuple[HookTarget, ...] = (),
) -> HookRegistration:
    definition = _definition(
        hook_id,
        event,
        output_fields=("arguments", "deny", "reason")
        if event is HookEvent.TOOL_BEFORE
        else ("context",),
        overrides=overrides,
    )
    return HookRegistration(
        hook_id=hook_id,
        event=event,
        source=HookSource.SETTINGS,
        definition=definition,
        digest="b" * 64,
        trusted=True,
    )


def test_augment_runs_trusted_enabled_plugins_then_settings() -> None:
    plugin_b = _plugin("plugin-b", "second")
    plugin_a = _plugin("plugin-a", "first")
    settings = _settings("user-policy")

    effective = resolve_event_hooks(
        HookEvent.TOOL_BEFORE,
        HookSettingsPolicy(mode=HookMode.AUGMENT),
        settings_registrations=[settings],
        plugin_registrations=[plugin_b, plugin_a],
        protected_hooks=["permission-check"],
    )

    assert [(item.plugin_id, item.hook_id) for item in effective.ordered] == [
        ("plugin-a", "first"),
        ("plugin-b", "second"),
        (None, "user-policy"),
    ]
    assert effective.protected_hooks == ("permission-check",)


def test_settings_override_matches_exact_plugin_and_hook_identity() -> None:
    targeted = _plugin("plugin-a", "shared-hook")
    other_plugin = _plugin("plugin-b", "shared-hook")
    settings = _settings(
        "user-replacement",
        overrides=(HookTarget(plugin_id="plugin-a", hook_id="shared-hook"),),
    )

    effective = resolve_event_hooks(
        HookEvent.TOOL_BEFORE,
        HookSettingsPolicy(),
        settings_registrations=[settings],
        plugin_registrations=[targeted, other_plugin],
    )

    assert [(item.plugin_id, item.hook_id) for item in effective.ordered] == [
        ("plugin-b", "shared-hook"),
        (None, "user-replacement"),
    ]
    assert [
        (
            status.registration.plugin_id,
            status.registration.hook_id,
            status.status,
        )
        for status in effective.statuses
    ] == [
        ("plugin-a", "shared-hook", "shadowed_by_settings"),
        ("plugin-b", "shared-hook", "active"),
        (None, "user-replacement", "active"),
    ]


def test_replace_filters_only_selected_plugin_events_and_preserves_protected() -> None:
    tool_hook = _plugin("plugin-a", "tool-hook")
    model_hook = _plugin("plugin-a", "model-hook", event=HookEvent.MODEL_AFTER)
    settings = _settings("user-tool-hook")

    effective = resolve_event_hooks(
        HookEvent.TOOL_BEFORE,
        HookSettingsPolicy(
            mode=HookMode.REPLACE,
            replace_plugin_events=(HookEvent.TOOL_BEFORE,),
        ),
        settings_registrations=[settings],
        plugin_registrations=[tool_hook, model_hook],
        protected_hooks=["core-tool-authorization"],
    )

    assert [item.hook_id for item in effective.ordered] == ["user-tool-hook"]
    assert effective.protected_hooks == ("core-tool-authorization",)
    assert [
        (status.registration.hook_id, status.status) for status in effective.statuses
    ] == [
        ("tool-hook", "replaced_by_settings"),
        ("user-tool-hook", "active"),
    ]


def test_replace_status_takes_precedence_over_plugin_trust_state() -> None:
    plugin_hook = _plugin(
        "vendor.plugin",
        "plugin-hook",
        event=HookEvent.SESSION_START,
        trusted=False,
    )

    effective = resolve_event_hooks(
        HookEvent.SESSION_START,
        HookSettingsPolicy(
            mode=HookMode.REPLACE,
            replace_plugin_events=(HookEvent.SESSION_START,),
        ),
        settings_registrations=(),
        plugin_registrations=(plugin_hook,),
    )

    assert effective.ordered == ()
    assert effective.statuses[0].status == "replaced_by_settings"


@pytest.mark.parametrize(
    ("trusted", "enabled", "expected_status"),
    [(False, True, "awaiting_trust"), (True, False, "disabled")],
)
def test_untrusted_or_disabled_plugin_is_not_dispatched(
    trusted: bool,
    enabled: bool,
    expected_status: str,
) -> None:
    effective = resolve_event_hooks(
        HookEvent.TOOL_BEFORE,
        HookSettingsPolicy(),
        settings_registrations=[],
        plugin_registrations=[
            _plugin("plugin-a", "hook", trusted=trusted, enabled=enabled)
        ],
    )

    assert effective.ordered == ()
    assert effective.statuses[0].status == expected_status


def test_settings_output_wins_but_deny_is_sticky() -> None:
    plugin = _plugin("plugin-a", "plugin-hook")
    settings = _settings("user-hook")
    plugin_outcome = HookOutcome(
        registration=plugin,
        output={"arguments": {"mode": "plugin"}, "deny": True, "reason": "blocked"},
    )
    settings_outcome = HookOutcome(
        registration=settings,
        output={"arguments": {"mode": "settings"}, "deny": False},
    )

    decision = merge_hook_outputs(
        HookEvent.TOOL_BEFORE,
        [settings_outcome, plugin_outcome],
    )

    assert decision.values["arguments"] == {"mode": "settings"}
    assert decision.denied is True
    assert decision.reason == "blocked"


def test_merge_rejects_output_not_declared_by_hook() -> None:
    plugin = _plugin("plugin-a", "plugin-hook")
    outcome = HookOutcome(registration=plugin, output={"allow": True})

    with pytest.raises(ValueError, match="undeclared"):
        merge_hook_outputs(HookEvent.TOOL_BEFORE, [outcome])
