"""Build runtime registrations from inspected packages and explicit grants."""

from __future__ import annotations

from collections.abc import Sequence

from app.agent.plugins.hook_contract import HookRegistration, HookSource
from app.agent.plugins.hook_runner import hook_trust_profile
from app.plugin_platform.hook_trust_store import HookTrustStore
from app.plugin_platform.models import PluginHookComponent


def registrations_for_plugin(
    *,
    plugin_id: str,
    owner_id: str | None = None,
    components: Sequence[PluginHookComponent],
    enabled: bool,
    trust_store: HookTrustStore,
) -> list[HookRegistration]:
    """Convert valid inspections into registrations with separate trust state.

    Installation/enablement only controls ``enabled``. Trust is evaluated
    independently against the inspected digest and the exact isolation profile
    this runtime would require. Invalid or stale component digests are omitted.
    """

    registrations: list[HookRegistration] = []
    trust_owner_id = owner_id or plugin_id
    for component in components:
        if not component.valid or component.digest is None:
            continue
        definition = component.definition
        trusted = trust_store.is_trusted(
            owner_type="plugin",
            owner_id=trust_owner_id,
            hook_id=definition.hook_id,
            digest=component.digest,
            isolation_profile=hook_trust_profile(definition),
        )
        registrations.append(
            HookRegistration(
                hook_id=definition.hook_id,
                plugin_id=plugin_id,
                event=definition.event,
                source=HookSource.MANAGED_PLUGIN,
                definition=definition,
                digest=component.digest,
                trusted=trusted,
                enabled=enabled,
            )
        )
    return registrations


__all__ = ["registrations_for_plugin"]
