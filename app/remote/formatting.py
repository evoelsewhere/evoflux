from __future__ import annotations

import html
from collections.abc import Mapping, Sequence

from app.remote.contracts import RemoteButton

__all__ = [
    "escape",
    "format_elapsed",
    "render_status_card",
    "render_done_card",
    "render_error_card",
    "render_gate_card",
    "render_settings_card",
    "render_project_picker",
    "render_prompt_suggestions",
]

_STATUS_ICON = {"accepted": "\U0001f527", "queued": "⏳", "pending": "⏳"}


def escape(value: str) -> str:
    """The only place raw text becomes safe to place inside an HTML tag."""
    return html.escape(value, quote=False)


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


def render_status_card(*, title: str, status: str) -> tuple[str, tuple[RemoteButton, ...]]:
    icon = _STATUS_ICON.get(status, "\U0001f527")
    text = f"{icon} <b>{escape(title)}</b>\n<i>{escape(status)}</i>"
    return text, ()


def render_done_card(
    *,
    title: str,
    elapsed_seconds: float,
    summary_lines: Sequence[str],
    tool_call_count: int,
    diff_token: str | None,
    toollog_token: str | None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    header = f"✅ <b>{escape(title)}</b> · {format_elapsed(elapsed_seconds)}"
    lines = [escape(line) for line in summary_lines]
    parts = [header]
    if lines:
        parts.append("\n".join(lines))
    parts.append(f"<b>{tool_call_count} tool calls</b>")
    text = "\n\n".join(parts)
    buttons: list[RemoteButton] = []
    if diff_token:
        buttons.append(RemoteButton(text="\U0001f4c4 Full diff", token=diff_token))
    if toollog_token:
        buttons.append(RemoteButton(text="\U0001f9fe Tool log", token=toollog_token))
    return text, tuple(buttons)


def render_error_card(
    *, title: str, message: str, toollog_token: str | None
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = f"❌ <b>{escape(title)}</b>\n\n<b>Error:</b> {escape(message)}"
    buttons = (
        (RemoteButton(text="\U0001f9fe Tool log", token=toollog_token),)
        if toollog_token
        else ()
    )
    return text, buttons


def render_gate_card(
    *, title: str, body: str, actions: Sequence[tuple[str, str]]
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = f"\U0001f510 <b>{escape(title)}</b>\n{escape(body)}"
    buttons = tuple(RemoteButton(text=label, token=token) for token, label in actions)
    return text, buttons


def render_settings_card(
    *,
    connection_label: str,
    model: str,
    permission_mode: str,
    redaction_policy: str,
    notify_scope: str,
    redaction_tokens: Mapping[str, str],
    notify_scope_tokens: Mapping[str, str],
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = (
        "<b>⚙️ Settings</b>\n\n"
        f"<b>Connection</b>\n{escape(connection_label)}\n\n"
        f"<b>Model</b>\n<code>{escape(model)}</code> <i>(desktop only)</i>\n\n"
        f"<b>Permission mode</b>\n<code>{escape(permission_mode)}</code> <i>(desktop only)</i>\n\n"
        f"<b>Notifications</b>\n<code>{escape(notify_scope)}</code>\n\n"
        f"<b>Outbound redaction</b>\n<code>{escape(redaction_policy)}</code>"
    )
    buttons = [
        RemoteButton(text=f"Redaction: {name}", token=token)
        for name, token in redaction_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Notify: {name}", token=token)
        for name, token in notify_scope_tokens.items()
    ]
    return text, tuple(buttons)


def render_project_picker(
    *, projects: Sequence[tuple[str, str]]
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = "Which project?"
    buttons = tuple(
        RemoteButton(text=f"\U0001f4c1 {escape(name)}", token=token)
        for token, name in projects
    )
    return text, buttons


def render_prompt_suggestions(
    *,
    project_name: str,
    context_line: str,
    suggestions: Sequence[tuple[str, str]],
    continue_token: str | None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = (
        f"<b>\U0001f4c1 {escape(project_name)}</b>\n"
        f"<i>{escape(context_line)}</i>\n\n"
        "Try one, or just type your own:"
    )
    buttons: list[RemoteButton] = []
    if continue_token:
        buttons.append(RemoteButton(text="▶ Continue last session", token=continue_token))
    buttons += [RemoteButton(text=label, token=token) for token, label in suggestions]
    return text, tuple(buttons)
