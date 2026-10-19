"""Inspect declarative package hooks without executing package content."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import ValidationError

from app.agent.plugins.hook_contract import HookDefinition
from app.plugin_platform.extensions import HOOKS_EXTENSION
from app.plugin_platform.models import (
    HookInspection,
    PluginDiagnostic,
    PluginHookComponent,
    PluginManifest,
)

MAX_HOOKS_BYTES = 256 * 1024
MAX_HOOKS = 128
MAX_HOOK_EXECUTABLE_BYTES = 20 * 1024 * 1024
MAX_HOOK_FILES = 128
MAX_HOOK_TOTAL_FILE_BYTES = 100 * 1024 * 1024


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: Literal["warning", "error"] = "error",
) -> PluginDiagnostic:
    return PluginDiagnostic(
        severity=severity,
        code=code,
        message=message,
        scope="hooks",
    )


def _resolve_package_file(root: Path, relative: str) -> tuple[Path, str]:
    if not relative.startswith("./"):
        raise ValueError("hook files must use package-relative ./ paths")
    raw_parts = relative[2:].replace("\\", "/").split("/")
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("hook executable path contains an invalid component")
    path = root
    for part in raw_parts:
        path = path / part
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise ValueError("hook executable does not exist") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("hook file paths must not contain symlinks")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("hook files must be regular files")
    if path.stat().st_size > MAX_HOOK_EXECUTABLE_BYTES:
        raise ValueError(
            f"hook file exceeds the {MAX_HOOK_EXECUTABLE_BYTES}-byte limit"
        )
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("hook file resolves outside the plugin root") from exc
    return path, PurePosixPath(*raw_parts).as_posix()


def _resolve_executable(root: Path, command: tuple[str, ...]) -> tuple[Path, str]:
    try:
        return _resolve_package_file(root, command[0])
    except ValueError as exc:
        if "package-relative" in str(exc):
            raise ValueError(
                "hook executable must be a package-relative ./ path"
            ) from exc
        raise


def hook_digest(
    root: str | Path,
    definition: HookDefinition,
    *,
    referenced_bytes: bytes | None = None,
) -> str:
    """Hash the normalized hook definition and referenced executable bytes."""

    package_root = Path(root).resolve(strict=True)
    executable, relative = _resolve_executable(package_root, definition.command)
    referenced: list[tuple[Path, str]] = [(executable, relative)]
    for declared in definition.files:
        path, normalized = _resolve_package_file(package_root, declared)
        if normalized == relative:
            continue
        referenced.append((path, normalized))
    if len(referenced) > MAX_HOOK_FILES:
        raise ValueError(f"hook exceeds the {MAX_HOOK_FILES}-file limit")
    if sum(path.stat().st_size for path, _ in referenced) > MAX_HOOK_TOTAL_FILE_BYTES:
        raise ValueError(
            f"hook files exceed the {MAX_HOOK_TOTAL_FILE_BYTES}-byte total limit"
        )
    payload = json.dumps(
        definition.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(payload)
    digest.update(b"\0")
    for path, file_relative in sorted(referenced, key=lambda item: item[1]):
        digest.update(file_relative.encode("utf-8"))
        digest.update(b"\0")
        if referenced_bytes is not None and path == executable:
            digest.update(referenced_bytes)
        else:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def inspect_plugin_hooks(
    plugin_root: str | Path, manifest: PluginManifest
) -> HookInspection:
    """Validate hook declarations, paths, and digests without launching them."""

    extension: Any = manifest.extensions.get(HOOKS_EXTENSION)
    if extension is None:
        return HookInspection()
    if not isinstance(extension, dict):
        return HookInspection(
            diagnostics=[
                _diagnostic(
                    "hooks-extension-invalid", "Hooks extension must be an object."
                )
            ]
        )

    try:
        extension_size = len(
            json.dumps(extension, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
    except (TypeError, ValueError):
        extension_size = MAX_HOOKS_BYTES + 1
    if extension_size > MAX_HOOKS_BYTES:
        return HookInspection(
            diagnostics=[
                _diagnostic(
                    "hooks-size-limit",
                    f"Hooks extension exceeds {MAX_HOOKS_BYTES} bytes.",
                )
            ]
        )

    diagnostics: list[PluginDiagnostic] = []
    if set(extension) != {"version", "hooks"}:
        diagnostics.append(
            _diagnostic(
                "hooks-extension-fields-invalid",
                "The hooks extension must contain only version and hooks.",
            )
        )
        return HookInspection(diagnostics=diagnostics)
    version = extension.get("version")
    if type(version) is not int or version != 1:
        return HookInspection(
            diagnostics=[
                _diagnostic(
                    "hooks-version-unsupported",
                    "Unsupported EvoFlux hooks extension version.",
                )
            ]
        )

    raw_hooks = extension.get("hooks")
    if not isinstance(raw_hooks, list):
        return HookInspection(
            diagnostics=[
                _diagnostic(
                    "hooks-list-invalid", "Hooks extension hooks must be an array."
                )
            ]
        )
    if len(raw_hooks) > MAX_HOOKS:
        diagnostics.append(
            _diagnostic(
                "hooks-count-limit", f"Hooks extension exceeds {MAX_HOOKS} hooks."
            )
        )
        raw_hooks = raw_hooks[:MAX_HOOKS]

    root = Path(plugin_root).resolve(strict=True)
    components: list[PluginHookComponent] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_hooks):
        entry_diagnostics: list[PluginDiagnostic] = []
        definition: HookDefinition | None = None
        command_path = ""
        digest: str | None = None
        try:
            if not isinstance(raw, dict):
                raise ValueError("hook definition must be an object")
            definition = HookDefinition.model_validate(raw)
            if definition.hook_id in seen_ids:
                raise ValueError("hook IDs must be unique within a package")
            seen_ids.add(definition.hook_id)
            _, command_path = _resolve_executable(root, definition.command)
            digest = hook_digest(root, definition)
        except (ValidationError, ValueError, OSError) as exc:
            message = "Hook declaration is invalid."
            if isinstance(exc, ValueError) and str(exc):
                message = str(exc)
            entry_diagnostics.append(
                _diagnostic(
                    "hook-definition-invalid",
                    f"Hook #{index + 1}: {message}",
                )
            )
        if definition is None:
            # Invalid declarations cannot become registrations or executable hooks.
            diagnostics.extend(entry_diagnostics)
            continue
        components.append(
            PluginHookComponent(
                definition=definition,
                command_path=command_path,
                digest=digest,
                valid=not entry_diagnostics,
                diagnostics=entry_diagnostics,
            )
        )
    return HookInspection(hooks=components, diagnostics=diagnostics)


__all__ = [
    "MAX_HOOKS",
    "MAX_HOOKS_BYTES",
    "MAX_HOOK_EXECUTABLE_BYTES",
    "hook_digest",
    "inspect_plugin_hooks",
]
