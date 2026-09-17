"""Markdown documents with YAML front matter — the ASDD storage primitive.

Every ASDD artifact is a Markdown file whose front matter carries its state.
There is no database row behind it, no content hash to keep in step and no
session that owns it: a reader resolves what a change is by reading the page,
and `git diff` shows a state transition the same way it shows a prose edit.

That makes two properties load-bearing. Parsing must be forgiving, because the
file is meant to be edited by hand and a malformed page should make one change
unreadable rather than take down the catalogue. Rendering must be
deterministic, because a write that reorders keys turns every save into a diff
and destroys the reviewability the format exists for.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import yaml

_FENCE = "---"


def scalar_text(value: Any) -> str | None:
    """Render one front-matter scalar as the text the page meant to say.

    YAML types values it recognizes, so an unquoted `recorded: 2026-09-17T07:35:00Z`
    arrives as a `datetime` and an unquoted `id: 2` as an `int`. Refusing those
    would make correctness depend on whether whoever wrote the page happened to
    quote it — a trap for exactly the hand-editing this format invites. Read the
    value the writer wrote, and keep timestamps in the ISO-8601 `Z` form the rest
    of the catalogue uses so a hand-written page and a machine-written one sort
    and compare alike.
    """

    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime):
        moment = (
            value.astimezone(dt.timezone.utc)
            if value.tzinfo is not None
            else value.replace(tzinfo=dt.timezone.utc)
        )
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, dt.date):
        return value.isoformat()
    text = value if isinstance(value, str) else str(value)
    return text.strip() or None


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    """One parsed artifact: its front matter and the Markdown beneath it."""

    front_matter: dict[str, Any]
    body: str

    def get(self, key: str, default: Any = None) -> Any:
        return self.front_matter.get(key, default)

    def text(self) -> str:
        return render_document(self.front_matter, self.body)


class AsddDocumentError(ValueError):
    """A page exists but cannot be read as an ASDD artifact."""


def parse_document(text: str) -> MarkdownDocument:
    """Split a page into front matter and body.

    A page without front matter is not an error: `design.md` and `tasks.md` are
    ordinary prose for most changes, and only `proposal.md` is required to
    declare state. Callers that need a field ask for it and report its absence
    themselves, with a message naming the file.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith(f"{_FENCE}\n"):
        return MarkdownDocument(front_matter={}, body=normalized.lstrip("\n"))
    closing = normalized.find(f"\n{_FENCE}", len(_FENCE))
    if closing < 0:
        return MarkdownDocument(front_matter={}, body=normalized.lstrip("\n"))
    raw = normalized[len(_FENCE) + 1 : closing]
    rest = normalized[closing + len(_FENCE) + 1 :]
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AsddDocumentError(f"front matter is not valid YAML: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise AsddDocumentError("front matter must be a mapping")
    return MarkdownDocument(front_matter=loaded, body=rest.lstrip("\n"))


def render_document(front_matter: dict[str, Any], body: str) -> str:
    """Render a page, preserving the caller's key order verbatim.

    `sort_keys=False` is the point: the field order is part of the contract each
    artifact module declares, so a proposal always reads `change`, `title`,
    `status` and never reshuffles between writes.
    """

    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not front_matter:
        return f"{normalized_body}\n" if normalized_body else ""
    rendered = yaml.safe_dump(
        front_matter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    ).rstrip("\n")
    return (
        "\n".join([_FENCE, rendered, _FENCE, "", normalized_body]).rstrip("\n") + "\n"
    )


def require_str(document: MarkdownDocument, key: str, *, source: str) -> str:
    text = scalar_text(document.front_matter.get(key))
    if text is None:
        raise AsddDocumentError(f"{source}: front matter is missing `{key}`")
    return text


def optional_str(document: MarkdownDocument, key: str) -> str | None:
    return scalar_text(document.front_matter.get(key))


def string_list(document: MarkdownDocument, key: str) -> list[str]:
    """Return a list-valued field, tolerating a single scalar.

    Hand-edited front matter writes `capabilities: user-auth` as often as it
    writes a list, and rejecting the scalar form would fail a page whose meaning
    is unambiguous.
    """

    value = document.front_matter.get(key)
    if not isinstance(value, list):
        text = scalar_text(value)
        return [text] if text else []
    return [text for text in map(scalar_text, value) if text]


__all__ = [
    "AsddDocumentError",
    "MarkdownDocument",
    "optional_str",
    "parse_document",
    "render_document",
    "require_str",
    "scalar_text",
    "string_list",
]
