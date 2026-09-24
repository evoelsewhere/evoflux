"""Compatibility wrapper for the shared remote redaction boundary."""

from __future__ import annotations

from app.remote.redaction import redact_remote_text


def redact(text: str) -> str:
    return redact_remote_text(text)


__all__ = ["redact"]
