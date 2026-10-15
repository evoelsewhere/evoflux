"""Inject the user's default response style into the system prompt.

Feature A of the Intelligent UI plan — the ``Simple`` / ``Visual`` choice
made in **Settings → Agents** is appended to the base prompt once per model
call, next to the built-in ``inject_current_date`` hook.

When the renderer is available, the Visual line names the concrete tool and
gives the model a compact selection guide. Keeping this capability check at
request time avoids telling an agent to call a tool that its tier cannot use.
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
    "Response style: visual. First understand what the user is trying to "
    "accomplish, then choose the clearest useful response: prose, structured "
    "markdown, or an interactive UI. Consider UI when the answer helps the "
    "user explore parts or alternatives, change inputs and see results, track "
    "progress, or take an in-chat action. Judge the likely answer and user "
    "workflow, not words that happen to appear in the prompt. Prefer the "
    "smallest UI that makes the task easier; explain it in concise prose and "
    "make controls, labels, outcomes, and assumptions clear. Use prose when "
    "the answer is a simple fact, explanation, or conversation and controls "
    "add no practical value."
)
_VISUAL_UI_LINE = (
    f"{_VISUAL_LINE} The ui_block tool is available for native interactive "
    "content in this chat. Before using it, check that a control changes "
    "what the user can understand, decide, calculate, track, or do; do not "
    "add UI for decoration or because the prompt contains a matching term. "
    "Choose the block from the job: compare options in a table, explore a "
    "changing value with a calculator, track a plan with steps/checklist, or "
    "let the user inspect a system with a focused custom interaction. Pair "
    "the UI with a concise explanation, useful labels, and any needed "
    "assumptions. Inspect the tool schema and render in chat, never as a "
    "widget file."
)


def response_style_directive(style: str, tool_names: set[str]) -> str:
    """Build concise task-utility guidance using only this run's tools."""
    if style == "simple":
        return _SIMPLE_LINE
    available = [name for name in ("ui_block", "visual_artifact") if name in tool_names]
    line = _VISUAL_LINE
    motion_progress_line = (
        " For a genuinely multi-stage motion explainer, use motion_progress at "
        "storyboard, sample review/revision, and final-render milestones so the "
        "chat can show truthful lifecycle state; do not emit one update per frame. "
        "The renderer owns exact frame counts and verified soundtrack status."
        if "motion_progress" in tool_names
        else ""
    )
    if not available:
        return line + motion_progress_line
    if "ui_block" in available and "visual_artifact" not in available:
        return _VISUAL_UI_LINE + motion_progress_line
    if "visual_artifact" in available and "ui_block" in available:
        return (
            f"{line} The ui_block and visual_artifact tools are available in this run. "
            "Use ui_block for compact declarative controls and visual_artifact only "
            "when a custom dashboard, motion explainer, or spatial 3D view materially "
            "improves the task. For dashboards, inspect data first and cite successful "
            "tool calls; do not claim live freshness without source evidence."
            f"{motion_progress_line}"
        )
    return (
        f"{line} The visual_artifact tool is available in this run for custom "
        "dashboards, motion explainers, or spatial 3D views when those controls "
        "materially improve the task. For dashboards, inspect data first and cite "
        "successful tool calls; do not claim live freshness without source evidence."
        f"{motion_progress_line}"
    )


@dynamic_prompt
def inject_response_style(request: PromptRequest) -> str:
    """Append the configured response-style directive to the base prompt.

    Reads ``settings.yaml`` on every model call so a change made in
    **Settings → Agents** applies to the next message without a restart,
    and degrades to ``visual`` if the settings file is corrupt.
    """
    line = response_style_directive(
        response_style_default(), set(request.state.tool_names)
    )
    return f"{request.base_prompt}\n\n{line}"
