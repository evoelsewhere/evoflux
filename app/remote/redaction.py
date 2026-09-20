"""Shared outbound redaction boundary for remote transports."""

from __future__ import annotations

from app.agent.outbound_redaction import OutboundContext, protect_outbound_text


def redact_remote_text(text: str) -> str:
    """Protect remote-bound text without making decoration fail a turn."""
    try:
        protected, _report = protect_outbound_text(
            text,
            context=OutboundContext(channel="remote"),
        )
        return protected
    except Exception:
        return text


__all__ = ["redact_remote_text"]
