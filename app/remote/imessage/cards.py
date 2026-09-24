"""Provider-neutral card projection for text-first iMessage clients."""

from __future__ import annotations

from collections.abc import Sequence

from app.remote.contracts import RemoteButton


def render_card(text: str, buttons: Sequence[RemoteButton]) -> str:
    """Render generic remote buttons as stable numbered text actions."""
    if not buttons:
        return text
    lines = [text.rstrip(), "", "Reply with a number:"]
    lines.extend(f"{index}. {button.text}" for index, button in enumerate(buttons, 1))
    return "\n".join(lines)
