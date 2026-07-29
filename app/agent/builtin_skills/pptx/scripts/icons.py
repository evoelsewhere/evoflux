"""Curated, themeable vector icons for EvoFlux PowerPoint generation.

The catalog vendors a deliberately small Lucide subset instead of generating
icons with an image model. Icons are embedded as SVG image parts, stay sharp at
any size, can be recolored before insertion, and can be converted to editable
PowerPoint shapes by modern Microsoft Office.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any, Iterable

from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.parts.image import ImagePart

from app.agent.builtin_skills.pptx.scripts.stylekit import LayoutGuard

CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "icons" / "lucide-1.16.0.json"
)
ICON_FAMILY = "lucide"
ICON_LICENSE = "ISC"
ICON_SOURCE = "https://lucide.dev/"
_HEX_COLOR = re.compile(r"^[0-9a-fA-F]{6}$")

_ALIASES = {
    "agent": "bot",
    "alert": "triangle-alert",
    "alert-circle": "circle-alert",
    "analytics": "chart-line",
    "api": "code-xml",
    "box": "package",
    "box-select": "panels-top-left",
    "briefcase": "briefcase-business",
    "cards": "panels-top-left",
    "circle-check": "badge-check",
    "code": "code-xml",
    "cog": "settings-2",
    "filter": "funnel",
    "globe": "earth",
    "grid": "panels-top-left",
    "growth": "trending-up",
    "help": "circle-question-mark",
    "layout-grid": "panels-top-left",
    "money": "circle-dollar-sign",
    "puzzle-piece": "link-2",
    "question": "circle-question-mark",
    "settings": "settings-2",
    "stack": "package",
    "upload": "cloud-upload",
}

_TAGS = {
    "arrow-right": "next direction flow",
    "badge-check": "verified success trust approval",
    "chart-bar": "analytics metrics report comparison",
    "chart-line": "analytics growth trend performance",
    "chart-pie": "analytics share allocation portfolio",
    "bot": "agent automation assistant ai",
    "brain-circuit": "ai intelligence reasoning model",
    "briefcase-business": "business work enterprise portfolio",
    "building-2": "company enterprise office organization",
    "calendar-days": "schedule date planning roadmap",
    "check": "success done yes approval",
    "circle-alert": "warning risk attention issue",
    "circle-dollar-sign": "money finance revenue cost",
    "circle-question-mark": "help question unknown support",
    "clock": "time speed duration deadline",
    "cloud": "cloud infrastructure platform",
    "cloud-upload": "upload deploy publish cloud",
    "code-xml": "code api developer integration",
    "database": "data storage warehouse memory",
    "earth": "global market geography world",
    "file-text": "document report content file",
    "flag": "milestone goal roadmap priority",
    "funnel": "filter pipeline conversion sales",
    "goal": "objective milestone outcome target",
    "key-round": "access credential key security",
    "laptop": "device software product digital",
    "lightbulb": "idea insight innovation opportunity",
    "link-2": "connection integration relationship link",
    "lock-keyhole": "security privacy access locked",
    "mail": "email message communication contact",
    "map": "map journey geography roadmap",
    "network": "network architecture system hierarchy",
    "package": "package product module delivery",
    "panels-top-left": "layout dashboard interface template",
    "presentation": "slides deck presentation pitch",
    "rocket": "launch speed startup growth",
    "search": "search discover research inspect",
    "settings-2": "settings control configure tune",
    "shield-check": "security compliance protection trust",
    "sparkles": "ai magic quality new highlight",
    "target": "target objective focus goal",
    "trending-up": "growth performance improvement trend",
    "triangle-alert": "warning risk danger issue",
    "users": "people team customers audience",
    "workflow": "workflow process automation pipeline",
    "wrench": "tool build repair operations",
    "zap": "speed energy automation instant",
}


@dataclass(frozen=True)
class IconMatch:
    """One searchable icon-catalog result."""

    name: str
    family: str
    tags: tuple[str, ...]


@lru_cache(maxsize=1)
def _catalog() -> dict[str, list[list[Any]]]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def list_icons() -> tuple[str, ...]:
    """Return every canonical icon name in stable order."""
    return tuple(sorted(_catalog()))


def resolve_icon(name: str) -> str:
    """Resolve a canonical name or supported alias."""
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    canonical = _ALIASES.get(normalized, normalized)
    if canonical not in _catalog():
        matches = [match.name for match in search_icons(normalized, limit=5)]
        if not matches:
            matches = get_close_matches(normalized, list_icons(), n=5, cutoff=0.45)
        suggestions = ", ".join(matches)
        suffix = f"; nearest catalog matches: {suggestions}" if suggestions else ""
        raise KeyError(f"Unknown {ICON_FAMILY} icon {name!r}{suffix}")
    return canonical


def resolve_icons(names: Iterable[str]) -> dict[str, str]:
    """Resolve a set of icon names and report every invalid name together."""
    resolved: dict[str, str] = {}
    errors: list[str] = []
    for name in names:
        try:
            resolved[name] = resolve_icon(name)
        except KeyError as exc:
            errors.append(str(exc.args[0]))
    if errors:
        raise KeyError("Icon preflight failed:\n- " + "\n- ".join(errors))
    return resolved


def search_icons(query: str, *, limit: int = 8) -> list[IconMatch]:
    """Search canonical names, aliases, and semantic tags."""
    tokens = {token for token in re.split(r"[^a-z0-9]+", query.lower()) if token}
    if not tokens:
        return [
            IconMatch(name, ICON_FAMILY, tuple(_TAGS.get(name, "").split()))
            for name in list_icons()[:limit]
        ]

    results: list[tuple[int, str]] = []
    for name in list_icons():
        haystack = {name, *name.split("-"), *_TAGS.get(name, "").split()}
        alias_tokens = {
            alias for alias, canonical in _ALIASES.items() if canonical == name
        }
        score = sum(
            6 if token == name else 4 if token in name else 2
            for token in tokens
            if token in haystack or token in alias_tokens or token in name
        )
        if score:
            results.append((score, name))
    results.sort(key=lambda item: (-item[0], item[1]))
    return [
        IconMatch(name, ICON_FAMILY, tuple(_TAGS.get(name, "").split()))
        for _, name in results[: max(limit, 0)]
    ]


def icon_svg(
    name: str,
    *,
    color: str = "20303C",
    stroke_width: float = 1.8,
) -> bytes:
    """Return a safe, monochrome Lucide SVG for the selected theme color."""
    canonical = resolve_icon(name)
    normalized_color = color.removeprefix("#")
    if not _HEX_COLOR.fullmatch(normalized_color):
        raise ValueError("Icon color must be a six-digit RGB hex value")
    if not 0.75 <= stroke_width <= 3.0:
        raise ValueError("Icon stroke_width must be between 0.75 and 3.0")

    elements: list[str] = []
    for tag, raw_attrs in _catalog()[canonical]:
        attrs = {
            str(key): str(value).replace("currentColor", f"#{normalized_color}")
            for key, value in raw_attrs.items()
        }
        attributes = " ".join(
            f'{escape(key, quote=True)}="{escape(value, quote=True)}"'
            for key, value in attrs.items()
        )
        elements.append(f"<{tag} {attributes}/>")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" '
        f'stroke="#{normalized_color.upper()}" stroke-width="{stroke_width:g}" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{''.join(elements)}</svg>"
    ).encode("utf-8")


def add_icon(
    slide,
    name: str,
    *,
    left,
    top,
    size,
    color: str = "20303C",
    stroke_width: float = 1.8,
    guard: LayoutGuard | None = None,
):
    """Insert one themeable SVG icon as a single, QA-identifiable shape."""
    canonical = resolve_icon(name)
    if int(size) <= 0:
        raise ValueError("Icon size must be positive")
    if guard is not None:
        guard.reserve(
            f"icon:{canonical}",
            left=int(left),
            top=int(top),
            width=int(size),
            height=int(size),
            role="icon",
        )

    blob = icon_svg(canonical, color=color, stroke_width=stroke_width)
    package = slide.part.package
    image_part = ImagePart(
        package.next_image_partname("svg"),
        "image/svg+xml",
        package,
        blob,
        filename=f"{canonical}.svg",
    )
    relationship_id = slide.part.relate_to(image_part, RT.IMAGE)
    shape_id = slide.shapes._next_shape_id  # noqa: SLF001
    picture_element = slide.shapes._grpSp.add_pic(  # noqa: SLF001
        shape_id,
        f"Icon {shape_id}",
        f"{canonical}.svg",
        relationship_id,
        left,
        top,
        size,
        size,
    )
    slide.shapes._recalculate_extents()  # noqa: SLF001
    picture = slide.shapes._shape_factory(picture_element)  # noqa: SLF001
    picture.name = f"[icon:{ICON_FAMILY}:{canonical}]"
    return picture


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument(
        "--check",
        nargs="+",
        metavar="ICON",
        help="validate one or more icon names before building a deck",
    )
    parser.add_argument("--svg", metavar="ICON", help="print one recolorable SVG")
    parser.add_argument("--color", default="20303C")
    args = parser.parse_args()
    if args.check:
        try:
            resolved = resolve_icons(args.check)
        except KeyError as exc:
            print(exc.args[0], file=sys.stderr)
            return 2
        for source, canonical in resolved.items():
            print(f"{source}\t{canonical}")
        return 0
    if args.svg:
        print(icon_svg(args.svg, color=args.color).decode("utf-8"))
        return 0
    matches = search_icons(args.query, limit=args.limit)
    if args.query and not matches:
        print(
            f"No {ICON_FAMILY} icons matched {args.query!r}. "
            "Use --check for exact-name validation.",
            file=sys.stderr,
        )
        return 2
    for match in matches:
        print(f"{match.name}\t{', '.join(match.tags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
