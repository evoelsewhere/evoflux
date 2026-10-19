from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.plugin_platform.extensions import HOOKS_EXTENSION
from app.plugin_platform.models import PLUGIN_SCHEMA_ID
from app.plugin_platform.validator import inspect_plugin


def _write_plugin(root: Path, hooks: object) -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_ID,
                "name": "hook-fixture",
                "extensions": {HOOKS_EXTENSION: hooks},
            }
        ),
        encoding="utf-8",
    )
    script = root / "hooks" / "startup.py"
    script.parent.mkdir()
    script.write_text("print('{}')\n", encoding="utf-8")
    return root


def _hook(**overrides: object) -> dict[str, object]:
    return {
        "hook_id": "bootstrap",
        "event": "session.start",
        "command": ["./hooks/startup.py"],
        "timeout_seconds": 10,
        "input_fields": ["session_id", "source"],
        "output_fields": ["context"],
        "failure_policy": "fail_open",
        **overrides,
    }


def test_inspects_package_hook_without_executing_and_hashes_content(
    tmp_path: Path,
) -> None:
    root = _write_plugin(
        tmp_path / "plugin",
        {
            "version": 1,
            "hooks": [
                _hook(
                    matcher={"source": "create"},
                    timeout_seconds=20,
                    failure_policy="fail_closed",
                )
            ],
        },
    )

    before = inspect_plugin(root)

    assert before.valid is True
    assert len(before.hooks) == 1
    hook = before.hooks[0]
    assert hook.valid is True
    assert hook.command_path == "hooks/startup.py"
    assert hook.digest is not None
    disclosure = before.trust.hooks[0]
    assert disclosure.matcher == {"source": "create"}
    assert disclosure.timeout_seconds == 20
    assert disclosure.failure_policy == "fail_closed"
    assert disclosure.environment_fields == ["EVOFLUX_HOOK_PROTOCOL"]
    assert disclosure.isolation_profile == "evoflux-plugin-hook-v2"

    (root / "hooks" / "startup.py").write_text("print('changed')\n")
    after = inspect_plugin(root)

    assert after.hooks[0].digest != hook.digest


def test_invalid_hook_path_is_inspectable_but_not_valid_for_execution(
    tmp_path: Path,
) -> None:
    root = _write_plugin(
        tmp_path / "plugin",
        {"version": 1, "hooks": [_hook(command=["./../outside.py"])]},
    )

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert len(inspection.hooks) == 1
    assert inspection.hooks[0].valid is False
    assert inspection.hooks[0].digest is None
    assert any(
        item.code == "hook-definition-invalid"
        for item in inspection.hooks[0].diagnostics
    )


def test_unsupported_hook_extension_version_does_not_invalidate_plugin(
    tmp_path: Path,
) -> None:
    root = _write_plugin(tmp_path / "plugin", {"version": 99, "hooks": [_hook()]})

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert inspection.hooks == []
    assert any(
        item.code == "hooks-version-unsupported" for item in inspection.diagnostics
    )


def test_malformed_hook_declaration_is_diagnostic_only(
    tmp_path: Path,
) -> None:
    root = _write_plugin(
        tmp_path / "malformed-hook",
        {"version": 1, "hooks": [None]},
    )

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert inspection.hooks == []
    assert any(
        item.code == "hook-definition-invalid" and "must be an object" in item.message
        for item in inspection.diagnostics
    )


def test_package_without_hooks_extension_keeps_default_plugin_inspection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugin-without-hooks"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_ID, "name": "no-hooks"}),
        encoding="utf-8",
    )

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert inspection.hooks == []
    assert not any(item.scope == "hooks" for item in inspection.diagnostics)


@pytest.mark.parametrize(
    ("command", "message"),
    [
        (["C:/outside/hook.py"], "package-relative"),
        (["./hooks/missing.py"], "does not exist"),
    ],
)
def test_unsafe_or_missing_hook_command_is_not_executable(
    tmp_path: Path, command: list[str], message: str
) -> None:
    root = _write_plugin(
        tmp_path / "invalid-command",
        {"version": 1, "hooks": [_hook(command=command)]},
    )

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert len(inspection.hooks) == 1
    component = inspection.hooks[0]
    assert component.valid is False
    assert component.digest is None
    assert message in component.diagnostics[0].message


def test_duplicate_hook_ids_are_isolated_to_invalid_declaration(
    tmp_path: Path,
) -> None:
    root = _write_plugin(
        tmp_path / "duplicate-hooks",
        {"version": 1, "hooks": [_hook(), _hook()]},
    )

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert len(inspection.hooks) == 2
    assert inspection.hooks[0].valid is True
    assert inspection.hooks[1].valid is False
    assert "unique" in inspection.hooks[1].diagnostics[0].message


def test_directory_command_is_rejected_as_non_file(
    tmp_path: Path,
) -> None:
    root = _write_plugin(
        tmp_path / "directory-command",
        {"version": 1, "hooks": [_hook(command=["./hooks"])]},
    )

    inspection = inspect_plugin(root)

    assert len(inspection.hooks) == 1
    assert inspection.hooks[0].valid is False
    assert "regular file" in inspection.hooks[0].diagnostics[0].message


def test_symlink_command_is_rejected_when_symlinks_are_available(
    tmp_path: Path,
) -> None:
    root = _write_plugin(
        tmp_path / "symlink-command",
        {"version": 1, "hooks": [_hook(command=["./hooks/external.py"])]},
    )
    external = tmp_path / "external.py"
    external.write_text("print('{}')\n", encoding="utf-8")
    command_path = root / "hooks" / "external.py"
    try:
        command_path.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available for this account")

    inspection = inspect_plugin(root)

    assert len(inspection.hooks) == 1
    assert inspection.hooks[0].valid is False
    assert "symlinks" in inspection.hooks[0].diagnostics[0].message


def test_declared_auxiliary_file_is_part_of_hook_digest(tmp_path: Path) -> None:
    root = _write_plugin(
        tmp_path / "multi-file-plugin",
        {"version": 1, "hooks": [_hook(runtime="python", files=["./hooks/helper.py"])]},
    )
    helper = root / "hooks" / "helper.py"
    helper.write_text("VALUE = 'approved'\n", encoding="utf-8")

    before = inspect_plugin(root).hooks[0]
    assert before.valid is True
    assert before.digest is not None

    helper.write_text("VALUE = 'changed'\n", encoding="utf-8")
    after = inspect_plugin(root).hooks[0]

    assert after.digest != before.digest


def test_missing_or_symlinked_auxiliary_file_is_not_executable(tmp_path: Path) -> None:
    root = _write_plugin(
        tmp_path / "missing-auxiliary",
        {"version": 1, "hooks": [_hook(runtime="python", files=["./hooks/helper.py"])]},
    )

    missing = inspect_plugin(root).hooks[0]
    assert missing.valid is False
    assert missing.digest is None

    helper = root / "hooks" / "helper.py"
    helper.write_text("VALUE = 1\n", encoding="utf-8")
    external = tmp_path / "external-helper.py"
    external.write_text("VALUE = 2\n", encoding="utf-8")
    helper.unlink()
    try:
        helper.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available for this account")

    symlinked = inspect_plugin(root).hooks[0]
    assert symlinked.valid is False
    assert symlinked.digest is None
