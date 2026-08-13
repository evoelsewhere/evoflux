"""Native provider entrypoints for the trusted Documents plugin."""

from __future__ import annotations


def preview_provider() -> object:
    from app.agent.builtin_plugins.documents.preview import document_preview_provider

    return document_preview_provider


__all__ = ["preview_provider"]
