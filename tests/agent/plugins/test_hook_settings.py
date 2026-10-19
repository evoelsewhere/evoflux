"""Persistence and migration-default tests for Settings hook definitions."""

from pathlib import Path

from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
    HookMode,
)
from app.core.runtime_settings import (
    HookRuntimeSettings,
    RuntimeSettings,
    load_runtime_settings,
    load_runtime_settings_report,
    save_runtime_settings,
)


def _definition() -> HookDefinition:
    return HookDefinition(
        hook_id="session-bootstrap",
        event=HookEvent.SESSION_START,
        command=("./hooks/bootstrap.py",),
        timeout_seconds=10,
        input_fields=("session_id", "source"),
        output_fields=("context",),
        failure_policy=HookFailurePolicy.FAIL_OPEN,
    )


def test_missing_hooks_in_legacy_settings_defaults_to_empty_augment(tmp_path: Path):
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("providers: {}\n", encoding="utf-8")

    loaded = load_runtime_settings(settings_file)

    assert loaded.hooks == HookRuntimeSettings()
    assert loaded.hooks.mode is HookMode.AUGMENT


def test_hook_settings_round_trip_in_runtime_settings(tmp_path: Path):
    settings_file = tmp_path / "settings.yaml"
    original = RuntimeSettings(
        hooks=HookRuntimeSettings(
            mode=HookMode.REPLACE,
            replace_plugin_events=(HookEvent.TOOL_BEFORE,),
            definitions=(_definition(),),
        )
    )

    save_runtime_settings(original, settings_file)
    loaded = load_runtime_settings(settings_file)

    assert loaded.hooks == original.hooks


def test_invalid_hook_setting_is_pruned_and_reported(tmp_path: Path):
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("hooks:\n  mode: unsupported\n", encoding="utf-8")

    loaded, ignored = load_runtime_settings_report(settings_file)

    assert loaded.hooks.mode is HookMode.AUGMENT
    assert len(ignored) == 1
    assert ignored[0].field == "hooks.mode"
