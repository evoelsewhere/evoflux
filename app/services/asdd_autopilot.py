"""Carrying an ASDD change from one phase to the next, without a click.

`autopilot: true` on a change meant one thing and read as another. It let an
agent clear a gate on its own judgment — write `auto_approvals.specs`, move
`status` on — and then the turn ended, because that is what every phase Skill
says to do. The rail put a **Continue** button up and waited. Autopilot
approved; a person still drove every hop.

This module is the driver. At a turn boundary it asks the same question the
rail's Continue button asks — *what phase does autopilot run next?* — and
answers it by starting that phase instead of rendering a button.

Everything that decides whether a hop is allowed already exists and is reused
verbatim: :func:`app.services.asdd_service.prepare_action` resolves
`autopilot_continue` through the rail, which refuses when autopilot is off,
when a `hold` is raised, when the phase is not offered at this status, and
when a blocker stands. A refusal is the loop's stop condition, not an error to
route around.

Two bounds of its own:

- **Progress.** A hop that leaves the change exactly where it was does not get
  another one. Without this a change that cannot advance would re-run its
  phase every turn, which is the compaction failure with a different name.
- **Hops.** A chain is capped, so a change that oscillates costs a bounded
  number of turns rather than a night.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.services.asdd_service import (
    AsddActionBlocked,
    catalogue_for,
    prepare_action,
)
from app.services.asdd_setup_service import ASDD_MANIFEST
from app.services.asdd_store import AsddStoreError

#: How many phases autopilot may run before it hands the turn back. A full
#: cycle is propose → specify → (design) → tasks → implement → verify, and
#: implementation re-enters itself while tasks remain, so the cap is generous
#: enough for a real change and small enough to bound a mistake.
MAX_CHAIN_HOPS = 12

#: The change a phase prompt names, as `action_prompt` writes it:
#: ``Work on ASDD change `add-note-search` — “…”``. Parsing our own sentence
#: is what lets the driver bind a session to a change without a second
#: identifier: the prompt is already in the transcript, and rule 2 forbids
#: minting an id to carry alongside it.
_CHANGE_IN_PROMPT = re.compile(r"ASDD change `([a-z0-9][a-z0-9-]*)`")


@dataclass(frozen=True)
class AutopilotHop:
    """The next phase to run, and the state it is running from."""

    change_id: str
    action: str
    skill: str
    prompt: str
    #: What "no progress" means for this change. Compared against the previous
    #: hop's value to decide whether the last turn moved anything.
    progress: tuple[str, int, int]


def stop_reason(
    hops: int, previous: tuple[str, int, int] | None, hop: "AutopilotHop"
) -> str | None:
    """Why this chain should stop before running *hop*, or ``None`` to run it.

    The rail already said the phase is allowed; these are the loop's own two
    bounds, kept here so they can be reasoned about without a running team.
    """

    if hops >= MAX_CHAIN_HOPS:
        return "chain_capped"
    if previous is not None and hop.progress == previous:
        # The last hop ran and left the change exactly where it was. Another
        # one would do the same thing for the same reason.
        return "no_progress"
    return None


def change_id_in(text: str | None) -> str | None:
    """The change a phase prompt names, or ``None`` when it names none."""

    if not text:
        return None
    match = _CHANGE_IN_PROMPT.search(text)
    return match.group(1) if match else None


def next_hop(workspace: str | Path, change_id: str) -> AutopilotHop | None:
    """The phase autopilot runs next for *change_id*, or ``None`` to stop.

    ``None`` is the ordinary outcome, not a failure: autopilot is off, a hold
    is up, the change is `ready` and waiting for a person to archive it, or
    the rail refuses the next phase because a blocker stands.
    """

    root = Path(workspace).expanduser()
    if not (root / ASDD_MANIFEST).is_file():
        return None

    try:
        catalogue = catalogue_for(root)
        record, prompt, skill = prepare_action(
            catalogue, change_id, "autopilot_continue"
        )
    except AsddActionBlocked as exc:
        logger.debug(
            "asdd_autopilot_stop change_id={} reason={}", change_id, exc
        )
        return None
    except (AsddStoreError, OSError, ValueError) as exc:
        logger.warning(
            "asdd_autopilot_unreadable change_id={} error={}", change_id, exc
        )
        return None

    artifacts = record.artifacts
    return AutopilotHop(
        change_id=record.change_id,
        action="autopilot_continue",
        skill=skill,
        prompt=prompt,
        progress=(artifacts.status, artifacts.tasks_done, len(artifacts.evidence_ids)),
    )
