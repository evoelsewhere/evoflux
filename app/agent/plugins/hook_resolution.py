"""Pure resolution and output merging for lifecycle hook registrations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agent.plugins.hook_contract import (
    HookEvent,
    HookMode,
    HookRegistration,
    HookSettingsPolicy,
    HookSource,
    HookTarget,
    validate_hook_output,
)


@dataclass(frozen=True, slots=True)
class HookRegistrationStatus:
    registration: HookRegistration
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class EffectiveHooks:
    """Ordered configurable hooks plus immutable runtime hook identities."""

    ordered: tuple[HookRegistration, ...]
    protected_hooks: tuple[Any, ...]
    statuses: tuple[HookRegistrationStatus, ...]


@dataclass(frozen=True, slots=True)
class HookOutcome:
    registration: HookRegistration
    output: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EventDecision:
    event: HookEvent
    denied: bool
    reason: str | None
    values: Mapping[str, Any]


def _plugin_target(registration: HookRegistration) -> HookTarget:
    if registration.plugin_id is None:
        raise ValueError("plugin registration is missing plugin_id")
    return HookTarget(plugin_id=registration.plugin_id, hook_id=registration.hook_id)


def _source_order(source: HookSource) -> int:
    if source in {HookSource.MANAGED_PLUGIN, HookSource.LEGACY_PYTHON}:
        return 0
    return 1


def _registration_order(registration: HookRegistration) -> tuple[int, str, str]:
    return (
        _source_order(registration.source),
        registration.plugin_id or "",
        registration.hook_id,
    )


def resolve_event_hooks(
    event: HookEvent,
    settings_policy: HookSettingsPolicy,
    *,
    settings_registrations: Sequence[HookRegistration],
    plugin_registrations: Sequence[HookRegistration],
    protected_hooks: Sequence[Any] = (),
) -> EffectiveHooks:
    """Resolve one event without allowing Settings to filter protected hooks.

    Package and legacy Python registrations are always ordered before Settings
    registrations so Settings output can take precedence during merge.
    """

    settings_for_event = [
        registration
        for registration in settings_registrations
        if registration.event is event and registration.source is HookSource.SETTINGS
    ]
    plugin_for_event = [
        registration
        for registration in plugin_registrations
        if registration.event is event
        and registration.source in {HookSource.MANAGED_PLUGIN, HookSource.LEGACY_PYTHON}
    ]

    ordered_settings = sorted(settings_for_event, key=_registration_order)
    ordered_plugins = sorted(plugin_for_event, key=_registration_order)
    active_settings = [
        registration
        for registration in ordered_settings
        if registration.enabled and registration.trusted
    ]
    override_targets = {
        target
        for registration in active_settings
        if registration.definition is not None
        for target in registration.definition.overrides
    }
    disabled_targets = set(settings_policy.disabled_plugin_hooks)
    replace_event = (
        settings_policy.mode is HookMode.REPLACE
        and event in settings_policy.replace_plugin_events
    )

    active_plugins: list[HookRegistration] = []
    statuses: list[HookRegistrationStatus] = []
    for registration in ordered_plugins:
        target = _plugin_target(registration)
        if not registration.enabled:
            status, reason = "disabled", "plugin hook is disabled"
        elif target in disabled_targets:
            status, reason = "disabled_by_settings", "disabled in global Settings"
        elif replace_event:
            status, reason = "replaced_by_settings", "event is in Settings replace mode"
        elif not registration.trusted:
            status, reason = "awaiting_trust", "current hook digest is not trusted"
        elif target in override_targets:
            status, reason = (
                "shadowed_by_settings",
                "targeted by a trusted Settings hook",
            )
        else:
            status, reason = "active", None
            active_plugins.append(registration)
        statuses.append(HookRegistrationStatus(registration, status, reason))

    active_settings_ordered: list[HookRegistration] = []
    for registration in ordered_settings:
        if not registration.enabled:
            status, reason = "disabled", "Settings hook is disabled"
        elif not registration.trusted:
            status, reason = "awaiting_trust", "current hook digest is not trusted"
        else:
            status, reason = "active", None
            active_settings_ordered.append(registration)
        statuses.append(HookRegistrationStatus(registration, status, reason))

    return EffectiveHooks(
        ordered=tuple(active_plugins + active_settings_ordered),
        protected_hooks=tuple(protected_hooks),
        statuses=tuple(statuses),
    )


def merge_hook_outputs(
    event: HookEvent,
    outcomes: Iterable[HookOutcome],
) -> EventDecision:
    """Apply deterministic output priority while retaining every denial.

    Replaceable output values use last-writer-wins order with Settings after
    plugin hooks. A true ``deny`` is monotonic and no later output can clear it.
    """

    ordered_outcomes = sorted(
        outcomes,
        key=lambda outcome: _registration_order(outcome.registration),
    )
    values: dict[str, Any] = {}
    deny_reasons: list[str] = []
    denied = False

    for outcome in ordered_outcomes:
        registration = outcome.registration
        if registration.event is not event:
            raise ValueError("hook outcome event does not match merge event")
        if not registration.trusted or not registration.enabled:
            raise ValueError("untrusted or disabled hook outcome cannot be merged")

        if registration.definition is None:
            if outcome.output:
                raise ValueError("legacy hook adapter cannot return declarative output")
            continue

        validated = validate_hook_output(
            event,
            registration.definition.output_fields,
            dict(outcome.output),
        )
        if validated.get("deny") is True:
            denied = True
            reason = validated.get("reason")
            if reason:
                deny_reasons.append(reason)

        for name, value in validated.items():
            if name not in {"deny", "reason"}:
                values[name] = value

    return EventDecision(
        event=event,
        denied=denied,
        reason=deny_reasons[0] if deny_reasons else None,
        values=values,
    )
