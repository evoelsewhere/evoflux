"""Sensitive-data protection for payloads leaving the agent.

The database and in-memory agent state retain their original content. This
module creates an external-request copy immediately before a model, web, or
MCP call, so protection cannot corrupt tool-call pairing or local history.
"""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from loguru import logger

from app.agent.schemas.chat import (
    AssistantMessage,
    ChatMessage,
    HumanMessage,
    ImageUrlBlock,
    TextBlock,
    ToolMessage,
)

OutboundDataPolicy = Literal["block", "redact", "off"]
OutboundPiiPolicy = Literal["off", "standard", "strict"]
OutboundChannel = Literal["model", "web", "mcp", "other"]


@dataclass(frozen=True)
class OutboundContext:
    """Safe routing metadata for an external request.

    Callers must not put payload values, credentials, or raw URLs in this
    object. It exists only to make policy decisions and audit logs explainable.
    """

    channel: OutboundChannel
    destination: str | None = None

    @property
    def label(self) -> str:
        return f"{self.channel}:{self.destination or 'external'}"

_SENSITIVE_ENV_NAME = re.compile(
    r"(?:^|_)(?:API_?KEY|ACCESS_?KEY|AUTH|BEARER|CREDENTIAL|"
    r"PASSWORD|PASSWD|PRIVATE_?KEY|SECRET|SESSION|TOKEN)(?:_|$)",
    re.IGNORECASE,
)

_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?"
            r"-----END [^-\r\n]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED:private-key]",
    ),
    (
        "authorization",
        re.compile(
            r"""(?imx)
            (
              \b(?:authorization|proxy-authorization)["']?\s*[:=]\s*["']?
              (?:bearer|basic|token)\s+
            )
            ((?!\[REDACTED:)[^"'\s,;}]+)
            """
        ),
        r"\1[REDACTED:authorization]",
    ),
    (
        "authorization",
        re.compile(
            r"(?i)(\b(?:bearer|basic|token)\s+)"
            r"(?!\[REDACTED:)[^\s,;}\]]{8,}"
        ),
        r"\1[REDACTED:authorization]",
    ),
    (
        "url-password",
        re.compile(
            r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)"
            r"((?!\[REDACTED:)[^@\s/]+)(@)"
        ),
        r"\1[REDACTED:url-password]\3",
    ),
    (
        "url-secret-query",
        re.compile(
            r"(?ix)([?&](?:api[_-]?key|access[_-]?(?:key|token)|"
            r"auth[_-]?token|client[_-]?secret|credential|password|passwd|"
            r"secret|token|refresh[_-]?token|session[_-]?token)=)"
            r"((?!\[REDACTED:)[^&#\s]{8,})"
        ),
        r"\1[REDACTED:url-secret]",
    ),
    (
        "secret-assignment",
        re.compile(
            r"""(?ix)
            (
              ["']?
              (?:api[_-]?key|access[_-]?(?:key|token)|auth[_-]?token|
                 client[_-]?secret|credential|password|passwd|
                 private[_-]?key|secret|token|access[_-]?token|
                 refresh[_-]?token|session[_-]?token)
              ["']?\s*[:=]\s*
            )
            (["'])
            ((?!\[REDACTED:)[^"'\r\n]{8,})
            \2
            """
        ),
        r"\1\2[REDACTED:secret]\2",
    ),
    (
        "secret-assignment",
        re.compile(
            r"""(?ix)
            (
              (?:api[_-]?key|access[_-]?(?:key|token)|auth[_-]?token|
                 client[_-]?secret|credential|password|passwd|
                 private[_-]?key|secret|token|refresh[_-]?token|
                 session[_-]?token)
              \s*[:=]\s*
            )
            ([A-Za-z0-9_+/%=:@.-]{8,})
            """
        ),
        r"\1[REDACTED:secret]",
    ),
    (
        "provider-token",
        re.compile(
            r"\b(?:"
            r"sk-[A-Za-z0-9_-]{16,}|"
            r"gh[opusr]_[A-Za-z0-9]{20,}|"
            r"xox[baprs]-[A-Za-z0-9-]{16,}|"
            r"AIza[0-9A-Za-z_-]{20,}|"
            r"AKIA[0-9A-Z]{16}"
            r")\b"
        ),
        "[REDACTED:provider-token]",
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
            r"\.[A-Za-z0-9_-]{8,}\b"
        ),
        "[REDACTED:jwt]",
    ),
)

