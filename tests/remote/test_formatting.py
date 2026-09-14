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


def test_render_error_card_escapes_message():
    text, buttons = formatting.render_error_card(
        title="Add rate limiter",
        message="ModuleNotFoundError: <redis>",
        toollog_token="log-tok",
    )
    assert "&lt;redis&gt;" in text
    assert len(buttons) == 1


def test_render_settings_card_never_emits_model_or_permission_buttons():
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask each time",
        redaction_policy="standard",
        notify_scope="all",
        redaction_tokens={"strict": "r1", "off": "r2"},
        notify_scope_tokens={"all": "n1", "remote_only": "n2"},
    )
    button_texts = [b.text for b in buttons]
    assert not any("model" in t.lower() for t in button_texts)
    assert not any("permission" in t.lower() for t in button_texts)
    assert any("strict" in t.lower() for t in button_texts)
