"""Inject the user's default response style into the system prompt.

Feature A of the Intelligent UI plan — the ``Simple`` / ``Visual`` choice
made in **Settings → Agents** is appended to the base prompt once per model
call, next to the built-in ``inject_current_date`` hook.

The visual line is deliberately tool-agnostic (app/agent/AGENTS.md): it
must NOT name ``ui_block``, so it steers by *structure* not by tool. It no
longer enumerates "tables" as a markdown affordance — that phrasing
competed with the interactive layer and made small models settle for a
static table whenever the data would have gained from a real widget.
"""

from __future__ import annotations

from app.agent.hooks.dynamic_prompt import PromptRequest, dynamic_prompt
from app.core.runtime_settings import response_style_default

_SIMPLE_LINE = (
    "Response style: simple. Default to plain prose paragraphs. "
    "Skip markdown headings, tables, bullet lists and emojis unless "
    "the user explicitly asks for them. "
    "Do not use interactive UI blocks either; plain prose only."
)
_VISUAL_LINE = (
    "Response style: visual. Structure answers with markdown when they "
    "gain from it — headings, lists and code blocks. When data or a "
    "comparison of options would be easier to use as an interactive "
    "widget than as flat text — including opinion answers that weigh "
    "contenders or a recommendation that could be revisited — prefer the "
    "interactive form. Keep plain prose for conversation and one-line "
    "explanations."
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
