"""Load only a skill explicitly selected by the user.

There is deliberately no keyword, intent, or prose classification here. A
normal request remains untouched and the model can call the ordinary ``skill``
tool. The composer directive is deterministic user input, so it is safe to
materialise as the equivalent tool exchange.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext


_DIRECTIVE_RE = re.compile(
    r"^/skill:"
    r"([a-zA-Z0-9][a-zA-Z0-9._-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?)"
    r"(?=\s|$)"
)


class ExplicitSkillSelectionHook(BaseAgentHook):
    """Materialise a composer-selected ``/skill:<name>`` directive."""

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        user_index, user_text = self._latest_user_message(state)
        if user_index is None or not user_text:
            return
        selector = self._selector(user_text)
        if selector is None:
            return

        from app.agent.tools.builtin.skill import discover_skills

        discovered = discover_skills()
        skill_name = self._resolve_name(selector, discovered)
        if skill_name is None:
            logger.warning(
                "skill_explicit_not_found agent={} selector={}",
                ctx.agent_name,
                selector,
            )
            return
        if skill_name in self._loaded_skills(state):
            return
        if self._inject(state, skill_name, discovered, insert_at=user_index + 1):
            logger.info(
                "skill_explicit_selected agent={} skill={}",
                ctx.agent_name,
                skill_name,
            )

    @staticmethod
    def _latest_user_message(state: "AgentState") -> tuple[int | None, str | None]:
        for index in range(len(state.messages) - 1, -1, -1):
            message = state.messages[index]
            if isinstance(message, HumanMessage):
                return index, message.text_content()
        return None, None

    @staticmethod
    def _selector(message: str) -> str | None:
        # Composer quote context precedes the directive. Only the first real
        # user-content line can select a skill.
        for line in message.splitlines():
            if not line or line == ">" or line.startswith("> "):
                continue
            match = _DIRECTIVE_RE.match(line)
            return match.group(1) if match else None
        return None

    @staticmethod
    def _resolve_name(selector: str, discovered: dict[str, dict]) -> str | None:
        if selector in discovered:
            return selector
        nested = selector.replace(":", "/", 1)
        return nested if nested in discovered else None

    @staticmethod
    def _loaded_skills(state: "AgentState") -> set[str]:
        loaded = set(state.metadata.get("loaded_skills", {}).keys())
        for message in state.messages:
            if not isinstance(message, AssistantMessage):
                continue
            for call in message.tool_calls or []:
                if call.function.name != "skill":
                    continue
                try:
                    name = json.loads(call.function.arguments).get("skill_name")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    continue
                if isinstance(name, str) and name:
                    loaded.add(name)
        return loaded

    @staticmethod
    def _inject(
        state: "AgentState",
        skill_name: str,
        discovered: dict[str, dict],
        *,
        insert_at: int,
    ) -> bool:
        from app.agent.tools.builtin.skill import _parse_frontmatter, _render_tokens

        info = discovered.get(skill_name)
        if info is None:
            return False
        skill_dir = Path(info["dir"])
        skill_file = skill_dir / "SKILL.md"
        try:
            text = skill_file.read_text(encoding="utf-8")
        except OSError:
            return False
        _, body = _parse_frontmatter(text)
        rendered = _render_tokens(body, skill_dir=skill_dir)
        call_id = f"explicit_{uuid.uuid4().hex[:12]}"
        state.messages[insert_at:insert_at] = [
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=call_id,
                        function=FunctionCall(
                            name="skill",
                            arguments=json.dumps({"skill_name": skill_name}),
                        ),
                    )
                ],
            ),
            ToolMessage(
                tool_call_id=call_id,
                name="skill",
                content=rendered,
            ),
        ]
        state.metadata.setdefault("loaded_skills", {})[skill_name] = rendered
        return True
