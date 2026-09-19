from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence

from app.remote.contracts import RemoteButton

__all__ = [
    "derive_card_heading",
    "escape",
    "format_elapsed",
    "markdown_to_telegram_html",
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
    "render_onboarding_card",
]

_CARD_HEADING_MAX_LENGTH = 60

_STATUS_ICON = {"accepted": "\U0001f527", "queued": "⏳", "pending": "⏳"}

_SEVERITY_ICON = {
    "high": "\U0001f534",
    "elevated": "\U0001f7e0",
    "normal": "\U0001f527",
}
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


def _format_token_count(n: int) -> str:
    """Format a token count as a human-readable short string.

    Examples: 128000 → "128K", 1000000 → "1M", 200000 → "200K".
    """
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f}M"
    if n >= 1_000:
        return f"{n // 1_000:,}K"
    return str(n)


# ── Markdown → Telegram HTML ─────────────────────────────────────────────────
#
# Telegram supports a strict HTML subset: <b>, <i>, <u>, <s>, <code>, <pre>,
# <a href>, <tg-spoiler>, <blockquote>.  No Markdown parse mode is used;
# the adapter always sends ``parse_mode="HTML"``.
#
# The converter runs AFTER HTML-escaping, so literal ``<`` / ``>`` / ``&`` in
# the source Markdown are already ``&lt;`` / ``&gt;`` / ``&amp;`` and will
# not collide with the HTML tags we inject.

# Placeholder used to protect pre-escaped code spans from later regex passes.
_CODE_SLOT = "\x00CODE{}\x00"
_CODE_SLOT_RE = re.compile(r"\x00CODE(\d+)\x00")


def markdown_to_telegram_html(text: str) -> str:
    """Convert a Markdown string to Telegram-safe HTML.

    The input is first HTML-escaped so literal ``<`` / ``>`` are safe.
    Markdown constructs are then converted to the Telegram HTML subset.
    Code blocks and inline code are protected from inner conversions.
    """
    if not text:
        return ""

    # 1. HTML-escape everything first.
    out = html.escape(text, quote=False)

    # 2. Protect fenced code blocks: ```lang\n...\n```  →  <pre>...</pre>
    code_slots: list[str] = []

    def _code_repl(m: re.Match) -> str:
        lang = m.group(1) or ""
        body = m.group(2)
        if lang:
            tag = f'<pre><code class="language-{lang}">{body}</code></pre>'
        else:
            tag = f"<pre>{body}</pre>"
        idx = len(code_slots)
        code_slots.append(tag)
        return _CODE_SLOT.format(idx)

    out = re.sub(
        r"```(\w*)\n(.*?)```",
        _code_repl,
        out,
        flags=re.DOTALL,
    )

    # 3. Protect inline code: `...`  →  <code>...</code>
    def _inline_repl(m: re.Match) -> str:
        idx = len(code_slots)
        code_slots.append(f"<code>{m.group(1)}</code>")
        return _CODE_SLOT.format(idx)

    out = re.sub(r"`([^`\n]+)`", _inline_repl, out)

    # 4. Headings: # / ## / ### → bold line
    out = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", out, flags=re.MULTILINE)

    # 5. Bold + italic: ***text*** → <b><i>text</i></b>
    out = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", out)

    # 6. Bold: **text** or __text__ → <b>text</b>
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"__(.+?)__", r"<b>\1</b>", out)

    # 7. Italic: *text* or _text_ → <i>text</i>
    #    Avoid matching * inside words (e.g. file_path*) by requiring a
    #    word boundary or whitespace before the opening *.
    out = re.sub(r"(?<!\w)\*([^\s*](?:[^*]*[^\s*])?)\*", r"<i>\1</i>", out)
    out = re.sub(r"(?<!\w)_([^\s_](?:[^_]*[^\s_])?)_(?!\w)", r"<i>\1</i>", out)

    # 8. Strikethrough: ~~text~~ → <s>text</s>
    out = re.sub(r"~~(.+?)~~", r"<s>\1</s>", out)

    # 9. Links: [text](url) → <a href="url">text</a>
    out = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        out,
    )

    # 10. Unordered list: - item or * item → • item
    out = re.sub(r"^[\-\*]\s+", "• ", out, flags=re.MULTILINE)

    # 11. Restore protected code slots.
    out = _CODE_SLOT_RE.sub(lambda m: code_slots[int(m.group(1))], out)

    return out


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


