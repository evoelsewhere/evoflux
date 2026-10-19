"""The plugin enable bit must never imply hook execution trust."""

from pathlib import Path

from app.agent.plugins.hook_contract import HookSource
from app.plugin_platform.hook_runtime import registrations_for_plugin
from app.plugin_platform.hook_trust_store import HookTrustGrant, HookTrustStore
from app.plugin_platform.hook_inspection import inspect_plugin_hooks
from app.plugin_platform.models import PluginManifest


def test_plugin_registration_requires_matching_digest_and_profile(
    tmp_path: Path,
) -> None:
    script = tmp_path / "hooks" / "startup.py"
    script.parent.mkdir()
    script.write_text("print('ok')\n")
    manifest = PluginManifest.model_validate(
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "example-plugin",
            "extensions": {
                "com.evoflux.hooks": {
                    "version": 1,
                    "hooks": [
                        {
                            "hook_id": "startup",
                            "event": "session.start",
                            "command": ["./hooks/startup.py"],
                            "timeout_seconds": 5,
                            "input_fields": ["source"],
                            "output_fields": ["context"],
                            "failure_policy": "fail_open",
                        }
                    ],
                }
            },
        }
    )
    inspection = inspect_plugin_hooks(tmp_path, manifest)
    component = inspection.hooks[0]
    store = HookTrustStore(tmp_path / "trust.json")
    store.approve(
        HookTrustGrant(
            owner_type="plugin",
            owner_id="example-plugin",
            hook_id="startup",
            digest=component.digest,
            isolation_profile="different-profile",
        )
    )

    registration = registrations_for_plugin(
        plugin_id="example-plugin",
        components=inspection.hooks,
        enabled=True,
        trust_store=store,
    )[0]

    assert registration.source is HookSource.MANAGED_PLUGIN
    assert registration.enabled is True
    assert registration.trusted is False


def test_disabled_plugin_hook_cannot_become_enabled_from_trust(tmp_path: Path) -> None:
    script = tmp_path / "startup.py"
    script.write_text("print('ok')\n")
    manifest = PluginManifest.model_validate(
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "example-plugin",
            "extensions": {
                "com.evoflux.hooks": {
                    "version": 1,
                    "hooks": [
                        {
                            "hook_id": "startup",
                            "event": "session.start",
                            "command": ["./startup.py"],
                            "timeout_seconds": 5,
                            "input_fields": ["source"],
                            "output_fields": [],
                            "failure_policy": "fail_open",
                        }
                    ],
                }
            },
        }
    )
    component = inspect_plugin_hooks(tmp_path, manifest).hooks[0]
    store = HookTrustStore(tmp_path / "trust.json")
    store.approve(
        HookTrustGrant(
            owner_type="plugin",
            owner_id="example-plugin",
            hook_id="startup",
            digest=component.digest,
            isolation_profile="evoflux-plugin-hook-v2",
        )
    )

    registration = registrations_for_plugin(
        plugin_id="example-plugin",
        components=[component],
        enabled=False,
        trust_store=store,
    )[0]

    assert registration.trusted is True
    assert registration.enabled is False


def test_static_context_approval_uses_a_distinct_capability_profile(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "skills" / "using-superpowers" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("reviewed context", encoding="utf-8")
    manifest = PluginManifest.model_validate(
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "static-context-plugin",
            "extensions": {
                "com.evoflux.hooks": {
                    "version": 1,
                    "hooks": [
                        {
                            "hook_id": "context",
                            "event": "session.start",
                            "command": ["./skills/using-superpowers/SKILL.md"],
                            "execution_kind": "static_context",
                            "timeout_seconds": 1,
                            "output_fields": ["context"],
                            "failure_policy": "fail_open",
                        }
                    ],
                }
            },
        }
    )
    component = inspect_plugin_hooks(tmp_path, manifest).hooks[0]
    store = HookTrustStore(tmp_path / "trust.json")
    store.approve(
        HookTrustGrant(
            owner_type="plugin",
            owner_id="static-context-plugin",
            hook_id="context",
            digest=component.digest,
            isolation_profile="evoflux-plugin-hook-v2",
        )
    )
    assert not registrations_for_plugin(
        plugin_id="static-context-plugin",
        components=[component],
        enabled=True,
        trust_store=store,
    )[0].trusted

    store.approve(
        HookTrustGrant(
            owner_type="plugin",
            owner_id="static-context-plugin",
            hook_id="context",
            digest=component.digest,
            isolation_profile="evoflux-static-context-v1",
        )
    )
    registration = registrations_for_plugin(
        plugin_id="static-context-plugin",
        components=[component],
        enabled=True,
        trust_store=store,
    )[0]
    assert registration.trusted is True
    assert registration.enabled is True
