"""Read the build plan a deck carries while an agent generates it.

The ``pptx-official`` Skill's ``scripts/deck_live.py`` creates a deck before
its slides exist and stores the plan (slide count, titles, state) as the
``evoflux.deck`` custom document property. Slides are appended one at a time
and the file is saved after each, so the slides present are the finished
ones; the preview renders skeletons for the rest until the plan says
``done``.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

PLAN_PROPERTY = "evoflux.deck"
_CUSTOM_PART = "docProps/custom.xml"
_CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_MAX_PLAN_BYTES = 64 * 1024
_MAX_SLIDES = 500


@dataclass(frozen=True, slots=True)
class DeckPlan:
    total: int
    titles: tuple[str, ...]
    done: bool

    def title(self, index: int) -> str:
        return self.titles[index] if 0 <= index < len(self.titles) else ""


def read_deck_plan(source: Path) -> DeckPlan | None:
    """Return the live-build plan embedded in ``source``, if it has one."""
    # lxml ships with the optional office-preview extra; import it lazily so
    # the preview service stays importable without it.
    from lxml import etree  # ty: ignore[unresolved-import] - compiled module, no stubs

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        with zipfile.ZipFile(source) as archive:
            info = archive.getinfo(_CUSTOM_PART)
            if info.file_size > _MAX_PLAN_BYTES:
                return None
            root = etree.fromstring(archive.read(info), parser)
    except (KeyError, OSError, zipfile.BadZipFile, etree.XMLSyntaxError):
        return None
    for prop in root.iter(f"{{{_CUSTOM_NS}}}property"):
        if prop.get("name") != PLAN_PROPERTY:
            continue
        text = "".join(prop.itertext()).strip()
        try:
            data = json.loads(text)
            total = int(data["total"])
            titles = tuple(str(title) for title in data.get("titles", []))[:_MAX_SLIDES]
            state = str(data.get("state", "building"))
        except (ValueError, KeyError, TypeError):
            return None
        if not 0 < total <= _MAX_SLIDES:
            return None
        return DeckPlan(total=total, titles=titles, done=state == "done")
    return None


def deck_is_live(source: Path) -> bool:
    """Whether an agent is still building ``source`` slide by slide."""
    if source.suffix.lower() != ".pptx":
        return False
    plan = read_deck_plan(source)
    return plan is not None and not plan.done


__all__ = ["PLAN_PROPERTY", "DeckPlan", "deck_is_live", "read_deck_plan"]