_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![\w.-])",
    re.IGNORECASE,
)
_PAYMENT_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_PHONE_PATTERN = re.compile(r"(?<![\w])(?:\+\d|\(\d|\d)[\d ().-]{7,}\d(?![\w])")
_STRICT_FIELD_PATTERN = re.compile(
    r"""(?ix)
    (
      ["']?
      (?P<key>
        full[_-]?name|first[_-]?name|last[_-]?name|
        street[_-]?address|address|
        passport(?:[_-]?(?:number|no))?|
        national[_-]?id|tax[_-]?id|ssn|cccd|cmnd
      )
      ["']?\s*[:=]\s*
    )
    (?P<quote>["'])
    (?P<value>[^"'\r\n]{2,})
    (?P=quote)
    """
)


class OutboundSensitiveDataError(PermissionError):
    """Raised when block mode finds sensitive text before a provider call."""


@dataclass(frozen=True)
class RedactionReport:
    matches: int = 0
    secret_matches: int = 0
    pii_matches: int = 0
    categories: tuple[str, ...] = ()
    secret_categories: tuple[str, ...] = ()
    context: OutboundContext | None = None


class _Redactor:
    def __init__(
        self,
        *,
        protect_secrets: bool,
        pii_policy: OutboundPiiPolicy,
        context: OutboundContext | None = None,
    ) -> None:
        self.matches = 0
        self.secret_matches = 0
        self.pii_matches = 0
        self.categories: set[str] = set()
        self.secret_categories: set[str] = set()
        self.exact_secrets = _configured_secret_values() if protect_secrets else ()
        self.protect_secrets = protect_secrets
        self.pii_policy = pii_policy
        self.context = context
        self._pii_aliases: dict[tuple[str, str], str] = {}
        self._pii_counts: dict[str, int] = {}

    def text(self, value: str | None) -> str | None:
        if value is None or not value:
            return value

        result = value
        if self.protect_secrets:
            for secret in self.exact_secrets:
                count = result.count(secret)
                if count:
                    result = result.replace(
                        secret,
                        "[REDACTED:configured-secret]",
                    )
                    self.matches += count
                    self.secret_matches += count
                    self.categories.add("configured-secret")
                    self.secret_categories.add("configured-secret")

            for category, pattern, replacement in _PATTERNS:
                result, count = pattern.subn(replacement, result)
                if count:
                    self.matches += count
                    self.secret_matches += count
                    self.categories.add(category)
                    self.secret_categories.add(category)

        if self.pii_policy != "off":
            result = self._mask_pii(result)
        return result

    def _mask_pii(self, value: str) -> str:
        result = _EMAIL_PATTERN.sub(
            lambda match: self._pseudonym(
                "email",
                match.group(0),
                match.group(0).casefold(),
            ),
            value,
        )
        result = _PAYMENT_CARD_PATTERN.sub(self._mask_payment_card, result)
        result = _IPV4_PATTERN.sub(self._mask_ip_address, result)
        if self.pii_policy == "strict":
            result = _STRICT_FIELD_PATTERN.sub(self._mask_strict_field, result)
        result = _PHONE_PATTERN.sub(self._mask_phone, result)
        return result

    def _mask_payment_card(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = "".join(character for character in raw if character.isdigit())
        if not 13 <= len(digits) <= 19 or not _passes_luhn(digits):
            return raw
        return self._pseudonym("card", raw, digits)

    def _mask_ip_address(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return raw
        if self.pii_policy == "standard":
            if not address.is_global or not _has_ip_context(match):
                return raw
        return self._pseudonym("ip", raw, address.compressed)

    def _mask_phone(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        if not raw.startswith("+") and not re.search(r"[ ().-]", raw):
            return raw
        stripped = raw.strip()
        is_north_american = (
            re.fullmatch(
                r"(?:\([2-9]\d{2}\)|[2-9]\d{2})[ .-]\d{3}[ .-]\d{4}",
                stripped,
            )
            is not None
        )
        if not (
            stripped.startswith("+") or stripped.startswith("0") or is_north_american
        ):
            return raw
        try:
            ipaddress.ip_address(raw)
        except ValueError:
            pass
        else:
            return raw
        digits = "".join(character for character in raw if character.isdigit())
        if not 9 <= len(digits) <= 15:
            return raw
        # Long digit strings that pass Luhn were already handled as cards.
        if 13 <= len(digits) <= 19 and _passes_luhn(digits):
            return raw
        return self._pseudonym("phone", raw, digits)

    def _mask_strict_field(self, match: re.Match[str]) -> str:
        key = match.group("key").lower().replace("-", "_")
        raw = match.group("value")
        if "name" in key:
            category = "name"
        elif "address" in key:
            category = "address"
        else:
            category = "id"
        protected = self._pseudonym(
            category,
            raw,
            re.sub(r"\s+", " ", raw).strip().casefold(),
        )
        quote = match.group("quote")
        return f"{match.group(1)}{quote}{protected}{quote}"

    def _pseudonym(self, category: str, raw: str, normalized: str) -> str:
        key = (category, normalized)
        alias = self._pii_aliases.get(key)
        if alias is None:
            index = self._pii_counts.get(category, 0) + 1
            self._pii_counts[category] = index
            alias = f"[{category.upper()}_{index}]"
            self._pii_aliases[key] = alias
        self.matches += 1
        self.pii_matches += 1
        self.categories.add(category)
        return alias

    def report(self) -> RedactionReport:
        return RedactionReport(
            matches=self.matches,
            secret_matches=self.secret_matches,
            pii_matches=self.pii_matches,
            categories=tuple(sorted(self.categories)),
            secret_categories=tuple(sorted(self.secret_categories)),
            context=self.context,
        )


def _configured_secret_values() -> tuple[str, ...]:
    """Return high-confidence credential values already present in the process.

    Only names that explicitly look sensitive are considered.  Short values
    are ignored to avoid masking ordinary words and IDs throughout prompts.
    """

    candidates: list[tuple[str, object]] = list(os.environ.items())
    try:
        from app.core.config import settings

        env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
        if env_file.is_file():
            candidates.extend(dotenv_values(env_file).items())
        candidates.extend(
            (name, getattr(settings, name, None))
            for name in type(settings).model_fields
            if _SENSITIVE_ENV_NAME.search(name)
        )
    except (OSError, ValueError):
        # Environment-backed values still provide useful protection if the
        # saved provider credential file is temporarily unreadable.
        pass

    values: set[str] = set()
    for name, raw_value in candidates:
        if not _SENSITIVE_ENV_NAME.search(name) or raw_value is None:
            continue
        reveal = getattr(raw_value, "get_secret_value", None)
        value = reveal() if callable(reveal) else raw_value
        if not isinstance(value, str):
            continue
        secret_value: str = value
        if 8 <= len(secret_value) <= 16384 and not secret_value.isspace():
            values.add(secret_value)
    return tuple(sorted(values, key=lambda item: len(item), reverse=True))


def load_outbound_data_policy() -> OutboundDataPolicy:
    """Load the saved policy, defaulting securely if the file is unusable."""

    try:
        from app.agent.sandbox import get_sandbox

        active = get_sandbox()
        value = getattr(active, "outbound_data_policy", None)
        if value in {"block", "redact", "off"}:
            return value
    except Exception as exc:  # noqa: BLE001 - policy lookup must fail closed
        logger.warning("active_outbound_policy_lookup_failed err={}", exc)

    try:
        from app.agent.sandbox_config import load_config

        return load_config().outbound_data_policy
    except (OSError, ValueError) as exc:
        logger.warning("outbound_data_policy_load_failed fallback=block err={}", exc)
        return "block"


def load_outbound_pii_policy() -> OutboundPiiPolicy:
    """Load the saved PII policy, defaulting to standard protection."""

    try:
        from app.agent.sandbox import get_sandbox

        active = get_sandbox()
        value = getattr(active, "outbound_pii_policy", None)
        if value in {"off", "standard", "strict"}:
            return value
    except Exception as exc:  # noqa: BLE001 - policy lookup must fail closed
        logger.warning("active_outbound_pii_policy_lookup_failed err={}", exc)

    try:
        from app.agent.sandbox_config import load_config

        return load_config().outbound_pii_policy
    except (OSError, ValueError) as exc:
        logger.warning("outbound_pii_policy_load_failed fallback=standard err={}", exc)
        return "standard"


def _raise_if_blocked(report: RedactionReport, *, policy: OutboundDataPolicy) -> None:
    """Block secrets while allowing the separate PII policy to pseudonymize."""

    if policy != "block" or not report.secret_matches:
        return
    categories = ", ".join(report.secret_categories)
    if report.context and report.context.channel == "model":
        prefix = "Blocked model request"
        context = f" for {report.context.destination or 'external'}"
    else:
        prefix = "Blocked outbound request"
        context = f" for {report.context.label}" if report.context else ""
    raise OutboundSensitiveDataError(
        f"{prefix}{context} because sensitive-data protection detected "
        f"{report.secret_matches} secret match(es): {categories}. Remove the sensitive value "
        "or switch the Sandbox outbound policy to Redact."
    )


def protect_outbound_text(
    value: str,
    *,
    policy: OutboundDataPolicy | None = None,
    pii_policy: OutboundPiiPolicy | None = None,
    context: OutboundContext | None = None,
) -> tuple[str, RedactionReport]:
    """Protect one string before sending it to a third-party endpoint.

    This is the scalar counterpart to :func:`protect_outbound_payload` for
    web queries, URLs, and MCP arguments. It uses the active session sandbox's
    policy when the caller does not supply one, keeping Work and Coding runs
    scoped to the same per-run security context as shell tools.
    """
    if policy is None:
        policy = load_outbound_data_policy()
    if pii_policy is None:
        pii_policy = load_outbound_pii_policy()
    if policy == "off" and pii_policy == "off":
        return value, RedactionReport(context=context)

    redactor = _Redactor(
        protect_secrets=policy != "off",
        pii_policy=pii_policy,
        context=context,
    )
    protected = redactor.text(value) or ""
    report = redactor.report()
    _raise_if_blocked(report, policy=policy)
    return protected, report


def protect_outbound_value(
    value: object,
    *,
    policy: OutboundDataPolicy | None = None,
    pii_policy: OutboundPiiPolicy | None = None,
    context: OutboundContext | None = None,
) -> tuple[object, RedactionReport]:
    """Recursively protect JSON-like values sent to an external tool.

    MCP arguments are structured rather than a chat transcript. Traversing
    the complete value prevents a secret hidden in a nested object or list
    from bypassing the provider-boundary redactor.
    """
    if policy is None:
        policy = load_outbound_data_policy()
    if pii_policy is None:
        pii_policy = load_outbound_pii_policy()
    if policy == "off" and pii_policy == "off":
        return value, RedactionReport(context=context)

    redactor = _Redactor(
        protect_secrets=policy != "off",
        pii_policy=pii_policy,
        context=context,
    )

    def walk(item: object) -> object:
        if isinstance(item, str):
            return redactor.text(item)
        if isinstance(item, dict):
            protected: dict[object, object] = {}
            for key, child in item.items():
                protected_key = redactor.text(key) if isinstance(key, str) else key
                protected[protected_key] = walk(child)
            return protected
        if isinstance(item, list):
            return [walk(child) for child in item]
        if isinstance(item, tuple):
            return tuple(walk(child) for child in item)
        return item

    protected = walk(value)
    report = redactor.report()
    _raise_if_blocked(report, policy=policy)
    return protected, report


def protect_outbound_payload(
    *,
    system_prompt: str,
    messages: list[ChatMessage],
    policy: OutboundDataPolicy,
    pii_policy: OutboundPiiPolicy = "off",
    context: OutboundContext | None = None,
) -> tuple[str, list[ChatMessage], RedactionReport]:
    """Return a provider-only protected copy of text-bearing payload fields."""

    if policy == "off" and pii_policy == "off":
        return system_prompt, messages, RedactionReport(context=context)

    redactor = _Redactor(
        protect_secrets=policy != "off",
        pii_policy=pii_policy,
        context=context,
    )
    protected_prompt = redactor.text(system_prompt) or ""
    protected_messages = [_protect_message(message, redactor) for message in messages]
    report = redactor.report()

    if not report.matches:
        return system_prompt, messages, report

    _raise_if_blocked(report, policy=policy)

    return protected_prompt, protected_messages, report


def _passes_luhn(digits: str) -> bool:
    checksum = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        value = int(character)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        checksum += value
    return checksum % 10 == 0


def _has_ip_context(match: re.Match[str]) -> bool:
    prefix = match.string[max(0, match.start() - 48) : match.start()]
    return (
        re.search(
            r"(?:\b(?:ip|host|server|client|remote)"
            r"(?:\s+address)?\s*(?:is|=|:)?\s*|https?://)$",
            prefix,
            re.IGNORECASE,
        )
        is not None
    )


def _protect_message(message: ChatMessage, redactor: _Redactor) -> ChatMessage:
    updates: dict[str, object] = {"content": redactor.text(message.content)}

    if isinstance(message, (HumanMessage, ToolMessage)) and message.parts:
        updates["parts"] = [
            (
                part.model_copy(update={"text": redactor.text(part.text) or ""})
                if isinstance(part, TextBlock)
                else part.model_copy(update={"url": redactor.text(part.url) or ""})
                if isinstance(part, ImageUrlBlock)
                else part
            )
            for part in message.parts
        ]

    if isinstance(message, AssistantMessage) and message.tool_calls:
        updates["tool_calls"] = [
            tool_call.model_copy(
                update={
                    "function": tool_call.function.model_copy(
                        update={
                            "arguments": redactor.text(tool_call.function.arguments)
                            or ""
                        }
                    )
                }
            )
            for tool_call in message.tool_calls
        ]

    return message.model_copy(update=updates)
