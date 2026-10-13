"""Inject the user's default response style into the system prompt.

Feature A of the Intelligent UI plan — the ``Simple`` / ``Visual`` choice
made in **Settings → Agents** is appended to the base prompt once per model
call, next to the built-in ``inject_current_date`` hook.
"""

from __future__ import annotations

from app.agent.hooks.dynamic_prompt import PromptRequest, dynamic_prompt
from app.core.runtime_settings import response_style_default

_SIMPLE_LINE = (
    "Response style: simple. Default to plain prose paragraphs. "
    "Skip markdown headings, tables, bullet lists and emojis unless "
    "the user explicitly asks for them."
)
_VISUAL_LINE = (
    "Response style: visual. You may use markdown headings, lists, "
    "tables and code blocks to make answers scannable when they "
    "gain from structure."
)


@dynamic_prompt
def inject_response_style(request: PromptRequest) -> str:
    """Append the configured response-style directive to the base prompt.

    Reads ``settings.yaml`` on every model call so a change made in
    **Settings → Agents** applies to the next message without a restart,
    and degrades to ``visual`` if the settings file is corrupt.
    """
    line = _SIMPLE_LINE if response_style_default() == "simple" else _VISUAL_LINE
    return f"{request.base_prompt}\n\n{line}"
