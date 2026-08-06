"""Hierarchical workspace instruction loading and mutation preflight."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.services.turn_changes import _parse_patch_ops

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage, ToolCall
    from app.agent.state import (
        AgentState,
        ModelCallHandler,
        ModelRequest,
        RunContext,
        ToolCallHandler,
    )


MAX_AGENTS_MD_BYTES = 128 * 1024
_MUTATING_TOOLS = frozenset({"edit", "write", "patch", "rm", "shell", "python", "bg"})
_PATH_KEYS = ("path", "file_path", "directory", "workdir", "target")


class WorkspaceInstructionsHook(BaseAgentHook):
    """Load root→target instruction chains with override precedence.

    Root instructions are present on every model call. When the model first
    targets a nested directory, read-only calls return the newly applicable
    rules with their result; mutating calls are preflight-blocked once so the
    model must observe those rules before retrying the mutation.
    """

    def __init__(
        self,
        workspace: str | None,
        extra_workspace_paths: list[str] | None = None,
    ) -> None:
        self._roots = [
            Path(path).resolve()
            for path in [workspace, *(extra_workspace_paths or [])]
            if path
        ]

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        repository_map = self._repository_map()
        sections = self._root_sections()
        loaded = (
            state.metadata.get("_loaded_workspace_instruction_files") or []
            if state is not None
            else []
        )
        sections.extend(self._read_instruction_file(Path(path)) for path in loaded)
        instruction_block = _render_sections(sections)
        block = "\n\n".join(
            part for part in (repository_map, instruction_block) if part
        )
        if not block:
            return await handler(request)
        prompt = (
            f"{request.system_prompt}\n\n{block}" if request.system_prompt else block
        )
        return await handler(request.override(system_prompt=prompt))

    def _repository_map(self) -> str:
        """Render repository locations without re-reading their instructions."""

        roots = list(dict.fromkeys(self._roots))
        if len(roots) < 2:
            return ""
        lines = [
            "## Available Repositories",
            "",
            "Use the repository path that owns the target code. The first "
            "repository is the primary workspace.",
            "",
        ]
        for index, root in enumerate(roots):
            marker = " **(primary)**" if index == 0 else ""
            lines.append(f"- **{root.name}**: `{root}`{marker}")
        return "\n".join(lines)

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler: "ToolCallHandler",
    ) -> str:
        targets = self._tool_targets(tool_call)
        new_files: list[Path] = []
        loaded = set(state.metadata.get("_loaded_workspace_instruction_files") or [])
        for target in targets:
            for instruction_file in self._instruction_chain(target):
                key = str(instruction_file)
                if instruction_file.parent in self._active_roots() or key in loaded:
                    continue
                loaded.add(key)
                new_files.append(instruction_file)

        if new_files:
            state.metadata["_loaded_workspace_instruction_files"] = sorted(loaded)
            block = _render_sections(
                self._read_instruction_file(path) for path in new_files
            )
            if tool_call.function.name in _MUTATING_TOOLS:
                return (
                    "[Instruction preflight — call not executed]\n"
                    "Nested workspace rules became applicable to this target. "
                    "Review them and reissue the call only if it complies.\n\n" + block
                )
            result = await handler(ctx, state, tool_call)
            return f"{result}\n\n[New nested workspace instructions]\n{block}"
        return await handler(ctx, state, tool_call)

    def _active_roots(self) -> list[Path]:
        roots = list(self._roots)
        try:
            from app.agent.sandbox import get_sandbox

            current = get_sandbox().workspace_root.resolve()
            if current not in roots:
                roots.append(current)
        except Exception:  # noqa: BLE001
            pass
        return roots

    def _root_sections(self) -> list[tuple[Path, str]]:
        sections: list[tuple[Path, str]] = []
        for root in self._active_roots():
            instruction = _instruction_at(root)
            if instruction:
                sections.append(self._read_instruction_file(instruction))
        return sections

    def _instruction_chain(self, target: Path) -> list[Path]:
        resolved = target.resolve()
        for root in self._active_roots():
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            current = root
            files: list[Path] = []
            directories = relative.parts[:-1] if relative.parts else ()
            for part in directories:
                current /= part
                instruction = _instruction_at(current)
                if instruction:
                    files.append(instruction)
            return files
        return []

    def _tool_targets(self, tool_call: "ToolCall") -> list[Path]:
        try:
            args: dict[str, Any] = json.loads(tool_call.function.arguments or "{}")
        except (TypeError, ValueError):
            return []
        raw_paths: list[str] = []
        for key in _PATH_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                raw_paths.append(value)
        patch_text = args.get("patch_text")
        if isinstance(patch_text, str):
            raw_paths.extend(
                path for path, _status, _add, _delete in _parse_patch_ops(patch_text)
            )
        roots = self._active_roots()
        default_root = roots[0] if roots else Path.cwd()
        return [
            Path(raw) if Path(raw).is_absolute() else default_root / raw
            for raw in raw_paths
        ]

    @staticmethod
    def _read_instruction_file(path: Path) -> tuple[Path, str]:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning(
                "workspace_instruction_read_failed path={} error={}", path, exc
            )
            return path, ""
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_AGENTS_MD_BYTES:
            logger.warning(
                "workspace_instruction_truncated path={} limit={}",
                path,
                MAX_AGENTS_MD_BYTES,
            )
            content = encoded[:MAX_AGENTS_MD_BYTES].decode("utf-8", errors="ignore")
            content += (
                "\n\n[AGENTS.md truncated — file exceeds the injected-size limit]"
            )
        return path, content.strip()

    def _read_agents_md(self) -> str:
        """Backward-compatible root reader used by older callers/tests."""
        return "\n\n".join(
            content for _path, content in self._root_sections() if content
        )


def _instruction_at(directory: Path) -> Path | None:
    override = directory / "AGENTS.override.md"
    if override.is_file():
        return override
    standard = directory / "AGENTS.md"
    return standard if standard.is_file() else None


def _render_sections(sections) -> str:
    rendered = [f"### `{path}`\n\n{content}" for path, content in sections if content]
    if not rendered:
        return ""
    return "## Workspace Instructions\n\n" + "\n\n".join(rendered)