def derive_card_heading(
    user_message: str | None,
    fallback_title: str = "Task",
) -> str:
    """Derive a concise, meaningful card heading.

    Prefers a truncated version of the user's original message (which is
    always concrete and contextual) over a session title that is often
    generic ("Task", "New task") or an LLM-generated title that may not
    have been generated yet.
    """
    if user_message and user_message.strip():
        text = user_message.strip().replace("\n", " ")
        if len(text) > _CARD_HEADING_MAX_LENGTH:
            return text[: _CARD_HEADING_MAX_LENGTH - 1].rstrip() + "\u2026"
        return text
    return fallback_title


def render_status_card(
    *, title: str, status: str
) -> tuple[str, tuple[RemoteButton, ...]]:
    icon = _STATUS_ICON.get(status, "\U0001f527")
    text = f"{icon} <b>{escape(title)}</b>\n<i>{escape(status)}</i>"
    return text, ()


def render_live_status_card(
    *,
    title: str,
    elapsed_seconds: float,
    activity_lines: Sequence[str],
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    """The single status card a live-mode turn edits in place (AC-56). No
    buttons — like ``render_status_card``, this card is never actionable;
    when the turn ends this same message becomes the done/error card."""
    header = f"\U0001f527 <b>{escape(title)}</b> · {format_elapsed(elapsed_seconds)}"
    parts = [header]
    # Token / model footer — only shown once the first usage data arrives.
    meta_parts: list[str] = []
    if model:
        meta_parts.append(escape(model))
    if input_tokens is not None or output_tokens is not None:
        meta_parts.append(f"{input_tokens or 0:,} \u2192 {output_tokens or 0:,} tok")
    if cost_usd is not None and cost_usd > 0:
        meta_parts.append(f"${cost_usd:.4f}")
    if meta_parts:
        parts.append("\U0001f4ca " + " \u00b7 ".join(meta_parts))
    if activity_lines:
        parts.append("\n".join(activity_lines))
    return "\n\n".join(parts), ()


def render_done_card(
    *,
    title: str,
    elapsed_seconds: float,
    response_text: str | None = None,
    summary_lines: Sequence[str],
    tool_call_count: int,
    diff_token: str | None,
    toollog_token: str | None,
    model: str | None = None,
    context_window: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    cost_usd: float | None = None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    header = f"✅ <b>{escape(title)}</b> · {format_elapsed(elapsed_seconds)}"
    lines = [escape(line) for line in summary_lines]
    parts = [header]
    if response_text and response_text.strip():
        parts.append(markdown_to_telegram_html(response_text.strip()))
    if lines:
        parts.append("\n".join(lines))
    parts.append(f"<b>{tool_call_count} tool calls</b>")

    # ── Usage footer ─────────────────────────────────────────────────
    # Build a compact multi-line usage block instead of a single dense
    # dot-separated line, giving each dimension room to breathe.
    usage_lines: list[str] = []
    total_tokens = (input_tokens or 0) + (output_tokens or 0)

    # Line 1: model name
    if model:
        usage_lines.append(escape(model))

    # Line 2: token summary — "📊 2.4k → 1.1k" with cache/reasoning callouts
    if total_tokens > 0:
        tok_parts: list[str] = []
        tok_parts.append(f"↓{_format_token_count(input_tokens or 0)}")
        tok_parts.append(f"↑{_format_token_count(output_tokens or 0)}")
        tok_line = "\U0001f4ca " + " ".join(tok_parts)

        sub_parts: list[str] = []
        if cached_tokens and cached_tokens > 0 and (input_tokens or 0) > 0:
            hit_pct = cached_tokens / (input_tokens or 1) * 100
            sub_parts.append(
                f"cache {_format_token_count(cached_tokens)} ({hit_pct:.0f}%)"
            )
        if reasoning_tokens and reasoning_tokens > 0:
            sub_parts.append(f"reasoning {_format_token_count(reasoning_tokens)}")
        if sub_parts:
            tok_line += " · " + " · ".join(sub_parts)
        usage_lines.append(tok_line)

    # Line 3: context window usage bar
    if context_window and context_window > 0 and (input_tokens or 0) > 0:
        used_pct = min((input_tokens or 0) / context_window * 100, 100)
        filled = round(used_pct / 5)  # 20 bars = 100%
        bar = "\u2588" * filled + "\u2591" * (20 - filled)
        usage_lines.append(
            f"{_format_token_count(context_window)} ctx [{bar}] {used_pct:.0f}%"
        )

    # Line 4: cost — show component breakdown when available
    if cost_usd is not None and cost_usd > 0:
        usage_lines.append(f"\U0001f4b0 ${cost_usd:.4f}")

    if usage_lines:
        parts.append("\n".join(usage_lines))
    text = "\n\n".join(parts)
    buttons: list[RemoteButton] = []
    if diff_token:
        buttons.append(RemoteButton(text="\U0001f4c4 Full diff", token=diff_token))
    if toollog_token:
        buttons.append(RemoteButton(text="\U0001f9fe Tool log", token=toollog_token))
    return text, tuple(buttons)


def _sanitize_error_message(message: str) -> str:
    """Make common provider errors more user-friendly.

    Strips internal provider details and HTTP status codes that confuse
    non-technical users while preserving enough to diagnose the issue.
    """
    # Model unavailable errors — show a clean message.
    if (
        "model is unavailable" in message.lower()
        or "rejected the request" in message.lower()
    ):
        # Extract model name if present (e.g. "opencode:deepseek-v4-flash-free")
        import re

        model_match = re.search(r"(\w+:[\w-]+)\s+rejected", message)
        if model_match:
            return f"Model <code>{escape(model_match.group(1))}</code> is currently unavailable. Check your provider dashboard or try a different model."
        return "The selected model is currently unavailable. Check your provider dashboard or try a different model."
    return escape(message)


def render_error_card(
    *, title: str, message: str, toollog_token: str | None
) -> tuple[str, tuple[RemoteButton, ...]]:
    friendly = _sanitize_error_message(message)
    text = f"❌ <b>{escape(title)}</b>\n\n<b>Error:</b> {friendly}"
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
    buttons = tuple(
        RemoteButton(text=escape(label), token=token) for token, label in actions
    )
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


def render_onboarding_card(
    *,
    label: str,
    default_permission_mode: str,
    setup_token: str,
    health_token: str,
    start_token: str,
) -> tuple[str, tuple[RemoteButton, ...]]:
    """The first-run card sent right after a successful pairing (AC-54) —
    a starting point rather than a dead end. The mode line is stated
    because it is the single most consequential default the operator
    should know about at pairing time: "auto" means no approval prompts
    will ever reach this phone."""
    mode_line = f"Mode is <code>{escape(default_permission_mode)}</code>"
    if default_permission_mode == "auto":
        mode_line += " — the agent won't ask before running commands."
    else:
        mode_line += "."
    text = (
        f'✅ <b>Paired!</b> This phone ("{escape(label)}") is now connected '
        f"to EvoFlux.\n\n{mode_line}"
    )
    buttons = (
        RemoteButton(text="⚙️ Set up", token=setup_token),
        RemoteButton(text="\U0001fa7a Health check", token=health_token),
        RemoteButton(text="\U0001f4ac Just start working", token=start_token),
    )
    return text, buttons


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
        buttons.append(
            RemoteButton(text="▶ Continue last session", token=continue_token)
        )
    buttons += [
        RemoteButton(text=escape(label), token=token) for token, label in suggestions
    ]
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


def render_session_list_card(
    sessions: Sequence[Mapping[str, str]],
) -> tuple[str, tuple[RemoteButton, ...]]:
    """Render a session-history list card.

    Each item in *sessions* must have ``title``, ``subtitle``, and ``token``.
    Returns text with a header and up to 5 inline buttons.
    """
    parts = ["<b>\U0001f4cb Recent sessions</b>"]
    buttons: list[RemoteButton] = []
    for item in sessions:
        label = escape(item.get("title", "Untitled"))
        buttons.append(RemoteButton(text=label, token=item["token"]))
    if not buttons:
        parts.append("No sessions yet.")
    return "\n\n".join(parts), tuple(buttons)


def render_session_detail_card(
    *,
    title: str,
    mode: str,
    created_at: str,
    message_count: int,
    tool_call_count: int,
    last_user_message: str | None,
    last_assistant_message: str | None,
    switch_token: str | None,
    summarize_token: str | None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    """Render a single session's detail card with optional action buttons."""
    parts = [
        f"<b>\U0001f4c4 {escape(title)}</b>",
        f"Mode: {escape(mode)} · Created: {escape(created_at)}",
        f"{message_count} messages · {tool_call_count} tool calls",
    ]
    if last_user_message:
        truncated = last_user_message[:200]
        if len(last_user_message) > 200:
            truncated += "\u2026"
        parts.append(f"\U0001f464 {escape(truncated)}")
    if last_assistant_message:
        truncated = last_assistant_message[:200]
        if len(last_assistant_message) > 200:
            truncated += "\u2026"
        parts.append(f"\U0001f916 {markdown_to_telegram_html(truncated)}")
    buttons: list[RemoteButton] = []
    if switch_token:
        buttons.append(RemoteButton(text="\u2705 Switch here", token=switch_token))
    if summarize_token:
        buttons.append(RemoteButton(text="\U0001f4dd Summarize", token=summarize_token))
    return "\n\n".join(parts), tuple(buttons)
