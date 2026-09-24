"""Read the build plan a deck carries while an agent generates it.

The ``pptx-official`` Skill's ``scripts/deck_live.py`` creates a deck before
its slides exist and stores the plan (slide count, state) as the
``evoflux.deck`` custom document property. Slides are appended one at a time
and the file is saved after each, so the slides present are the finished
ones; the preview renders skeletons for the rest until the plan says
``done``. The plan names the building session (``EVOFLUX_SESSION`` in the
agent's shell): only that session sees the build live, and only while its
turn runs, so another session editing the same file, or an abandoned build,
shows a plain deck.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterable
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
    done: bool
    # The EvoFlux session whose agent is building the deck, when known.
    session: str | None = None

    def live_for(self, session_id: str | None) -> bool:
        """Whether ``session_id`` (a session whose turn is running) builds it.

        A deck is shown under construction only to the session building it,
        and only while that session's agent is working; everyone else — and
        that session once its turn ends — sees the slides that exist. A plan
        written before sessions were recorded belongs to any running session.
        """
        if self.done or not session_id:
            return False
        return self.session is None or self.session == session_id


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
            state = str(data.get("state", "building"))
            session = data.get("session")
        except (ValueError, KeyError, TypeError, AttributeError):
            return None
        if not 0 < total <= _MAX_SLIDES:
            return None
        return DeckPlan(
            total=total,
            done=state == "done",
            session=str(session)[:64] if session else None,
        )
    return None


def deck_is_live(source: Path, session_id: str | None) -> bool:
    """Whether ``session_id``'s running turn is building ``source`` slide by slide."""
    if source.suffix.lower() != ".pptx":
        return False
    plan = read_deck_plan(source)
    return plan is not None and plan.live_for(session_id)


def deck_is_live_for_any(source: Path, session_ids: Iterable[str]) -> bool:
    """Whether any of ``session_ids`` (running sessions) is building ``source``."""
    if source.suffix.lower() != ".pptx":
        return False
    plan = read_deck_plan(source)
    return plan is not None and any(plan.live_for(sid) for sid in session_ids)


__all__ = [
    "PLAN_PROPERTY",
    "DeckPlan",
    "deck_is_live",
    "deck_is_live_for_any",
    "read_deck_plan",
]
