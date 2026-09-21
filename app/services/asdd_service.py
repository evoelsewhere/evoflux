"""Orchestration between the ASDD catalogue on disk and the API.

Everything here is a pure function of the repository plus one write. There is no
cached projection to invalidate and no row whose staleness has to be defended,
so a panel that reloads always sees exactly what a reviewer would see in the
working tree.

The one piece of judgment that lives here rather than in the store is the phase
prompt: it names the Skill, the change folder and the artifact the agent is
expected to produce, and it is built from the change's own state so an agent
never has to be told which run, revision or hash it is working on.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from app.services.asdd_document import scalar_text
from app.services.asdd_lifecycle import (
    APPROVAL_ARTIFACTS,
    AUTOPILOT_HUMAN_ONLY,
    TERMINAL_STATUSES,
    ChangeArtifacts,
    action_rail,
    archive_blockers,
    artifact_blockers,
)
from app.services.asdd_setup_service import resolve_data_directory
from app.services.asdd_store import (
    AsddCatalogue,
    AsddStoreError,
    ChangeRecord,
    normalize_slug,
    slugify,
)


class AsddActionBlocked(AsddStoreError):
    """The requested action is not available in the change's current state."""

    def __init__(self, message: str, blockers: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.blockers = blockers


#: Which Skill carries out each rail action, and what it is expected to leave
#: behind. `archive` is a report rather than an edit: the fold itself is a
#: server operation, because it rewrites the catalogue and must be atomic.
_PHASE_SKILLS: dict[str, tuple[str, str]] = {
    "draft_proposal": ("asdd-propose", "proposal.md"),
    "draft_specs": ("asdd-specify", "specs/<capability>/spec.md"),
    "draft_design": ("asdd-plan", "design.md"),
    "draft_tasks": ("asdd-plan", "tasks.md"),
    "start_implementation": ("asdd-implement", "the approved tasks"),
    "start_verification": ("asdd-verify", "evidence/<id>.md"),
    "check_archive": ("asdd-archive", "an archive readiness report"),
}


def _autopilot_next(artifacts: ChangeArtifacts) -> str | None:
    """The phase autopilot runs next, from wherever the change is standing.

    `specified` forks on the risk tier for the same reason
    `status_after_approval` does: a tier that owes a design goes to the design,
    everything else goes straight to planning. `implementing` forks on the work
    itself — unchecked tasks mean the implementation phase is not finished, and
    handing the change to verification early would only produce evidence for
    something that is not built yet.
    """

    if artifacts.status == "proposed":
        return "draft_specs"
    if artifacts.status == "specified":
        return "draft_design" if artifacts.design_required else "draft_tasks"
    if artifacts.status == "designed":
        return "draft_tasks"
    if artifacts.status == "tasked":
        return "start_implementation"
    if artifacts.status == "implementing":
        remaining = artifacts.tasks_total - artifacts.tasks_done
        return "start_implementation" if remaining > 0 else "start_verification"
    if artifacts.status == "verifying":
        return "start_verification"
    return None


def catalogue_for(workspace: str | Path) -> AsddCatalogue:
    root = Path(workspace).expanduser().resolve()
    return AsddCatalogue.create(root, resolve_data_directory(root))


def change_payload(catalogue: AsddCatalogue, record: ChangeRecord) -> dict[str, Any]:
    artifacts = record.artifacts
    return {
        "change_id": record.change_id,
        "repository": str(catalogue.root),
        "title": artifacts.title,
        "status": artifacts.status,
        "risk": artifacts.risk,
        "capabilities": artifacts.capabilities,
        "delta_capabilities": artifacts.delta_capabilities,
        "approvals": artifacts.approvals,
        "auto_approvals": artifacts.auto_approvals,
        "autopilot": artifacts.autopilot,
        "hold": dict(artifacts.hold) if artifacts.hold else None,
        "tasks_total": artifacts.tasks_total,
        "tasks_done": artifacts.tasks_done,
        "evidence_count": len(artifacts.evidence_ids),
        "review_recorded": artifacts.review_recorded,
        "created": record.created,
        "path": catalogue.relative(record.path),
    }


def detail_payload(catalogue: AsddCatalogue, record: ChangeRecord) -> dict[str, Any]:
    return {
        "change": change_payload(catalogue, record),
        "rail": action_rail(record.artifacts),
        "proposal": record.proposal_body,
        "design": record.design_body,
        "tasks": record.tasks_body,
        "deltas": [
            {
                "capability": item.capability,
                "added": [requirement.name for requirement in item.delta.added],
                "modified": [requirement.name for requirement in item.delta.modified],
                "removed": list(item.delta.removed),
                "problems": item.problems,
                "body": item.body,
            }
            for item in record.deltas
        ],
        "evidence": [
            {
                "id": scalar_text(document.get("id")) or "",
                "kind": scalar_text(document.get("kind")) or "machine",
                "result": scalar_text(document.get("result")) or "inconclusive",
                "requirement": scalar_text(document.get("requirement")),
                "recorded": scalar_text(document.get("recorded")),
                "summary": document.body.split("\n\n", 1)[0].strip(),
            }
            for document in record.evidence
        ],
    }


def list_changes(catalogue: AsddCatalogue) -> dict[str, Any]:
    """List every open change, skipping any folder that cannot be read.

    One corrupt `proposal.md` must not blank the panel: the broken change is
    logged and omitted, and opening it directly still reports exactly what is
    wrong with it.
    """

    changes: list[dict[str, Any]] = []
    for change_id in catalogue.list_change_ids():
        try:
            changes.append(change_payload(catalogue, catalogue.read_change(change_id)))
        except AsddStoreError as exc:
            logger.warning(
                "asdd_change_unreadable change_id={} error={}", change_id, exc
            )
    return {
        "workspace": str(catalogue.root),
        "changes": changes,
        "archived": catalogue.list_archived(),
        "capabilities": catalogue.list_capabilities(),
    }


def list_changes_across(roots: "Sequence[str]", *, workspace: str) -> dict[str, Any]:
    """Every change in *roots*, as one listing.

    A Coding project is several repositories and a change lives in exactly one
    of them, so listing only the repository a session happened to open on
    reports an empty board to someone whose changes are all next door. Each
    change already names its own repository, so the merge needs no key of its
    own — and a repository with no ASDD directory contributes nothing rather
    than failing the listing, which is what lets a half-installed project show
    the changes it does have.

    Order follows *roots*, which is the project's own repository order; within
    a repository the catalogue's own ordering stands.
    """
    changes: list[dict[str, Any]] = []
    archived: list[str] = []
    capabilities: set[str] = set()
    repositories: list[dict[str, Any]] = []
    for root in roots:
        payload = list_changes(catalogue_for(root))
        changes.extend(payload["changes"])
        archived.extend(payload["archived"])
        capabilities.update(payload["capabilities"])
        # Kept per repository as well as merged: a capability's spec and an
        # archived change live in exactly one working tree, so a reader that
        # only had the merged names would ask the wrong repository for them.
        repositories.append(
            {
                "path": payload["workspace"],
                "capabilities": payload["capabilities"],
                "archived": payload["archived"],
            }
        )
    return {
        "workspace": workspace,
        "changes": changes,
        # Archive names carry their own date prefix, so newest-first across
        # repositories is the same sort the single-repository listing uses.
        "archived": sorted(set(archived), reverse=True),
        "capabilities": sorted(capabilities),
        "repositories": repositories,
    }


def derive_change_id(title: str, *, taken: set[str]) -> str:
    """Return a free slug for a new change, derived from its title.

    Derived rather than random: the slug is what everyone will type, so it has
    to come from something the user already said. A collision gets a numeric
    suffix, which is the only place in ASDD where a name is not purely the
    author's choice.
    """

    base = slugify(title, label="title")
    if base not in taken:
        return base
    for index in range(2, 100):
        candidate = f"{base}-{index}"
        if candidate not in taken:
            return candidate
    raise AsddStoreError(f"Too many changes already named like '{base}'")


def create_change(
    catalogue: AsddCatalogue,
    *,
    title: str,
    change_id: str | None = None,
    risk: str | None = None,
    capabilities: list[str] | None = None,
    problem: str = "",
    outcome: str = "",
) -> ChangeRecord:
    taken = set(catalogue.list_change_ids()) | catalogue.archived_change_ids()
    slug = (
        normalize_slug(change_id, label="change id")
        if change_id
        else derive_change_id(title, taken=taken)
    )
    catalogue.create_change(
        change_id=slug, title=title, risk=risk, capabilities=capabilities
    )
    catalogue.seed_request(slug, problem=problem, outcome=outcome)
    return catalogue.read_change(slug)


def approve(
    catalogue: AsddCatalogue, change_id: str, artifact: str, *, note: str | None = None
) -> ChangeRecord:
    """Record a human approval, refusing one the files do not support."""

    if artifact not in APPROVAL_ARTIFACTS:
        raise AsddStoreError(f"Unknown ASDD approval artifact: {artifact}")
    record = catalogue.read_change(change_id)
    blockers = artifact_blockers(record.artifacts, artifact)
    if blockers:
        raise AsddActionBlocked(
            f"{artifact} cannot be approved yet: {blockers[0]['message']}", blockers
        )
    approved = catalogue.approve(change_id, artifact, note=note)
    return approved


def action_prompt(catalogue: AsddCatalogue, record: ChangeRecord, action: str) -> str:
    """Return the instruction that runs one phase in a Coding chat."""

    skill, produces = _PHASE_SKILLS[action]
    folder = catalogue.relative(record.path)
    lines = [
        f"${skill}",
        "",
        f"Work on ASDD change `{record.change_id}` — “{record.artifacts.title}”.",
        f"Its folder is `{folder}`; the capability catalogue is "
        f"`{catalogue.relative(catalogue.specs_path)}`.",
        f"Risk tier is `{record.artifacts.risk}`. "
        f"Declared status is `{record.artifacts.status}`.",
        f"Produce: {produces}.",
    ]
    if record.artifacts.capabilities:
        lines.append(
            "Capabilities named by the proposal: "
            + ", ".join(f"`{item}`" for item in record.artifacts.capabilities)
            + "."
        )
    if action == "start_implementation":
        remaining = record.artifacts.tasks_total - record.artifacts.tasks_done
        lines.append(
            f"{remaining} of {record.artifacts.tasks_total} tasks remain unchecked."
        )
    lines.append(
        "Read the change folder before acting; it is the only source of truth for "
        "this change."
    )
    lines.extend(_autopilot_instructions(record.artifacts))
    return "\n".join(lines)


def _autopilot_instructions(artifacts: ChangeArtifacts) -> list[str]:
    """Say who clears the next gate, and how the agent records it.

    Without autopilot this is the rule the method has always had. With it on,
    the agent needs an honest channel: it may pass a gate on its own judgment,
    but it records that in `auto_approvals`, never in `approvals`. The two are
    separate so the repository never claims a person read something no person
    read — and so an agent that needs to move has somewhere legitimate to write
    instead of forging the signature it is told not to touch.
    """

    if not artifacts.autopilot:
        return [
            "Stop at your Skill's stop condition and leave every approval to the "
            "user. Never write `approvals` yourself."
        ]

    reserved = sorted(AUTOPILOT_HUMAN_ONLY.get(artifacts.risk, frozenset()))
    lines = [
        "",
        "AUTOPILOT IS ON for this change. Carry it to the next phase yourself "
        "instead of stopping at the gate, but only when you would have told the "
        "user it was fine. Judge each gate on its merits; do not rubber-stamp.",
        "To pass a gate: write the timestamp under `auto_approvals.<artifact>` in "
        "proposal.md and set `status` to the next phase. Never write `approvals` "
        "— that map is the user's signature and yours is not the same thing.",
        "Implementation and verification are not gates, so there is nothing to "
        "sign: finish the phase, then set `status` to the next one — "
        "`implementing` to `verifying` once every task is ticked, `verifying` to "
        "`ready` once every approved requirement has passing evidence. Stop at "
        "`ready`; archiving folds the deltas into the catalogue and stays the "
        "user's.",
        "To stop instead: leave `status` where it is and write a `hold` mapping "
        "with `gate`, `reason` and `raised`. Say plainly in the chat what you "
        "need a decision on. Raise a hold whenever the change is ambiguous, "
        "widens beyond its proposal, touches security, data or public contracts, "
        "or when you would want a second opinion.",
    ]
    if reserved:
        lines.append(
            f"Risk tier `{artifacts.risk}` reserves these for the user no matter "
            f"what: {', '.join(f'`{gate}`' for gate in reserved)}. Draft them, "
            "then raise a hold and wait."
        )
    return lines


def prepare_action(
    catalogue: AsddCatalogue, change_id: str, action: str
) -> tuple[ChangeRecord, str, str]:
    """Check an action is runnable now and return the prompt that runs it."""

    record = catalogue.read_change(change_id)
    rail = action_rail(record.artifacts)
    available = {item["id"]: item for item in rail["actions"]}
    # "Continue" is the autopilot face of whatever phase comes after this gate:
    # the agent that clears the gate is the same agent that does the next phase,
    # so one click hands it both jobs rather than making the reader click twice.
    if action == "autopilot_continue":
        if "autopilot_continue" not in available:
            raise AsddActionBlocked(
                "Autopilot is not carrying this change right now", []
            )
        action = _autopilot_next(record.artifacts) or action
        available[action] = {"id": action, "blockers": []}
    if action not in _PHASE_SKILLS:
        raise AsddStoreError(f"Unknown ASDD action: {action}")
    if action not in available:
        raise AsddActionBlocked(
            f"`{action}` is not offered while the change is `{record.artifacts.status}`",
            [],
        )
    blockers = available[action]["blockers"]
    if blockers:
        raise AsddActionBlocked(
            f"`{action}` is blocked: {blockers[0]['message']}", blockers
        )
    skill, _produces = _PHASE_SKILLS[action]
    return record, action_prompt(catalogue, record, action), skill


def set_autopilot(
    catalogue: AsddCatalogue, change_id: str, *, enabled: bool
) -> ChangeRecord:
    """Turn autopilot on or off, refusing it where it would mean nothing."""

    record = catalogue.read_change(change_id)
    if enabled and record.artifacts.status in TERMINAL_STATUSES:
        raise AsddActionBlocked(
            f"`{record.artifacts.status}` changes have nothing left to carry", []
        )
    return catalogue.set_autopilot(change_id, enabled=enabled)


def mark_ready(catalogue: AsddCatalogue, change_id: str) -> ChangeRecord:
    record = catalogue.read_change(change_id)
    blockers = archive_blockers(record.artifacts)
    if blockers:
        raise AsddActionBlocked(
            f"The change is not ready: {blockers[0]['message']}", blockers
        )
    updated = catalogue.set_status(change_id, "ready")
    return updated


def archive(
    catalogue: AsddCatalogue, change_id: str, *, today: date | None = None
) -> dict[str, Any]:
    """Fold a change into the catalogue after re-checking its gates."""

    record = catalogue.read_change(change_id)
    blockers = archive_blockers(record.artifacts)
    if blockers:
        raise AsddActionBlocked(
            f"The change cannot be archived: {blockers[0]['message']}", blockers
        )
    # Resolve the date once, so the name reported back and the folder created
    # cannot land on different sides of midnight.
    stamp = today or datetime.now(timezone.utc).date()
    archived_as = catalogue.archive_entry_name(change_id, today=stamp)
    updated = catalogue.archive_change(change_id, today=stamp)
    logger.info("asdd_change_archived change_id={} capabilities={}", change_id, updated)
    return {
        "change_id": record.change_id,
        "archived_as": archived_as,
        "capabilities_updated": updated,
    }


def record_evidence(
    catalogue: AsddCatalogue,
    change_id: str,
    *,
    evidence_id: str,
    kind: str,
    result: str,
    summary: str,
    requirement: str | None = None,
    body: str = "",
) -> ChangeRecord:
    record = catalogue.record_evidence(
        change_id,
        evidence_id=evidence_id,
        kind=kind,
        result=result,
        summary=summary,
        requirement=requirement,
        body=body,
    )
    return record


def record_handoff_evidence(
    workspace: str | Path,
    *,
    change_id: str,
    task_id: str,
    recipient: str,
    artifact: dict[str, Any],
    owned_requirements: list[str],
) -> ChangeRecord | None:
    """Write one evidence page from a completed delegated mission.

    Machine trust comes only from a runtime-generated `completion_contract`.
    A member's own prose about what it checked is recorded as `review` evidence
    — useful context, but not the thing the ready gate counts as proof.
    """

    catalogue = catalogue_for(workspace)
    try:
        catalogue.read_change(change_id)
    except AsddStoreError:
        # The change may have been archived or renamed while the mission ran.
        # Losing the page is better than failing the handoff that produced it.
        logger.warning(
            "asdd_handoff_evidence_skipped change_id={} task_id={}", change_id, task_id
        )
        return None

    results = [
        item
        for item in (artifact.get("criteria_results") or [])
        if isinstance(item, dict)
    ]
    reported = {
        str(item.get("criterion_id")): str(item.get("status") or "inconclusive")
        for item in results
        if item.get("criterion_id")
    }
    missing = [name for name in owned_requirements if name not in reported]
    verified = bool(artifact.get("completion_contract"))
    statuses = {reported.get(name, "inconclusive") for name in owned_requirements}
    if missing or "failed" in statuses:
        result = "failed"
    elif statuses == {"passed"}:
        result = "passed"
    else:
        result = "inconclusive"

    lines = [
        f"Mission `{task_id}` handed off by **{recipient}**.",
        "",
        *[
            f"- `{name}` — {reported.get(name, 'not reported')}"
            for name in owned_requirements
        ],
    ]
    if missing:
        lines += ["", "Requirements with no reported result: " + ", ".join(missing)]
    if not verified:
        lines += [
            "",
            "No runtime completion contract accompanied this handoff, so nothing "
            "here counts as machine evidence.",
        ]

    return record_evidence(
        catalogue,
        change_id,
        evidence_id=f"handoff-{task_id}",
        kind="machine" if verified else "review",
        result=result,
        summary=f"Handoff from {recipient} for {len(owned_requirements)} requirements",
        requirement=owned_requirements[0] if len(owned_requirements) == 1 else None,
        body="\n".join(lines),
    )


def spec_payload(catalogue: AsddCatalogue, capability: str) -> dict[str, Any] | None:
    read = catalogue.read_spec(capability)
    if read is None:
        return None
    document, spec = read
    return {
        "capability": capability,
        "purpose": spec.purpose,
        "requirements": [
            {
                "name": requirement.name,
                "statement": requirement.statement,
                "scenarios": [
                    {"name": scenario.name, "steps": scenario.steps}
                    for scenario in requirement.scenarios
                ],
            }
            for requirement in spec.requirements
        ],
        "path": catalogue.relative(catalogue.spec_path(capability)),
        "body": document.body,
    }


__all__ = [
    "AsddActionBlocked",
    "action_prompt",
    "approve",
    "archive",
    "catalogue_for",
    "change_payload",
    "create_change",
    "derive_change_id",
    "detail_payload",
    "list_changes",
    "mark_ready",
    "prepare_action",
    "record_evidence",
    "record_handoff_evidence",
    "spec_payload",
]
