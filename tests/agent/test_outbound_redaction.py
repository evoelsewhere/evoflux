from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.outbound_redaction import (
    OutboundContext,
    OutboundSensitiveDataError,
    protect_outbound_text,
    protect_outbound_value,
    protect_outbound_payload,
)
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ImageDataBlock,
    ImageUrlBlock,
    TextBlock,
    ToolCall,
    ToolMessage,
)


def test_redact_masks_configured_secret_without_mutating_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "unusual-local-credential-value"
    monkeypatch.setenv("SAMPLE_API_KEY", secret)
    original = HumanMessage(content=f"Use {secret} for this request")

    prompt, messages, report = protect_outbound_payload(
        system_prompt=f"Never reveal {secret}",
        messages=[original],
        policy="redact",
    )

    assert secret not in prompt
    assert secret not in (messages[0].content or "")
    assert "[REDACTED:configured-secret]" in prompt
    assert report.matches == 2
    assert original.content == f"Use {secret} for this request"
    assert messages[0] is not original


def test_redact_masks_credentials_loaded_only_from_saved_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    secret = "saved-only-opaque-credential"
    (tmp_path / ".env").write_text(
        f"CUSTOM_SERVICE_TOKEN={secret}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("CUSTOM_SERVICE_TOKEN", raising=False)

    _, messages, report = protect_outbound_payload(
        system_prompt="safe",
        messages=[HumanMessage(content=f"Use {secret}")],
        policy="redact",
    )

    assert secret not in (messages[0].content or "")
    assert report.categories == ("configured-secret",)


def test_redact_covers_tool_arguments_text_parts_and_credentialed_urls() -> None:
    assistant = AssistantMessage(
        tool_calls=[
            ToolCall(
                id="call-1",
                function=FunctionCall(
                    name="fetch",
                    arguments='{"authorization": "Bearer abcdefghijklmnop"}',
                ),
            )
        ]
    )
    tool = ToolMessage(
        tool_call_id="call-1",
        content="password=correct-horse-battery-staple",
        parts=[
            TextBlock(text="client_secret: abcdefghijklmnop"),
            ImageUrlBlock(url="https://user:password123@example.com/image.png"),
            ImageDataBlock(data="c2FmZS1ieXRlcw==", media_type="image/png"),
        ],
    )

    _, protected, report = protect_outbound_payload(
        system_prompt="safe",
        messages=[assistant, tool],
        policy="redact",
    )

    protected_assistant = protected[0]
    protected_tool = protected[1]
    assert isinstance(protected_assistant, AssistantMessage)
    assert isinstance(protected_tool, ToolMessage)
    assert (
        protected_assistant.tool_calls
        and "abcdefghijklmnop"
        not in protected_assistant.tool_calls[0].function.arguments
    )
    assert "correct-horse-battery-staple" not in (protected_tool.content or "")
    assert protected_tool.parts
    assert isinstance(protected_tool.parts[0], TextBlock)
    assert "abcdefghijklmnop" not in protected_tool.parts[0].text
    assert isinstance(protected_tool.parts[1], ImageUrlBlock)
    assert "password123" not in protected_tool.parts[1].url
    assert protected_tool.parts[2] == tool.parts[2]
    assert report.matches >= 4


def test_block_policy_stops_request_without_echoing_secret() -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"

    with pytest.raises(OutboundSensitiveDataError) as raised:
        protect_outbound_payload(
            system_prompt="safe",
            messages=[HumanMessage(content=secret)],
            policy="block",
        )

    assert secret not in str(raised.value)
    assert "provider-token" in str(raised.value)


def test_block_policy_reports_secret_count_without_echoing_secret() -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"

    with pytest.raises(OutboundSensitiveDataError) as raised:
        protect_outbound_text(
            secret,
            policy="block",
            pii_policy="standard",
            context=OutboundContext(channel="model", destination="github"),
        )

    assert secret not in str(raised.value)
    assert "for github" in str(raised.value)


def test_off_policy_preserves_payload() -> None:
    message = HumanMessage(content="Authorization: Bearer leave-this-visible")

    prompt, messages, report = protect_outbound_payload(
        system_prompt="password=leave-this-visible",
        messages=[message],
        policy="off",
    )

    assert prompt == "password=leave-this-visible"
    assert messages == [message]
    assert report.matches == 0


def test_standard_pii_uses_stable_aliases_and_keeps_local_history() -> None:
    original = HumanMessage(
        content=(
            "Email linh@example.com, repeat LINH@example.com; "
            "phone +84 912 345 678; card 4111 1111 1111 1111; "
            "public IP: 8.8.8.8; private 192.168.1.10"
        )
    )

    _, messages, report = protect_outbound_payload(
        system_prompt="safe",
        messages=[original],
        policy="off",
        pii_policy="standard",
    )

    protected = messages[0].content or ""
    assert protected.count("[EMAIL_1]") == 2
    assert "[PHONE_1]" in protected
    assert "[CARD_1]" in protected
    assert "[IP_1]" in protected
    assert "192.168.1.10" in protected
    assert "linh@example.com" in (original.content or "")
    assert {"card", "email", "ip", "phone"} <= set(report.categories)


def test_strict_pii_masks_private_ips_and_structured_identity_fields() -> None:
    message = HumanMessage(
        content=(
            '{"full_name": "Nguyen Van Linh", '
            '"address": "12 Nguyen Hue, District 1", '
            '"national_id": "079123456789", '
            '"internal_ip": "192.168.1.10"}'
        )
    )

    _, messages, report = protect_outbound_payload(
        system_prompt="safe",
        messages=[message],
        policy="off",
        pii_policy="strict",
    )

    protected = messages[0].content or ""
    assert '"full_name": "[NAME_1]"' in protected
    assert '"address": "[ADDRESS_1]"' in protected
    assert '"national_id": "[ID_1]"' in protected
    assert "[IP_1]" in protected
    assert {"address", "id", "ip", "name"} <= set(report.categories)


def test_pii_off_does_not_mask_personal_data() -> None:
    message = HumanMessage(content="Email me at person@example.com or +1 202 555 0198")

    _, messages, report = protect_outbound_payload(
        system_prompt="safe",
        messages=[message],
        policy="off",
        pii_policy="off",
    )

    assert messages == [message]
    assert report.matches == 0


def test_standard_pii_ignores_non_card_numbers_and_private_ips() -> None:
    message = HumanMessage(
        content=(
            "Build 1234567890123, version 1.2.3.4, host 10.0.0.8, "
            "timestamp 2026-07-31 15:54:04"
        )
    )

    _, messages, report = protect_outbound_payload(
        system_prompt="safe",
        messages=[message],
        policy="off",
        pii_policy="standard",
    )

    assert messages == [message]
    assert report.matches == 0


def test_standard_pii_masks_north_american_phone_format() -> None:
    message = HumanMessage(content="Call (202) 555-0198")

    _, messages, report = protect_outbound_payload(
        system_prompt="safe",
        messages=[message],
        policy="off",
        pii_policy="standard",
    )

    assert messages[0].content == "Call [PHONE_1]"
    assert report.categories == ("phone",)


def test_block_secret_policy_masks_pii_without_blocking_the_request() -> None:
    value = "person@example.com"

    protected, report = protect_outbound_text(
        value,
        policy="block",
        pii_policy="standard",
    )

    assert protected == "[EMAIL_1]"
    assert value not in protected
    assert report.secret_matches == 0
    assert report.pii_matches == 1


def test_nested_external_arguments_are_protected() -> None:
    protected, report = protect_outbound_value(
        {
            "filters": [{"headers": {"authorization": "Bearer abcdefghijklmnop"}}],
            "callback": "https://user:password123@example.com/hook",
        },
        policy="redact",
        pii_policy="off",
    )

    assert isinstance(protected, dict)
    serialized = str(protected)
    assert "abcdefghijklmnop" not in serialized
    assert "password123" not in serialized
    assert report.matches >= 2


def test_url_query_credentials_are_protected() -> None:
    protected, report = protect_outbound_text(
        "https://example.test/callback?token=abcdefghijklmnop&state=ok",
        policy="redact",
        pii_policy="off",
        context=OutboundContext(channel="web", destination="fetch"),
    )

    assert "abcdefghijklmnop" not in protected
    assert "[REDACTED:url-secret]" in protected
    assert "state=ok" in protected
    assert report.secret_categories == ("url-secret-query",)


def test_protected_placeholders_are_idempotent_and_not_double_counted() -> None:
    protected, first_report = protect_outbound_text(
        "Authorization: Bearer abcdefghijklmnop",
        policy="redact",
        pii_policy="off",
    )
    protected_again, second_report = protect_outbound_text(
        protected,
        policy="redact",
        pii_policy="off",
    )

    assert protected_again == protected
    assert first_report.secret_matches == 1
    assert second_report.matches == 0


def test_nested_external_object_keys_are_protected() -> None:
    secret_key = "token=abcdefghijklmnop"

    protected, report = protect_outbound_value(
        {secret_key: "safe"},
        policy="redact",
        pii_policy="off",
    )

    assert isinstance(protected, dict)
    assert secret_key not in protected
    assert "abcdefghijklmnop" not in str(protected)
    assert report.secret_matches == 1
