"""Runtime-owned lifecycle markers for agent messages.

Text sentinels remain accepted at the model boundary for compatibility with
existing prompts and providers, but they are normalized before messages are
persisted or published to clients.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage


SLEEP_LIFECYCLE = "sleep"
SLEEP_SENTINELS = ("<sleep>", "[sleep]")


def extract_sleep_prefix(content: str | None) -> str | None:
    """Return content before a trailing sleep sentinel, or ``None``."""

    trimmed = (content or "").rstrip()
    for sentinel in SLEEP_SENTINELS:
        if trimmed.endswith(sentinel):
            return trimmed[: -len(sentinel)].rstrip()
    return None


def normalize_sleep_message(message: AssistantMessage) -> bool:
    """Move a trailing text sentinel into ``extra.lifecycle`` in-place."""

    prefix = extract_sleep_prefix(message.content)
    if prefix is None:
        return bool(message.extra and message.extra.get("lifecycle") == SLEEP_LIFECYCLE)

    message.content = prefix or None
    message.extra = {**(message.extra or {}), "lifecycle": SLEEP_LIFECYCLE}
    return True


def is_sleep_message(message: object) -> bool:
    """Recognize normalized messages and legacy sentinel-bearing messages."""

    extra = getattr(message, "extra", None)
    if isinstance(extra, dict) and extra.get("lifecycle") == SLEEP_LIFECYCLE:
        return True
    return extract_sleep_prefix(getattr(message, "content", None)) is not None


class SleepSentinelStreamFilter:
    """Withhold only the stream tail that could become a sleep sentinel."""

    def __init__(self) -> None:
        self._pending = ""

    def reset(self) -> None:
        self._pending = ""

    def feed(self, text: str) -> str:
        self._pending += text
        hold_from = self._candidate_suffix_start(self._pending)
        if hold_from is None:
            visible = self._pending
            self._pending = ""
            return visible

        visible = self._pending[:hold_from]
        self._pending = self._pending[hold_from:]
        return visible

    def finish(self) -> tuple[str, bool]:
        prefix = extract_sleep_prefix(self._pending)
        if prefix is not None:
            self._pending = ""
            return prefix, True

        visible = self._pending
        self._pending = ""
        return visible, False

    @staticmethod
    def _candidate_suffix_start(value: str) -> int | None:
        for index in range(len(value)):
            suffix = value[index:]
            if any(sentinel.startswith(suffix) for sentinel in SLEEP_SENTINELS):
                return index
            if any(
                suffix.startswith(sentinel) and suffix[len(sentinel) :].isspace()
                for sentinel in SLEEP_SENTINELS
            ):
                return index
        return None
