"""Canonical skill activation and safe resource reading."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from html import escape
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from app.agent.schemas.chat import AssistantMessage, FunctionCall, ToolCall, ToolMessage

from app.agent.sandbox import get_sandbox
from app.agent.skills.discovery import (
    MAX_SKILL_FILE_BYTES,
    list_skill_resources,
    parse_frontmatter,
)
from app.agent.skills.models import SkillRecord

if TYPE_CHECKING:
    from app.agent.state import AgentState


MAX_RESOURCE_BYTES = 256 * 1024
MAX_ACTIVATED_SKILL_BYTES = 95_000
_ACTIVATION_SOURCE_RE = re.compile(r"[^a-z0-9_]+")


def inject_skill_activation(
    state: AgentState,
    *,
    skill_name: str,
    content: str,
    source: str,
    insert_at: int | None = None,
) -> None:
    """Insert one canonical, durable skill tool-call/result pair."""

    prefix = _ACTIVATION_SOURCE_RE.sub("_", source.casefold()).strip("_") or "skill"
    call_id = f"{prefix}_{uuid.uuid4().hex[:12]}"
    pair = [
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id=call_id,
                    function=FunctionCall(
                        name="skill",
                        arguments=json.dumps(
                            {"action": "load", "skill_name": skill_name}
                        ),
                    ),
                )
            ],
        ),
        ToolMessage(tool_call_id=call_id, name="skill", content=content),
    ]
    index = len(state.messages) if insert_at is None else insert_at
    state.messages[index:index] = pair
    state.metadata.setdefault("loaded_skills", {})[skill_name] = content


def _read_bounded_utf8(path: Path, *, limit: int, label: str) -> str:
    """Read at most *limit* bytes so a post-discovery mutation stays bounded."""

    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"{label} exceeds the {limit}-byte runtime limit.")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8 text.") from exc


def render_path_tokens(text: str, *, skill_dir: Path | None = None) -> str:
    """Expand the small, explicit set of EvoFlux path placeholders."""

    if not text:
        return text
    from app.core.config import settings

    tokens = {
        "EVOFLUX_CONFIG_DIR": settings.EVOFLUX_CONFIG_DIR,
        "AGENTS_DIR": settings.AGENTS_DIR,
        "SKILLS_DIR": settings.SKILLS_DIR,
    }
    if skill_dir is not None:
        tokens["SKILL_DIR"] = str(skill_dir.resolve())
    for name, value in tokens.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _grant_skill_read_access(skill_dir: Path) -> None:
    """Mount an activated external bundle as a read-only sandbox root."""

    try:
        sandbox = get_sandbox()
    except Exception:
        return
    resolved = skill_dir.resolve()
    allowed = [*sandbox.allowed_workspace_roots, *sandbox.read_only_paths]
    if any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        return
    sandbox.read_only_paths.append(resolved)


def is_skill_activation_content(content: object, skill_name: str) -> bool:
    """Return whether *content* is the canonical complete activation wrapper."""

    if not isinstance(content, str):
        return False
    prefix = f'<skill_content name="{escape(skill_name)}"'
    if not content.startswith(prefix):
        return False
    suffix = content[len(prefix) :]
    return suffix.startswith((">", " ")) and content.rstrip().endswith(
        "</skill_content>"
    )


async def activate_skill(record: SkillRecord) -> str:
    """Read and wrap one skill body with its identity and resource manifest."""

    text, rendered = await _read_skill_instructions(record)
    revision = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    resources = await asyncio.to_thread(list_skill_resources, record.skill_dir)
    _grant_skill_read_access(record.skill_dir)

    resource_lines = [f"- {item['path']} ({item['size']} bytes)" for item in resources]
    if record.resource_count > len(resources):
        resource_lines.append(
            f"- … {record.resource_count - len(resources)} more resources omitted from the manifest"
        )
    manifest = "\n".join(resource_lines) if resource_lines else "- (none)"
    output = (
        f'<skill_content name="{escape(record.name)}" revision="{revision}">\n'
        f"Skill directory: {record.skill_dir.resolve()}\n"
        "Resolve every relative path in the instructions against that directory. "
        'Use skill(action="read_resource") for text resources that ordinary '
        "file tools cannot access.\n\n"
        "<instructions>\n"
        f"{rendered}\n"
        "</instructions>\n\n"
        "<skill_resources>\n"
        f"{manifest}\n"
        "</skill_resources>\n"
        "</skill_content>"
    )
    if len(output.encode("utf-8")) > MAX_ACTIVATED_SKILL_BYTES:
        raise ValueError(
            "Activated skill exceeds the 95,000-byte model-context limit; "
            "move conditional detail into bundle resources."
        )
    return output


async def _read_skill_instructions(record: SkillRecord) -> tuple[str, str]:
    """Return bounded source and rendered instructions for one valid record."""

    text = await asyncio.to_thread(
        _read_bounded_utf8,
        record.skill_file,
        limit=MAX_SKILL_FILE_BYTES,
        label="SKILL.md",
    )
    try:
        _, body = parse_frontmatter(text)
    except RecursionError as exc:
        raise ValueError("SKILL.md frontmatter is nested too deeply.") from exc
    rendered = render_path_tokens(body, skill_dir=record.skill_dir)
    if len(rendered.encode("utf-8")) > MAX_ACTIVATED_SKILL_BYTES:
        raise ValueError(
            "Skill instructions exceed the 95,000-byte model-context limit; "
            "move conditional detail into bundle resources."
        )
    return text, rendered


async def read_skill_instructions(record: SkillRecord) -> str:
    """Read one bounded body for compatibility callers outside tool execution."""

    _text, rendered = await _read_skill_instructions(record)
    _grant_skill_read_access(record.skill_dir)
    return rendered


def resolve_resource_path(record: SkillRecord, resource_path: str) -> Path:
    """Resolve one manifest path and reject traversal or symlink escapes."""

    if not resource_path or "\\" in resource_path or "\x00" in resource_path:
        raise ValueError("resource_path must be a non-empty POSIX relative path.")
    relative = PurePosixPath(resource_path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("resource_path must stay inside the selected skill bundle.")
    if relative.as_posix() in {"SKILL.md", ".evoflux.json"}:
        raise ValueError(
            "Use action='load' for SKILL.md; internal scope metadata is not a resource."
        )

    candidate = record.skill_dir.joinpath(*relative.parts)
    current = record.skill_dir
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(
                "Symlinked skill resources are not readable through this tool."
            )
    resolved_root = record.skill_dir.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("resource_path escapes the selected skill bundle.")
    if not resolved.is_file():
        raise FileNotFoundError(f"Skill resource '{resource_path}' was not found.")
    return resolved


async def read_skill_resource(record: SkillRecord, resource_path: str) -> str:
    """Read one bounded UTF-8 resource after canonical path validation."""

    path = resolve_resource_path(record, resource_path)
    try:
        content = await asyncio.to_thread(
            _read_bounded_utf8,
            path,
            limit=MAX_RESOURCE_BYTES,
            label="Skill resource",
        )
    except ValueError as exc:
        if "not valid UTF-8" not in str(exc):
            raise
        raise ValueError(
            "Binary resources cannot be inlined. Use an appropriate file or artifact tool."
        ) from exc
    _grant_skill_read_access(record.skill_dir)
    return (
        f'<skill_resource skill="{escape(record.name)}" '
        f'path="{escape(resource_path)}">\n{content}\n</skill_resource>'
    )


__all__ = [
    "MAX_ACTIVATED_SKILL_BYTES",
    "MAX_RESOURCE_BYTES",
    "activate_skill",
    "inject_skill_activation",
    "is_skill_activation_content",
    "read_skill_instructions",
    "read_skill_resource",
    "render_path_tokens",
    "resolve_resource_path",
]
