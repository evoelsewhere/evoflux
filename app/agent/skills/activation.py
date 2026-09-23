"""Recognising and producing Skill activations.

An activation is a successful, complete ``read`` of a Skill's ``SKILL.md``.
The model produces one by calling ``read`` on a catalog ``location``; the
harness produces the same pair for a ``$name`` mention by running the real
``read`` tool, so both paths leave identical history.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from app.agent.schemas.chat import AssistantMessage, FunctionCall, ToolCall, ToolMessage
from app.agent.state import PendingToolLifecycle

if TYPE_CHECKING:
    from app.agent.skills.models import Skill
    from app.agent.skills.registry import SkillCatalog
    from app.agent.state import AgentState


SKILL_FILE_NAME = "SKILL.md"
READ_TOOL = "read"


def full_read_path(call: ToolCall) -> str | None:
    """Return the path of a ``read`` call that reads a whole file from line 1."""

    if call.function.name != READ_TOOL:
        return None
    try:
        arguments = json.loads(call.function.arguments or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(arguments, dict):
        return None
    path = arguments.get("path")
    offset = arguments.get("offset", 1)
    if not isinstance(path, str) or not path or arguments.get("limit") is not None:
        return None
    if offset not in (None, 1):
        return None
    return path


def is_successful_result(message: ToolMessage | None) -> bool:
    content = getattr(message, "content", None)
    return (
        isinstance(content, str) and bool(content) and not content.startswith("Error:")
    )


def is_skill_file_read(call: ToolCall, result: ToolMessage | None) -> bool:
    """Whether *call* fully and successfully read a file named ``SKILL.md``."""

    path = full_read_path(call)
    return (
        path is not None
        and os.path.basename(path.replace("\\", "/")) == SKILL_FILE_NAME
        and is_successful_result(result)
    )


def activated_skills(
    messages: Iterable[object], catalog: SkillCatalog
) -> dict[str, Skill]:
    """Return the catalog Skills whose ``SKILL.md`` was read in *messages*."""

    message_list = list(messages)
    results = {
        message.tool_call_id: message
        for message in message_list
        if isinstance(message, ToolMessage)
    }
    activated: dict[str, Skill] = {}
    for message in message_list:
        if not isinstance(message, AssistantMessage) or not message.tool_calls:
            continue
        for call in message.tool_calls:
            if not is_skill_file_read(call, results.get(call.id)):
                continue
            path = full_read_path(call)
            skill = catalog.for_location(path) if path else None
            if skill is not None:
                activated[skill.name] = skill
    return activated


async def insert_skill_read(state: AgentState, skill: Skill, *, insert_at: int) -> bool:
    """Insert a harness-run ``read`` of *skill*'s ``SKILL.md`` into history."""

    from app.agent.tools.builtin.filesystem.read import _read_file

    path = skill.location.as_posix()
    arguments = json.dumps({"path": path})
    try:
        content = await _read_file(path=path, _state=state)
    except (OSError, ValueError, PermissionError):
        return False
    if not isinstance(content, str):
        return False
    call_id = f"skill_{uuid.uuid4().hex[:12]}"
    state.messages[insert_at:insert_at] = [
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id=call_id,
                    function=FunctionCall(name=READ_TOOL, arguments=arguments),
                )
            ],
        ),
        ToolMessage(tool_call_id=call_id, name=READ_TOOL, content=content),
    ]
    state.pending_tool_lifecycles.append(
        PendingToolLifecycle(
            tool_call_id=call_id,
            name=READ_TOOL,
            arguments=arguments,
            result=content,
            metadata={"duration_ms": 0.0, "synthetic": True, "skill": skill.name},
        )
    )
    return True


def plugin_root(skill: Skill) -> Path | None:
    """The plugin package root for a plugin-contributed Skill."""

    if skill.source != "plugin":
        return None
    return skill.root.parent


__all__ = [
    "READ_TOOL",
    "SKILL_FILE_NAME",
    "activated_skills",
    "full_read_path",
    "insert_skill_read",
    "is_skill_file_read",
    "is_successful_result",
    "plugin_root",
]
