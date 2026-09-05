"""Structured reading of a rendered document preview.

The renderer already labels its output for inspection: every page, slide, or
sheet carries ``data-preview-item`` with a human label, and every drawn element
carries ``data-qa-label`` plus its geometry as percentages of the page box.
This module is the reader for that contract, and it lives beside the writer on
purpose — the markup and the parse cannot drift into two different truths.

Geometry arrives as percentages, so "does this element sit inside its page" is
a comparison against 0 and 100 rather than against any absolute size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

PREVIEW_ITEM_ATTRIBUTE = "data-preview-item"
PREVIEW_LABEL_ATTRIBUTE = "data-preview-label"
ELEMENT_LABEL_ATTRIBUTE = "data-qa-label"

DEFAULT_MAX_ITEMS = 200
DEFAULT_MAX_ELEMENTS_PER_ITEM = 200
DEFAULT_MAX_TEXT_CHARS = 400

_PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_WHITESPACE = re.compile(r"\s+")


def _percent(style: str, property_name: str) -> float | None:
    match = re.search(rf"(?:^|;)\s*{property_name}\s*:\s*([^;]+)", style)
    if match is None:
        return None
    value = _PERCENT.search(match.group(1))
    return float(value.group(1)) if value else None


@dataclass(frozen=True)
class PreviewElement:
    """One labelled element drawn on a preview item."""

    label: str
    text: str
    left: float | None = None
    top: float | None = None
    width: float | None = None
    height: float | None = None

    @property
    def right(self) -> float | None:
        if self.left is None or self.width is None:
            return None
        return self.left + self.width

    @property
    def bottom(self) -> float | None:
        if self.top is None or self.height is None:
            return None
        return self.top + self.height

    def out_of_bounds(self) -> bool:
        """Whether any edge falls outside the page box."""

        edges = (
            (self.left, "min"),
            (self.top, "min"),
            (self.right, "max"),
            (self.bottom, "max"),
        )
        for value, kind in edges:
            if value is None:
                continue
            if kind == "min" and value < 0:
                return True
            if kind == "max" and value > 100:
                return True
        return False


@dataclass
class PreviewItem:
    """One page, slide, or sheet of a rendered preview."""

    label: str
    elements: list[PreviewElement] = field(default_factory=list)
    elements_truncated: bool = False

    def out_of_bounds(self) -> list[PreviewElement]:
        return [element for element in self.elements if element.out_of_bounds()]

    def text(self) -> str:
        return "\n".join(element.text for element in self.elements if element.text)


@dataclass
class PreviewSummary:
    """Everything the rendered preview says about itself."""

    items: list[PreviewItem] = field(default_factory=list)
    items_truncated: bool = False


class _PreviewReader(HTMLParser):
    def __init__(
        self,
        *,
        max_items: int,
        max_elements: int,
        max_text_chars: int,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._max_items = max_items
        self._max_elements = max_elements
        self._max_text_chars = max_text_chars
        self.summary = PreviewSummary()
        self._item: PreviewItem | None = None
        self._item_depth = 0
        self._element: dict[str, object] | None = None
        self._element_depth = 0
        self._chunks: list[str] = []

    # ── element lifecycle ────────────────────────────────────────────────
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: (value or "") for name, value in attrs}

        if self._item is not None:
            self._item_depth += 1
        if self._element is not None:
            self._element_depth += 1

        if PREVIEW_ITEM_ATTRIBUTE in attributes:
            self._close_item()
            if len(self.summary.items) >= self._max_items:
                self.summary.items_truncated = True
                return
            self._item = PreviewItem(
                label=attributes.get(PREVIEW_LABEL_ATTRIBUTE, "").strip()
                or f"Item {len(self.summary.items) + 1}"
            )
            self._item_depth = 0
            return

        if ELEMENT_LABEL_ATTRIBUTE in attributes and self._element is None:
            if self._item is not None and len(self._item.elements) >= self._max_elements:
                self._item.elements_truncated = True
                return
            style = attributes.get("style", "")
            self._element = {
                "label": attributes[ELEMENT_LABEL_ATTRIBUTE].strip(),
                "left": _percent(style, "left"),
                "top": _percent(style, "top"),
                "width": _percent(style, "width"),
                "height": _percent(style, "height"),
            }
            self._element_depth = 0
            self._chunks = []

    def handle_endtag(self, tag: str) -> None:
        if self._element is not None:
            if self._element_depth == 0:
                self._close_element()
            else:
                self._element_depth -= 1
        if self._item is not None:
            if self._item_depth == 0:
                self._close_item()
            else:
                self._item_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._element is not None:
            self._chunks.append(data)

    # ── collection ───────────────────────────────────────────────────────
    def _close_element(self) -> None:
        if self._element is None:
            return
        text = _WHITESPACE.sub(" ", "".join(self._chunks)).strip()
        if len(text) > self._max_text_chars:
            text = text[: self._max_text_chars].rstrip() + "…"
        element = PreviewElement(
            label=str(self._element["label"]),
            text=text,
            left=self._element["left"],  # type: ignore[arg-type]
            top=self._element["top"],  # type: ignore[arg-type]
            width=self._element["width"],  # type: ignore[arg-type]
            height=self._element["height"],  # type: ignore[arg-type]
        )
        self._element = None
        self._chunks = []
        if self._item is not None and not self._item.elements_truncated:
            self._item.elements.append(element)

    def _close_item(self) -> None:
        self._close_element()
        if self._item is not None:
            self.summary.items.append(self._item)
        self._item = None

    def finish(self) -> PreviewSummary:
        self._close_item()
        return self.summary


def summarize_document_preview(
    preview: Path,
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_elements: int = DEFAULT_MAX_ELEMENTS_PER_ITEM,
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
) -> PreviewSummary:
    """Read a rendered preview into its pages and their labelled elements."""

    reader = _PreviewReader(
        max_items=max_items,
        max_elements=max_elements,
        max_text_chars=max_text_chars,
    )
    reader.feed(preview.read_text(encoding="utf-8", errors="replace"))
    reader.close()
    return reader.finish()


__all__ = [
    "DEFAULT_MAX_ELEMENTS_PER_ITEM",
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_MAX_TEXT_CHARS",
    "ELEMENT_LABEL_ATTRIBUTE",
    "PREVIEW_ITEM_ATTRIBUTE",
    "PREVIEW_LABEL_ATTRIBUTE",
    "PreviewElement",
    "PreviewItem",
    "PreviewSummary",
    "summarize_document_preview",
]
