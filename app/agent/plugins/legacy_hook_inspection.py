"""Non-executing inventory of trusted legacy Python hook subscriptions.

Legacy hooks are arbitrary trusted code. Replacement preview must never import
them merely to discover their callbacks, so this module recognizes only
literal functional declarations and direct ``BaseAgentHook`` overrides. When
the source is dynamic it reports a conservative possible match instead.
"""

from __future__ import annotations

import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Literal

from app.agent.plugins.hook_contract import HookEvent

_EVENTS_BY_METHOD: dict[str, tuple[HookEvent, ...]] = {
    "before_agent": (HookEvent.AGENT_START,),
    "after_agent": (HookEvent.AGENT_STOP,),
    "before_model": (HookEvent.MODEL_BEFORE,),
    "after_model": (HookEvent.MODEL_AFTER,),
    "before_completion": (HookEvent.COMPLETION_BEFORE,),
    "wrap_model_call": (HookEvent.MODEL_BEFORE, HookEvent.MODEL_AFTER),
    "wrap_tool_call": (HookEvent.TOOL_BEFORE, HookEvent.TOOL_AFTER),
}

_FUNCTIONAL_EVENTS = {
    "tool.before": HookEvent.TOOL_BEFORE,
    "tool.after": HookEvent.TOOL_AFTER,
    "agent.start": HookEvent.AGENT_START,
    "agent.stop": HookEvent.AGENT_STOP,
    "model.before": HookEvent.MODEL_BEFORE,
    "model.after": HookEvent.MODEL_AFTER,
    "completion.stop": HookEvent.COMPLETION_BEFORE,
    "compact.before": HookEvent.COMPACT_BEFORE,
    "compact.after": HookEvent.COMPACT_AFTER,
    "subagent.start": HookEvent.SUBAGENT_START,
    "subagent.stop": HookEvent.SUBAGENT_STOP,
}


def _literal_functional_events(tree: ast.Module) -> set[HookEvent] | None:
    factory = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "plugin"
        ),
        None,
    )
    if factory is None:
        return None
    returns = [node for node in ast.walk(factory) if isinstance(node, ast.Return)]
    if not returns or any(not isinstance(node.value, ast.Dict) for node in returns):
        return None
    events: set[HookEvent] = set()
    for return_node in returns:
        value = return_node.value
        assert isinstance(value, ast.Dict)
        for key in value.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                return None
            event = _FUNCTIONAL_EVENTS.get(key.value)
            if event is not None:
                events.add(event)
    return events


def _class_events(tree: ast.Module) -> set[HookEvent] | None:
    plugin_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Plugin"
        ),
        None,
    )
    if plugin_class is None:
        return None
    is_hook_subclass = any(
        (isinstance(base, ast.Name) and base.id == "BaseAgentHook")
        or (isinstance(base, ast.Attribute) and base.attr == "BaseAgentHook")
        for base in plugin_class.bases
    )
    if not is_hook_subclass:
        return None
    return {
        event
        for node in plugin_class.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        for event in _EVENTS_BY_METHOD.get(node.name, ())
    }


def _trusted_digest(path: Path, content: bytes) -> bool:
    try:
        trust_path = path.parent / ".trusted-hooks.json"
        trust_stat = trust_path.stat()
        if not stat.S_ISREG(trust_stat.st_mode) or trust_stat.st_size > 1024 * 1024:
            return False
        trust_doc = json.loads(trust_path.read_text(encoding="utf-8"))
        return (
            isinstance(trust_doc, dict)
            and trust_doc.get(path.name) == hashlib.sha256(content).hexdigest()
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def inspect_legacy_hook_subscriptions(
    directories: tuple[Path, ...] | list[Path],
    events: tuple[HookEvent, ...] | list[HookEvent],
) -> list[dict[str, str | HookEvent]]:
    """List trusted legacy callbacks that a replace policy may suppress.

    This only reads bounded source and trust metadata. Dynamic declarations are
    conservatively represented for every selected event with ``certainty`` set
    to ``possible``; no extension code is imported or executed.
    """

    selected = set(events)
    if not selected:
        return []
    seen: set[Path] = set()
    result: list[dict[str, str | HookEvent]] = []
    for directory in directories:
        try:
            if not directory.is_dir():
                continue
            candidates = sorted(directory.glob("*.py"))
        except OSError:
            continue
        for path in candidates:
            if path.name.startswith("_"):
                continue
            try:
                resolved = path.resolve(strict=True)
                if resolved in seen:
                    continue
                seen.add(resolved)
                file_stat = path.stat()
                if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_size > 1024 * 1024
                ):
                    continue
                content = path.read_bytes()
                if not _trusted_digest(path, content):
                    continue
                tree = ast.parse(content.decode("utf-8"), filename=path.name)
            except (OSError, UnicodeError, SyntaxError, ValueError):
                continue

            factory = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "plugin"
                ),
                None,
            )
            plugin_class = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "Plugin"
                ),
                None,
            )
            if factory is None and plugin_class is None:
                continue

            declared = _literal_functional_events(tree) if factory else None
            if declared is None and factory is None:
                declared = _class_events(tree)
            certainty: Literal["exact", "possible"] = "exact"
            if declared is None:
                # The file is trusted and discoverable, but static analysis
                # cannot establish which event keys its factory returns.
                declared = selected
                certainty = "possible"
            elif factory is not None and factory.decorator_list:
                # A decorator can replace the factory or alter its returned
                # mapping, so literal source alone is not an exact contract.
                certainty = "possible"
            elif plugin_class is not None and (
                plugin_class.decorator_list
                or any(
                    isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and node.name in _EVENTS_BY_METHOD
                    and node.decorator_list
                    for node in plugin_class.body
                )
            ):
                certainty = "possible"
            elif factory is not None and any(
                isinstance(node, ast.Constant) and node.value == "applies_to"
                for node in ast.walk(factory)
            ):
                certainty = "possible"
            elif (
                factory is not None
                and len(
                    [node for node in ast.walk(factory) if isinstance(node, ast.Return)]
                )
                > 1
            ):
                certainty = "possible"
            elif plugin_class is not None and any(
                isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                and node.name == "applies_to"
                for node in plugin_class.body
            ):
                certainty = "possible"
            for event in sorted(declared & selected, key=lambda item: item.value):
                result.append(
                    {
                        "event": event,
                        "plugin_id": "local-python",
                        "hook_id": path.stem,
                        "installation_id": hashlib.sha256(
                            str(resolved.parent).encode("utf-8")
                        ).hexdigest()[:16],
                        "source": "legacy_python",
                        "display_name": path.name,
                        "certainty": certainty,
                    }
                )
    return result


__all__ = ["inspect_legacy_hook_subscriptions"]
