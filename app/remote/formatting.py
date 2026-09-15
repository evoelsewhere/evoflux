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
    "render_permission_card",
    "render_permission_resolved_card",
    "render_health_card",
    "render_changes_card",
    "render_live_status_card",
]

_STATUS_ICON = {"accepted": "\U0001f527", "queued": "⏳", "pending": "⏳"}

_SEVERITY_ICON = {"high": "\U0001f534", "elevated": "\U0001f7e0", "normal": "\U0001f527"}
_SEVERITY_LABEL = {
    "high": "Dangerous command",
    "elevated": "Command",
    "normal": "Permission requested",
}
_RESOLUTION_ICON = {"once": "✅", "always": "\U0001f512", "reject": "❌"}
_RESOLUTION_LABEL = {
    "once": "Allowed once",
    "always": "Allowed for session",
    "reject": "Rejected",
}
_HEALTH_ICON = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


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


def render_live_status_card(
    *, title: str, elapsed_seconds: float, activity_lines: Sequence[str]
) -> tuple[str, tuple[RemoteButton, ...]]:
    """The single status card a live-mode turn edits in place (AC-56). No
    buttons — like ``render_status_card``, this card is never actionable;
    when the turn ends this same message becomes the done/error card."""
    header = f"\U0001f527 <b>{escape(title)}</b> · {format_elapsed(elapsed_seconds)}"
    if not activity_lines:
        return header, ()
    return header + "\n\n" + "\n".join(activity_lines), ()


def render_done_card(
    *,
    title: str,
    elapsed_seconds: float,
    response_text: str | None = None,
    summary_lines: Sequence[str],
    tool_call_count: int,
    diff_token: str | None,
    toollog_token: str | None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    header = f"✅ <b>{escape(title)}</b> · {format_elapsed(elapsed_seconds)}"
    lines = [escape(line) for line in summary_lines]
    parts = [header]
    if response_text and response_text.strip():
        parts.append(escape(response_text.strip()))
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


def render_permission_card(
    *,
    tool: str,
    command: str,
    severity: str,
    agent: str,
    always_glob: str | None,
    always_token: str | None,
    once_token: str,
    reject_token: str,
) -> tuple[str, tuple[RemoteButton, ...]]:
    icon = _SEVERITY_ICON.get(severity, "\U0001f527")
    label = _SEVERITY_LABEL.get(severity, "Permission requested")
    text = (
        f"{icon} <b>{escape(label)}</b>\n"
        f"<pre>{escape(command)}</pre>\n"
        f"<i>{escape(tool)} · {escape(agent)}</i>"
    )
    buttons = [RemoteButton(text="Allow once", token=once_token)]
    if always_token and always_glob:
        buttons.append(
            RemoteButton(
                text=f"\U0001f512 Allow for session — {escape(always_glob)}",
                token=always_token,
            )
        )
    buttons.append(RemoteButton(text="Reject", token=reject_token))
    return text, tuple(buttons)


def render_permission_resolved_card(
    *, command: str, resolution: str
) -> tuple[str, tuple[RemoteButton, ...]]:
    icon = _RESOLUTION_ICON.get(resolution, "✅")
    label = _RESOLUTION_LABEL.get(resolution, "Resolved")
    text = f"{icon} <b>{escape(label)}</b>\n<pre>{escape(command)}</pre>"
    return text, ()


def render_gate_card(
    *, title: str, body: str, actions: Sequence[tuple[str, str]]
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = f"\U0001f510 <b>{escape(title)}</b>\n{escape(body)}"
    buttons = tuple(RemoteButton(text=escape(label), token=token) for token, label in actions)
    return text, buttons


def render_settings_card(
    *,
    connection_label: str,
    model: str,
    permission_mode: str,
    agent_name: str,
    response_mode: str,
    response_mode_tokens: Mapping[str, str],
    mode_tokens: Mapping[str, str],
    agent_tokens: Mapping[str, str],
    model_tokens: Mapping[str, str],
    configured_provider_count: int | None = None,
    redaction_policy: str | None = None,
    notify_scope: str | None = None,
    redaction_tokens: Mapping[str, str] = {},
    notify_scope_tokens: Mapping[str, str] = {},
) -> tuple[str, tuple[RemoteButton, ...]]:
    lines = [
        "<b>⚙️ Settings</b>",
        "",
        f"<b>Connection</b>\n{escape(connection_label)}",
        "",
        f"<b>Mode</b>\n<code>{escape(permission_mode)}</code>",
        "",
        f"<b>Model</b>\n<code>{escape(model)}</code>",
        "",
        f"<b>Lead agent</b>\n<code>{escape(agent_name)}</code>",
        "",
        f"<b>Responses</b>\n<code>{escape(response_mode)}</code>",
    ]
    if configured_provider_count is not None:
        lines += [
            "",
            f"<b>Providers</b>\n{configured_provider_count} configured",
        ]
    if notify_scope is not None:
        lines += ["", f"<b>Notifications</b>\n<code>{escape(notify_scope)}</code>"]
    if redaction_policy is not None:
        lines += [
            "",
            f"<b>Outbound redaction</b>\n<code>{escape(redaction_policy)}</code>",
        ]
    text = "\n".join(lines)

    # bypass is excluded here too (not just at the control.py write path,
    # see ALLOWED_REMOTE_MODES) — a bug in one boundary alone must never be
    # the only thing standing between a phone and bypass mode (AC-48).
    buttons: list[RemoteButton] = [
        RemoteButton(text=f"Mode: {escape(name)}", token=token)
        for name, token in mode_tokens.items()
        if name != "bypass"
    ]
    buttons += [
        RemoteButton(text=f"Agent: {escape(name)}", token=token)
        for name, token in agent_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Responses: {escape(name)}", token=token)
        for name, token in response_mode_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Model: {escape(name)}", token=token)
        for name, token in model_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Redaction: {escape(name)}", token=token)
        for name, token in redaction_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Notify: {escape(name)}", token=token)
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
    buttons += [RemoteButton(text=escape(label), token=token) for token, label in suggestions]
    return text, tuple(buttons)


def render_health_card(checks: Sequence[Mapping[str, object]]) -> str:
    lines = ["<b>\U0001fa7a Health</b>", ""]
    for check in checks:
        icon = _HEALTH_ICON.get(str(check.get("status", "")), "❓")
        label = escape(str(check.get("label", "")))
        detail = escape(str(check.get("detail", "")))
        lines.append(f"{icon} <b>{label}</b>\n{detail}")
    return "\n\n".join(lines)


def render_changes_card(
    *,
    title: str,
    files: Sequence[tuple[str, str, int | None, int | None]],
    additions: int,
    deletions: int,
    file_tokens: Mapping[str, str],
) -> tuple[str, tuple[RemoteButton, ...]]:
    lines = [
        f"<b>\U0001f4dd Changes</b> — {escape(title)}",
        "",
        f"+{additions} -{deletions} across {len(files)} file(s)",
        "",
    ]
    for path, status, file_additions, file_deletions in files:
        counts = ""
        if file_additions is not None or file_deletions is not None:
            counts = f" (+{file_additions or 0} -{file_deletions or 0})"
        lines.append(f"\U0001f4c4 {escape(path)}{counts} — {escape(status)}")
    text = "\n".join(lines)

    buttons = tuple(
        RemoteButton(text=f"View: {escape(path)}", token=token)
        for path, token in file_tokens.items()
    )
    return text, buttons
