import html as html_lib

from app.remote import formatting
from app.remote.contracts import RemoteButton


def test_escape_neutralizes_tag_characters():
    assert formatting.escape("<script>&") == "&lt;script&gt;&amp;"


def test_render_status_card_escapes_title():
    text, buttons = formatting.render_status_card(
        title="Fix <b>tests</b>", status="accepted"
    )
    assert "<b>tests</b>" not in text
    assert html_lib.escape("Fix <b>tests</b>") in text
    assert buttons == ()


def test_render_done_card_escapes_summary_and_adds_buttons():
    text, buttons = formatting.render_done_card(
        title="Fix auth tests",
        elapsed_seconds=72.3,
        summary_lines=["<script>alert(1)</script>", "tests/conftest.py"],
        tool_call_count=4,
        diff_token="diff-tok",
        toollog_token="log-tok",
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
    assert "1m 12s" in text
    assert "4 tool calls" in text
    assert buttons == (
        RemoteButton(text="\U0001f4c4 Full diff", token="diff-tok"),
        RemoteButton(text="\U0001f9fe Tool log", token="log-tok"),
    )


def test_render_done_card_includes_response_text_for_tool_free_turns():
    text, _ = formatting.render_done_card(
        title="What's the weather like",
        elapsed_seconds=2.0,
        response_text="It's sunny and 72F.",
        summary_lines=[],
        tool_call_count=0,
        diff_token=None,
        toollog_token=None,
    )
    assert "It's sunny and 72F." in text


def test_render_done_card_escapes_response_text():
    text, _ = formatting.render_done_card(
        title="Echo",
        elapsed_seconds=1.0,
        response_text="<script>alert(1)</script>",
        summary_lines=[],
        tool_call_count=0,
        diff_token=None,
        toollog_token=None,
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_live_status_card_animates_spinner_by_elapsed_time():
    early, _ = formatting.render_live_status_card(
        title="Streaming", elapsed_seconds=0.0, activity_lines=[]
    )
    later, _ = formatting.render_live_status_card(
        title="Streaming", elapsed_seconds=1.0, activity_lines=[]
    )
    assert early != later
    assert "<b>Streaming</b>" in early
    assert "<b>Streaming</b>" in later


def test_render_live_status_card_includes_response_preview():
    text, _ = formatting.render_live_status_card(
        title="Streaming",
        elapsed_seconds=1.0,
        activity_lines=[],
        response_text="Partial response",
    )
    assert "Partial response" in text


def test_render_live_status_card_includes_stop_action():
    text, buttons = formatting.render_live_status_card(
        title="Running task",
        elapsed_seconds=1.0,
        activity_lines=[],
        stop_token="stop-token",
    )
    assert "Running task" in text
    assert [button.text for button in buttons] == ["Stop task"]
    assert buttons[0].token == "stop-token"


def test_render_live_status_card_truncates_response_preview():
    text, _ = formatting.render_live_status_card(
        title="Streaming",
        elapsed_seconds=1.0,
        activity_lines=[],
        response_text="x" * 4000,
    )
    assert len(text) < 3200
    assert "..." in text


def test_render_done_card_omits_buttons_when_no_tokens():
    _, buttons = formatting.render_done_card(
        title="No-op turn",
        elapsed_seconds=1.0,
        summary_lines=[],
        tool_call_count=0,
        diff_token=None,
        toollog_token=None,
    )
    assert buttons == ()


def test_render_permission_card_shows_command_and_severity_icon():
    text, buttons = formatting.render_permission_card(
        tool="shell",
        command="rm -rf build/",
        severity="high",
        agent="evoflux",
        always_glob=None,
        always_token=None,
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert "rm -rf build/" in text
    assert "\U0001f534" in text  # red circle = high severity
    assert "shell" in text
    assert "evoflux" in text
    assert buttons == (
        RemoteButton(text="Allow once", token="once-tok"),
        RemoteButton(text="Reject", token="reject-tok"),
    )


def test_render_permission_card_escapes_command():
    text, _ = formatting.render_permission_card(
        tool="shell",
        command="echo <script>alert(1)</script>",
        severity="elevated",
        agent="evoflux",
        always_glob=None,
        always_token=None,
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_permission_card_adds_allow_for_session_button_with_glob():
    text, buttons = formatting.render_permission_card(
        tool="shell",
        command="git push origin main",
        severity="elevated",
        agent="evoflux",
        always_glob="git push *",
        always_token="always-tok",
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert "git push *" in text or any("git push *" in b.text for b in buttons)
    assert buttons == (
        RemoteButton(text="Allow once", token="once-tok"),
        RemoteButton(
            text="\U0001f512 Allow for session — git push *", token="always-tok"
        ),
        RemoteButton(text="Reject", token="reject-tok"),
    )


def test_render_permission_card_omits_always_button_without_glob():
    _, buttons = formatting.render_permission_card(
        tool="read",
        command="tests/test_auth.py",
        severity="normal",
        agent="evoflux",
        always_glob=None,
        always_token=None,
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert len(buttons) == 2


def test_render_permission_resolved_card_states_decision_and_has_no_buttons():
    text, buttons = formatting.render_permission_resolved_card(
        command="rm -rf build/", resolution="once"
    )
    assert "rm -rf build/" in text
    assert "Allowed once" in text
    assert buttons == ()


def test_render_permission_resolved_card_escapes_command():
    text, _ = formatting.render_permission_resolved_card(
        command="<script>alert(1)</script>", resolution="reject"
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_settings_card_shows_mode_model_and_agent_buttons():
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="anthropic:claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={"ask": "m1", "auto": "m2"},
        agent_tokens={"evoflux": "a1", "explorer": "a2"},
        model_tokens={"anthropic:claude-sonnet-5": "d1"},
    )
    assert "ask" in text
    assert "anthropic:claude-sonnet-5" in text
    assert "evoflux" in text
    button_tokens = {b.token for b in buttons}
    assert {"m1", "m2", "a1", "a2", "d1"} <= button_tokens


def test_render_settings_card_shows_response_mode_and_its_toggle():
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={"summary": "r1", "live": "r2"},
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
    )
    assert "summary" in text
    button_tokens = {b.token for b in buttons}
    assert {"r1", "r2"} <= button_tokens


def test_render_settings_card_shows_configured_provider_count() -> None:
    text, _ = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
        configured_provider_count=3,
    )
    assert "Providers" in text
    assert "3" in text


def test_render_settings_card_omits_providers_line_when_not_supplied() -> None:
    text, _ = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
    )
    assert "Providers" not in text


def test_render_settings_card_never_offers_a_bypass_button():
    _, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="anthropic:claude-sonnet-5",
        permission_mode="auto",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={"auto": "m1", "bypass": "should-never-appear"},
        agent_tokens={},
        model_tokens={},
    )
    assert "should-never-appear" not in {b.token for b in buttons}
    assert not any("bypass" in b.text.lower() for b in buttons)


def test_render_settings_card_omits_redaction_section_when_not_supplied():
    text, _ = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="anthropic:claude-sonnet-5",
        permission_mode="auto",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
    )
    assert "Outbound redaction" not in text
    assert "Notifications" not in text


def test_render_live_status_card_shows_title_elapsed_and_activity() -> None:
    text, buttons = formatting.render_live_status_card(
        title="Fix failing tests",
        elapsed_seconds=72.0,
        activity_lines=["\U0001f4ad explorer thinking", "\U0001f527 grep foo"],
    )
    assert "Fix failing tests" in text
    assert "1m 12s" in text
    assert "explorer thinking" in text
    assert "grep foo" in text
    assert buttons == ()


def test_render_live_status_card_escapes_title() -> None:
    text, _ = formatting.render_live_status_card(
        title="<script>alert(1)</script>", elapsed_seconds=1.0, activity_lines=[]
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_live_status_card_with_no_activity_yet_still_renders() -> None:
    text, buttons = formatting.render_live_status_card(
        title="New task", elapsed_seconds=0.5, activity_lines=[]
    )
    assert "New task" in text
    assert buttons == ()


def test_render_error_card_escapes_message():
    text, buttons = formatting.render_error_card(
        title="Add rate limiter",
        message="ModuleNotFoundError: <redis>",
        toollog_token="log-tok",
    )
    assert "&lt;redis&gt;" in text
    assert len(buttons) == 1


def test_render_settings_card_now_emits_mode_and_model_buttons():
    """Supersedes the old AC-41 boundary (model/mode were never buttons,
    "desktop only" read-only text) — AC-48/49 revise that: mode and model
    are now remotely settable, so this card must offer buttons for both."""
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={"ask": "m1"},
        agent_tokens={},
        model_tokens={"claude-sonnet-5": "d1"},
        redaction_policy="standard",
        notify_scope="all",
        redaction_tokens={"strict": "r1", "off": "r2"},
        notify_scope_tokens={"all": "n1", "remote_only": "n2"},
    )
    button_texts = [b.text for b in buttons]
    assert any("model" in t.lower() for t in button_texts)
    assert any("mode" in t.lower() for t in button_texts)
    assert any("strict" in t.lower() for t in button_texts)


def test_render_onboarding_card_names_the_phone_and_states_auto_mode() -> None:
    text, buttons = formatting.render_onboarding_card(
        label="My Phone",
        default_permission_mode="auto",
        setup_token="setup-tok",
        health_token="health-tok",
        start_token="start-tok",
    )
    assert "My Phone" in text
    assert "connected to EvoFlux" in text
    assert "auto" in text
    assert "won't ask" in text
    assert len(buttons) == 3
    assert {b.token for b in buttons} == {"setup-tok", "health-tok", "start-tok"}


def test_render_onboarding_card_escapes_label() -> None:
    text, _ = formatting.render_onboarding_card(
        label="<script>alert(1)</script>",
        default_permission_mode="auto",
        setup_token="s",
        health_token="h",
        start_token="w",
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_onboarding_card_states_non_auto_mode_without_the_auto_warning() -> None:
    text, _ = formatting.render_onboarding_card(
        label="My Phone",
        default_permission_mode="ask",
        setup_token="s",
        health_token="h",
        start_token="w",
    )
    assert "ask" in text
    assert "won't ask" not in text


def test_render_gate_card_escapes_action_labels():
    text, buttons = formatting.render_gate_card(
        title="Approve deploy?",
        body="Ready for production",
        actions=[("yes-tok", "Accept <risks>"), ("no-tok", "Reject & wait")],
    )
    assert len(buttons) == 2
    assert buttons[0].text == "Accept &lt;risks&gt;"
    assert buttons[1].text == "Reject &amp; wait"
    assert "<risks>" not in buttons[0].text
    assert "& wait" not in buttons[1].text


def test_render_settings_card_escapes_toggle_names():
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
        redaction_policy="standard",
        notify_scope="all",
        redaction_tokens={"<strict>": "r1", "off": "r2"},
        notify_scope_tokens={"all": "n1", "remote & local": "n2"},
    )
    button_texts = [b.text for b in buttons]
    assert any("&lt;strict&gt;" in t for t in button_texts)
    assert any("remote &amp; local" in t for t in button_texts)


def test_render_prompt_suggestions_escapes_labels():
    text, buttons = formatting.render_prompt_suggestions(
        project_name="<MyProject>",
        context_line="line & context",
        suggestions=[("sug-tok-1", "Suggest <tag>"), ("sug-tok-2", "Other & more")],
        continue_token="cont-tok",
    )
    assert len(buttons) == 3  # continue + 2 suggestions
    # First button is continue
    assert buttons[0].text == "▶ Continue last session"
    # Suggestion buttons should have escaped labels
    assert buttons[1].text == "Suggest &lt;tag&gt;"
    assert buttons[2].text == "Other &amp; more"


def test_render_health_card_shows_each_check_with_its_status_icon():
    text = formatting.render_health_card(
        [
            {"id": "db", "label": "Database", "status": "ok", "detail": "connected"},
            {
                "id": "disk",
                "label": "Disk space",
                "status": "fail",
                "detail": "2.1 GB free",
            },
        ]
    )
    assert "Database" in text
    assert "Disk space" in text
    assert "✅" in text  # ok icon
    assert "❌" in text  # fail icon


def test_render_health_card_escapes_detail_text():
    text = formatting.render_health_card(
        [
            {
                "id": "x",
                "label": "X",
                "status": "warn",
                "detail": "<script>alert(1)</script>",
            }
        ]
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_changes_card_lists_files_with_line_counts_and_buttons():
    text, buttons = formatting.render_changes_card(
        title="Fix auth tests",
        files=[
            ("app/auth.py", "modified", 10, 2),
            ("tests/test_auth.py", "added", 5, 0),
        ],
        additions=15,
        deletions=2,
        file_tokens={"app/auth.py": "tok-1", "tests/test_auth.py": "tok-2"},
    )
    assert "app/auth.py" in text
    assert "+15" in text
    assert "-2" in text
    assert {b.token for b in buttons} == {"tok-1", "tok-2"}


def test_render_changes_card_escapes_file_paths():
    text, _ = formatting.render_changes_card(
        title="Task",
        files=[("<script>.py", "modified", 1, 0)],
        additions=1,
        deletions=0,
        file_tokens={},
    )
    assert "<script>.py" not in text
    assert "&lt;script&gt;.py" in text


# ── Markdown → Telegram HTML ─────────────────────────────────────────────────


class TestMarkdownToTelegramHtml:
    """Regression tests for markdown_to_telegram_html.  Telegram uses
    parse_mode="HTML" so every Markdown construct must be converted."""

    def test_bold(self) -> None:
        assert formatting.markdown_to_telegram_html("**bold**") == "<b>bold</b>"

    def test_italic(self) -> None:
        assert formatting.markdown_to_telegram_html("*italic*") == "<i>italic</i>"

    def test_bold_italic(self) -> None:
        result = formatting.markdown_to_telegram_html("***both***")
        assert "<b>" in result and "<i>" in result

    def test_inline_code(self) -> None:
        result = formatting.markdown_to_telegram_html("use `foo()` here")
        assert "<code>foo()</code>" in result

    def test_fenced_code_block(self) -> None:
        md = "```python\ndef f():\n    pass\n```"
        result = formatting.markdown_to_telegram_html(md)
        assert "<pre>" in result
        assert "def f():" in result

    def test_link(self) -> None:
        result = formatting.markdown_to_telegram_html(
            "[click here](https://example.com)"
        )
        assert '<a href="https://example.com">click here</a>' in result

    def test_heading(self) -> None:
        result = formatting.markdown_to_telegram_html("# Title")
        assert "<b>Title</b>" in result

    def test_strikethrough(self) -> None:
        result = formatting.markdown_to_telegram_html("~~deleted~~")
        assert "<s>deleted</s>" in result

    def test_unordered_list(self) -> None:
        result = formatting.markdown_to_telegram_html("- item one\n- item two")
        assert "• item one" in result
        assert "• item two" in result

    def test_html_escape_before_conversion(self) -> None:
        """Literal < and > in source Markdown must be escaped, not treated
        as HTML tags."""
        result = formatting.markdown_to_telegram_html("x < y and y > z")
        assert "&lt;" in result
        assert "&gt;" in result

    def test_empty_input(self) -> None:
        assert formatting.markdown_to_telegram_html("") == ""

    def test_none_like_empty(self) -> None:
        # The function accepts str, but callers may pass empty.
        assert formatting.markdown_to_telegram_html("") == ""

    def test_code_block_protected_from_inner_formatting(self) -> None:
        """Bold markers inside code blocks must NOT be converted."""
        md = "```\n**not bold**\n```"
        result = formatting.markdown_to_telegram_html(md)
        assert "<b>" not in result
        assert "**not bold**" in result

    def test_inline_code_protected_from_inner_formatting(self) -> None:
        md = "`**not bold**`"
        result = formatting.markdown_to_telegram_html(md)
        assert "<b>" not in result

    def test_mixed_content(self) -> None:
        md = (
            "# Header\n\n"
            "Some **bold** and *italic* text.\n\n"
            "- Item 1\n"
            "- Item 2\n\n"
            "Check `code()` and [link](https://example.com)."
        )
        result = formatting.markdown_to_telegram_html(md)
        assert "<b>Header</b>" in result
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "• Item 1" in result
        assert "<code>code()</code>" in result
        assert '<a href="https://example.com">link</a>' in result


# ── derive_card_heading ──────────────────────────────────────────────────────


class TestDeriveCardHeading:
    def test_short_message_used_as_is(self) -> None:
        assert formatting.derive_card_heading("fix the bug") == "fix the bug"

    def test_long_message_truncated_with_ellipsis(self) -> None:
        msg = "a" * 100
        result = formatting.derive_card_heading(msg)
        assert len(result) <= 60
        assert result.endswith("\u2026")

    def test_newlines_replaced_with_spaces(self) -> None:
        assert formatting.derive_card_heading("line1\nline2") == "line1 line2"

    def test_none_uses_fallback(self) -> None:
        assert formatting.derive_card_heading(None) == "Task"

    def test_empty_string_uses_fallback(self) -> None:
        assert formatting.derive_card_heading("") == "Task"

    def test_whitespace_only_uses_fallback(self) -> None:
        assert formatting.derive_card_heading("   ") == "Task"

    def test_custom_fallback(self) -> None:
        assert formatting.derive_card_heading(None, fallback_title="Custom") == "Custom"


# ── render_done_card with usage data ─────────────────────────────────────────


class TestRenderDoneCardUsage:
    def test_done_card_shows_model_and_tokens(self) -> None:
        text, _ = formatting.render_done_card(
            title="Task",
            elapsed_seconds=5.0,
            summary_lines=[],
            tool_call_count=0,
            diff_token=None,
            toollog_token=None,
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cached_tokens=200,
            cost_usd=0.015,
        )
        assert "claude-sonnet-4-20250514" in text
        # Compact format: ↓1K ↑500 · cache 200 (20%)
        assert "1K" in text
        assert "500" in text
        assert "cache 200" in text
        assert "20%" in text
        assert "$0.0150" in text

    def test_done_card_shows_reasoning_tokens(self) -> None:
        text, _ = formatting.render_done_card(
            title="Task",
            elapsed_seconds=2.0,
            summary_lines=[],
            tool_call_count=0,
            diff_token=None,
            toollog_token=None,
            model="o3-mini",
            input_tokens=500,
            output_tokens=200,
            reasoning_tokens=3000,
        )
        assert "reasoning 3K" in text

    def test_done_card_omits_usage_when_none(self) -> None:
        text, _ = formatting.render_done_card(
            title="Task",
            elapsed_seconds=1.0,
            summary_lines=[],
            tool_call_count=0,
            diff_token=None,
            toollog_token=None,
        )
        assert "\U0001f4ca" not in text  # chart icon = usage footer

    def test_done_card_converts_markdown_response(self) -> None:
        """Response text with Markdown should be converted to HTML."""
        text, _ = formatting.render_done_card(
            title="Task",
            elapsed_seconds=1.0,
            summary_lines=[],
            tool_call_count=0,
            diff_token=None,
            toollog_token=None,
            response_text="**fixed** the `auth.ts` bug",
        )
        assert "<b>fixed</b>" in text
        assert "<code>auth.ts</code>" in text


# ── render_live_status_card with usage ────────────────────────────────────────


class TestRenderLiveStatusCardUsage:
    def test_live_card_shows_model_and_tokens(self) -> None:
        text, _ = formatting.render_live_status_card(
            title="Working",
            elapsed_seconds=3.0,
            activity_lines=[],
            model="gpt-4",
            input_tokens=500,
            output_tokens=100,
            cost_usd=0.005,
        )
        assert "gpt-4" in text
        assert "500" in text
        assert "100" in text
        assert "$0.0050" in text

    def test_live_card_omits_usage_when_none(self) -> None:
        text, _ = formatting.render_live_status_card(
            title="Working",
            elapsed_seconds=1.0,
            activity_lines=["tool call"],
        )
        assert "\U0001f4ca" not in text
