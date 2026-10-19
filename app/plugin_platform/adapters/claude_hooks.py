"""Translate one reviewed Claude hook pattern without running its command."""

from __future__ import annotations

import json
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
)
from app.agent.plugins.hook_runner import MAX_HOOK_OUTPUT_BYTES
from app.plugin_platform.hook_inspection import hook_digest
from app.plugin_platform.models import (
    HookInspection,
    PluginDiagnostic,
    PluginHookComponent,
)

_CLAUDE_HOOK_MANIFEST_MAX_BYTES = 256 * 1024
_SUPERPOWERS_PLUGIN_NAME = "superpowers"
_SUPERPOWERS_MATCHER = "startup|clear|compact"
_SUPERPOWERS_COMMAND = '"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start'
_SUPERPOWERS_CONTEXT_PREFIX = (
    "<EXTREMELY_IMPORTANT>\n"
    "You have superpowers.\n\n"
    "**Below is the full content of your 'superpowers:using-superpowers' skill - "
    "your introduction to using skills. For all other skills, use the 'Skill' tool:**\n\n"
)
_SUPERPOWERS_CONTEXT_SUFFIX = "\n</EXTREMELY_IMPORTANT>"


def _warning(code: str, message: str) -> PluginDiagnostic:
    return PluginDiagnostic(
        severity="warning",
        code=code,
        message=message,
        scope="hooks",
    )


def _read_hook_manifest(path: Path) -> dict[str, Any]:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ValueError("hooks/hooks.json must be a regular non-symlink file")
        if path.stat().st_size > _CLAUDE_HOOK_MANIFEST_MAX_BYTES:
            raise ValueError("Claude hook manifest exceeds the size limit")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Claude hook manifest is unreadable or invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Claude hook manifest must be a JSON object")
    return data


def _is_supported_superpowers_shape(
    manifest: dict[str, Any],
    hook_manifest: dict[str, Any],
) -> bool:
    name = manifest.get("name")
    if not isinstance(name, str) or name.casefold() != _SUPERPOWERS_PLUGIN_NAME:
        return False
    hooks = hook_manifest.get("hooks")
    if not isinstance(hooks, dict) or set(hooks) != {"SessionStart"}:
        return False
    groups = hooks["SessionStart"]
    if not isinstance(groups, list) or len(groups) != 1:
        return False
    group = groups[0]
    if not isinstance(group, dict) or set(group) != {"matcher", "hooks"}:
        return False
    if group.get("matcher") != _SUPERPOWERS_MATCHER:
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list) or len(handlers) != 1:
        return False
    return handlers[0] == {
        "type": "command",
        "command": _SUPERPOWERS_COMMAND,
        "shell": "bash",
        "async": False,
    }


def adapt_claude_hooks(
    source_root: str | Path,
    normalized_root: str | Path,
    source_manifest: dict[str, Any],
) -> HookInspection:
    """Convert the exact Superpowers session bootstrap to static context.

    The upstream shell launcher is deliberately neither copied nor executed.
    The adapted declaration reads only the installed Skill file after explicit
    digest-bound trust. Other Claude hook shapes remain unsupported.
    """

    source = Path(source_root)
    destination = Path(normalized_root)
    manifest_path = source / "hooks" / "hooks.json"
    if not manifest_path.exists():
        return HookInspection(
            diagnostics=[
                _warning(
                    "claude-hook-manifest-missing",
                    "Claude hook declarations require hooks/hooks.json.",
                )
            ]
        )
    try:
        hook_manifest = _read_hook_manifest(manifest_path)
    except ValueError as exc:
        return HookInspection(
            diagnostics=[_warning("claude-hook-manifest-invalid", str(exc))]
        )
    if not _is_supported_superpowers_shape(source_manifest, hook_manifest):
        return HookInspection(
            diagnostics=[
                _warning(
                    "claude-hook-unsupported",
                    "Claude hooks are unsupported except the exact Superpowers "
                    "SessionStart skill-context bootstrap.",
                )
            ]
        )

    skill_relative = PurePosixPath("skills/using-superpowers/SKILL.md")
    skill_path = destination.joinpath(*skill_relative.parts)
    current = destination
    try:
        for part in skill_relative.parts:
            current = current / part
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("Superpowers Skill paths cannot contain symlinks")
        if not stat.S_ISREG(skill_path.stat().st_mode):
            raise ValueError("Superpowers using-superpowers Skill is not a file")
        skill_bytes = skill_path.read_bytes()
    except (OSError, ValueError) as exc:
        return HookInspection(
            diagnostics=[
                _warning(
                    "claude-hook-skill-unavailable",
                    f"Superpowers bootstrap could not be adapted: {exc}",
                )
            ]
        )

    try:
        skill_text = skill_bytes.decode("utf-8")
    except UnicodeError as exc:
        return HookInspection(
            diagnostics=[
                _warning(
                    "claude-hook-skill-invalid",
                    f"Skill cannot be trusted: {exc}",
                )
            ]
        )

    if (
        len(skill_bytes)
        + len(_SUPERPOWERS_CONTEXT_PREFIX.encode("utf-8"))
        + len(_SUPERPOWERS_CONTEXT_SUFFIX.encode("utf-8"))
        > MAX_HOOK_OUTPUT_BYTES
        or len(skill_text)
        + len(_SUPERPOWERS_CONTEXT_PREFIX)
        + len(_SUPERPOWERS_CONTEXT_SUFFIX)
        > 32_000
    ):
        return HookInspection(
            diagnostics=[
                _warning(
                    "claude-hook-context-too-large",
                    "Superpowers bootstrap Skill exceeds the bounded context size.",
                )
            ]
        )
    try:
        definition = HookDefinition(
            hook_id="superpowers.session-start",
            event=HookEvent.SESSION_START,
            command=(f"./{skill_relative.as_posix()}",),
            execution_kind="static_context",
            timeout_seconds=1,
            output_fields=("context",),
            failure_policy=HookFailurePolicy.FAIL_OPEN,
            context_prefix=_SUPERPOWERS_CONTEXT_PREFIX,
            context_suffix=_SUPERPOWERS_CONTEXT_SUFFIX,
        )
        digest = hook_digest(destination, definition)
    except (UnicodeError, OSError, ValueError) as exc:
        return HookInspection(
            diagnostics=[
                _warning("claude-hook-skill-invalid", f"Skill cannot be trusted: {exc}")
            ]
        )

    return HookInspection(
        hooks=[
            PluginHookComponent(
                definition=definition,
                command_path=skill_relative.as_posix(),
                digest=digest,
                valid=True,
            )
        ]
    )


__all__ = ["adapt_claude_hooks"]
