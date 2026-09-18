"""The ASDD lifecycle, computed from what a change folder contains.

The old model kept a change's phase in a database column and defended it with a
content hash and a session lock. This one reads `status` out of `proposal.md`
and checks it against the files on disk, so the answer to "what happens next"
is something a person can derive by opening the folder — and something they can
correct with an editor when a run dies halfway.

Two rules keep that honest. A declared status is never trusted on its own: a
change that says `tasked` but has no `tasks.md` reports that as a blocker
instead of offering the next action. And every gate is a missing *file* or a
missing *approval*, never a stale identifier, so nothing here can fail for a
reason the user cannot see in `git status`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal[
    "drafting",
    "proposed",
    "specifying",
    "specified",
    "designing",
    "designed",
    "tasking",
    "tasked",
    "implementing",
    "verifying",
    "ready",
    "archived",
]

STATUSES: tuple[str, ...] = (
    "drafting",
    "proposed",
    "specifying",
    "specified",
    "designing",
    "designed",
    "tasking",
    "tasked",
    "implementing",
    "verifying",
    "ready",
    "archived",
)

RISK_TIERS: tuple[str, ...] = ("trivial", "standard", "cross_layer", "critical")

#: Risk tiers that must produce a `design.md` and an independent review. Below
#: this line a design document is noise; at or above it, the change crosses a
#: boundary whose alternatives have to be written down before code exists.
DESIGN_REQUIRED_RISK: frozenset[str] = frozenset({"cross_layer", "critical"})

APPROVAL_ARTIFACTS: tuple[str, ...] = ("proposal", "specs", "design", "tasks")

#: The status at which each artifact is finished and waiting on a person.
#:
#: Declaring it is how an author says "this is written, read it" — the files
#: alone cannot say so, because `create_change` writes a proposal template and
#: an existence check would pass on a change nobody has touched.
APPROVAL_GATE: dict[str, str] = {
    "proposal": "proposed",
    "specs": "specified",
    "design": "designed",
    "tasks": "tasked",
}

TERMINAL_STATUSES: frozenset[str] = frozenset({"archived"})

#: Gates autopilot may never clear on its own, by risk tier.
#:
#: Autopilot exists so an agent can carry an ordinary change through its gates
#: without waiting on a person for each one. It does not exist to remove the
#: person from decisions the tier was created to force. `cross_layer` and
#: `critical` are exactly the tiers that already demand a written design and an
#: independent review, so those two moments stay a person's — the design they
#: are being asked to accept, and the archive that folds it into the catalogue
#: for good.
AUTOPILOT_HUMAN_ONLY: dict[str, frozenset[str]] = {
    "trivial": frozenset(),
    "standard": frozenset(),
    "cross_layer": frozenset({"design", "archive"}),
    "critical": frozenset({"design", "archive"}),
}


def human_only_gate(artifacts: ChangeArtifacts, gate: str) -> bool:
    """Whether `gate` needs a person even with autopilot on."""

    return gate in AUTOPILOT_HUMAN_ONLY.get(artifacts.risk, frozenset())


@dataclass(frozen=True, slots=True)
class ChangeArtifacts:
    """What one change folder actually contains, as read from disk."""

    change_id: str
    title: str
    status: str
    risk: str
    capabilities: list[str] = field(default_factory=list)
    #: Gates a person signed off, written only by the approve endpoint.
    approvals: dict[str, str | None] = field(default_factory=dict)
    #: Gates autopilot cleared on the agent's own judgment.
    #:
    #: Kept apart from `approvals` so the repository never says a person
    #: approved something no person read. Both clear a gate; only one is a
    #: signature, and the panel shows which.
    auto_approvals: dict[str, str | None] = field(default_factory=dict)
    autopilot: bool = False
    #: Set by an agent that decided a gate needs a person after all.
    hold: dict[str, str] | None = None
    #: Whether `risk` is actually in the front matter. Absent means nobody
    #: has tiered the change yet, which is not the same as `standard`.
    risk_declared: bool = True
    has_proposal: bool = False
    has_design: bool = False
    #: Questions `design.md` still lists as unanswered.
    design_open_questions: list[str] = field(default_factory=list)
    has_tasks: bool = False
    delta_capabilities: list[str] = field(default_factory=list)
    #: Every requirement the deltas add or modify, by name. A removed one
    #: needs no evidence — there is nothing left to exercise.
    delta_requirements: list[str] = field(default_factory=list)
    #: Requirement name -> the results of the evidence pages citing it.
    evidence_results: dict[str, list[str]] = field(default_factory=dict)
    spec_problems: list[str] = field(default_factory=list)
    tasks_total: int = 0
    tasks_done: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    review_recorded: bool = False

    @property
    def design_required(self) -> bool:
        return self.risk in DESIGN_REQUIRED_RISK

    def approved(self, artifact: str) -> bool:
        """Whether a person signed this gate off."""

        return bool(self.approvals.get(artifact))

    def auto_approved(self, artifact: str) -> bool:
        return bool(self.auto_approvals.get(artifact))

    def cleared(self, artifact: str) -> bool:
        """Whether this gate is passed, by whichever route."""

        return self.approved(artifact) or self.auto_approved(artifact)

    @property
    def held(self) -> bool:
        return bool(self.hold)


def _blocker(code: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **fields}


def _gate_blockers(artifacts: ChangeArtifacts, artifact: str) -> list[dict[str, Any]]:
    """Refuse an approval the change is not standing at.

    The rail only ever offers an approval at its own gate, so this changes
    nothing a user can click. It closes the gap underneath: the endpoint takes
    the artifact from the URL, and without this an approval could be recorded
    against a change that is not there yet — a brand-new change whose
    `proposal.md` is still the untouched template cleared the proposal gate,
    because the template is a file and the gate only asked whether a file
    existed. Approving from the far side is refused for the opposite reason: it
    would rewind a change that has already moved on.
    """

    gate = APPROVAL_GATE.get(artifact)
    if gate is None or artifacts.status == gate:
        return []
    order = {status: index for index, status in enumerate(STATUSES)}
    here = order.get(artifacts.status, -1)
    there = order[gate]
    if here < there:
        return [
            _blocker(
                "gate_not_reached",
                f"The change is still at `{artifacts.status}`. It reaches the "
                f"{artifact} gate when proposal.md declares `status: {gate}`.",
                status=artifacts.status,
                gate=gate,
            )
        ]
    return [
        _blocker(
            "gate_passed",
            f"The change is past the {artifact} gate at `{artifacts.status}`. "
            f"Approving now would move it back to "
            f"`{status_after_approval(artifacts, artifact)}`.",
            status=artifacts.status,
            gate=gate,
        )
    ]


def artifact_blockers(
    artifacts: ChangeArtifacts, artifact: str
) -> list[dict[str, Any]]:
    """Return why `artifact` cannot be approved yet."""

    blockers: list[dict[str, Any]] = _gate_blockers(artifacts, artifact)
    if artifact == "proposal":
        if not artifacts.has_proposal:
            blockers.append(_blocker("missing_artifact", "proposal.md does not exist"))
        if artifacts.has_proposal and not artifacts.risk_declared:
            # The tier decides whether this change owes a design and an
            # independent review. Letting an unset one read as `standard` would
            # skip that decision rather than make it.
            blockers.append(
                _blocker(
                    "risk_not_set",
                    "The proposal has no `risk`. Set it to "
                    + ", ".join(f"`{tier}`" for tier in RISK_TIERS)
                    + " — the tier decides whether this change owes a design "
                    "and an independent review.",
                )
            )
        if artifacts.has_proposal and not artifacts.capabilities:
            blockers.append(
                _blocker(
                    "no_capabilities",
                    "The proposal names no capability, so no spec can be written "
                    "against it",
                )
            )
    elif artifact == "specs":
        if not artifacts.delta_capabilities:
            blockers.append(
                _blocker("missing_artifact", "No capability delta has been written")
            )
        missing = [
            capability
            for capability in artifacts.capabilities
            if capability not in artifacts.delta_capabilities
        ]
        if missing:
            blockers.append(
                _blocker(
                    "capability_without_delta",
                    "The proposal names capabilities with no delta: "
                    + ", ".join(sorted(missing)),
                    capabilities=sorted(missing),
                )
            )
        # And the other direction. Archiving folds every delta present, so a
        # delta for a capability the proposal never named would contract
        # behaviour nobody proposed and nobody approved.
        undeclared = [
            capability
            for capability in artifacts.delta_capabilities
            if capability not in artifacts.capabilities
        ]
        if undeclared:
            blockers.append(
                _blocker(
                    "delta_without_capability",
                    "Deltas exist for capabilities the proposal does not name: "
                    + ", ".join(sorted(undeclared))
                    + ". Add them to `capabilities` or delete the delta — "
                    "archiving folds every delta it finds.",
                    capabilities=sorted(undeclared),
                )
            )
        blockers += [
            _blocker("spec_format", problem) for problem in artifacts.spec_problems
        ]
    elif artifact == "design":
        if not artifacts.has_design:
            blockers.append(_blocker("missing_artifact", "design.md does not exist"))
        elif artifacts.design_open_questions:
            # A design is the one artifact whose whole job is to have decided.
            # Approving it while it still lists what it has not decided would
            # make the gate the tier exists to force into a formality.
            blockers.append(
                _blocker(
                    "open_questions",
                    "design.md still lists "
                    f"{len(artifacts.design_open_questions)} open question"
                    f"{'' if len(artifacts.design_open_questions) == 1 else 's'}: "
                    + "; ".join(artifacts.design_open_questions[:3])
                    + ". Ask the user with `ask_user`, record the answers, and "
                    "move anything genuinely out of scope to a follow-up change.",
                    questions=artifacts.design_open_questions,
                )
            )
    elif artifact == "tasks":
        if not artifacts.has_tasks:
            blockers.append(_blocker("missing_artifact", "tasks.md does not exist"))
        elif artifacts.tasks_total == 0:
            blockers.append(_blocker("no_tasks", "tasks.md contains no checklist item"))
    return blockers


def _implementation_blockers(artifacts: ChangeArtifacts) -> list[dict[str, Any]]:
    remaining = artifacts.tasks_total - artifacts.tasks_done
    if remaining <= 0:
        return []
    return [
        _blocker(
            "tasks_open",
            f"{remaining} of {artifacts.tasks_total} tasks are still unchecked",
            remaining=remaining,
            total=artifacts.tasks_total,
        )
    ]


def _verification_blockers(artifacts: ChangeArtifacts) -> list[dict[str, Any]]:
    blockers = _implementation_blockers(artifacts)
    if not artifacts.evidence_ids:
        blockers.append(
            _blocker("no_evidence", "No evidence has been recorded for this change")
        )
    else:
        # "Evidence before ready" used to mean one page of any kind, so a change
        # contracting five requirements archived on a single unrelated page —
        # and a page citing a requirement name that does not exist counted just
        # the same. Coverage is what the rule was always trying to say.
        uncovered = [
            name
            for name in artifacts.delta_requirements
            if not artifacts.evidence_results.get(name)
        ]
        if uncovered:
            blockers.append(
                _blocker(
                    "requirement_without_evidence",
                    f"{len(uncovered)} approved requirement"
                    f"{' has' if len(uncovered) == 1 else 's have'} no evidence: "
                    + "; ".join(sorted(uncovered)[:3]),
                    requirements=sorted(uncovered),
                )
            )
        failing = sorted(
            name
            for name, results in artifacts.evidence_results.items()
            if "failed" in results
        )
        if failing:
            blockers.append(
                _blocker(
                    "requirement_failed",
                    "Evidence records a failure for: " + "; ".join(failing[:3]),
                    requirements=failing,
                )
            )
    if artifacts.design_required and not artifacts.review_recorded:
        blockers.append(
            _blocker(
                "review_required",
                f"Risk tier '{artifacts.risk}' requires a recorded independent review",
            )
        )
    return blockers


def archive_blockers(artifacts: ChangeArtifacts) -> list[dict[str, Any]]:
    """Return why a change cannot be folded into the spec catalogue yet."""

    blockers = _verification_blockers(artifacts)
    if not artifacts.delta_capabilities:
        blockers.append(
            _blocker(
                "missing_artifact",
                "The change has no capability delta, so archiving would change nothing",
            )
        )
    for artifact in required_approvals(artifacts):
        if not artifacts.cleared(artifact):
            blockers.append(
                _blocker(
                    "approval_missing",
                    f"{artifact} has not been approved",
                    artifact=artifact,
                )
            )
        elif human_only_gate(artifacts, artifact) and not artifacts.approved(artifact):
            blockers.append(
                _blocker(
                    "human_approval_required",
                    f"Risk tier '{artifacts.risk}' needs a person to approve "
                    f"{artifact}; autopilot cleared it",
                    artifact=artifact,
                )
            )
    blockers += [
        _blocker("spec_format", problem) for problem in artifacts.spec_problems
    ]
    return blockers


def required_approvals(artifacts: ChangeArtifacts) -> tuple[str, ...]:
    """Return the approval gates this change has to clear, in order."""

    if artifacts.design_required:
        return ("proposal", "specs", "design", "tasks")
    return ("proposal", "specs", "tasks")


def status_after_approval(artifacts: ChangeArtifacts, artifact: str) -> str:
    """Return the status a change reaches once `artifact` is approved."""

    if artifact == "proposal":
        return "specifying"
    if artifact == "specs":
        return "designing" if artifacts.design_required else "tasking"
    if artifact == "design":
        return "tasking"
    if artifact == "tasks":
        return "implementing"
    raise ValueError(f"Unknown ASDD approval artifact: {artifact}")


def declared_status_problems(artifacts: ChangeArtifacts) -> list[dict[str, Any]]:
    """Return every way the declared status contradicts the files on disk.

    A hand-edited `status` is legitimate — the file is the source of truth — so
    this reports the contradiction rather than rewriting the value. The UI shows
    it on the rail and the user fixes whichever side is wrong.
    """

    problems: list[dict[str, Any]] = []
    status = artifacts.status
    if status not in STATUSES:
        return [
            _blocker(
                "unknown_status",
                f"`status: {status}` is not one of: {', '.join(STATUSES)}",
            )
        ]
    if artifacts.risk not in RISK_TIERS:
        problems.append(
            _blocker(
                "unknown_risk",
                f"`risk: {artifacts.risk}` is not one of: {', '.join(RISK_TIERS)}",
            )
        )
    reached = STATUSES.index(status)
    for artifact in required_approvals(artifacts):
        gate = STATUSES.index(status_after_approval(artifacts, artifact))
        # `cleared`, not `approved`: a change autopilot legitimately carried
        # past this gate records it under `auto_approvals`, and reporting that
        # as a contradiction would put a red banner on every autopilot run.
        if reached >= gate and not artifacts.cleared(artifact):
            problems.append(
                _blocker(
                    "approval_missing",
                    f"`status: {status}` is past the {artifact} gate, but "
                    f"`approvals.{artifact}` is empty",
                    artifact=artifact,
                )
            )
    if reached >= STATUSES.index("specified") and not artifacts.delta_capabilities:
        problems.append(
            _blocker(
                "missing_artifact",
                f"`status: {status}` is past specification, but the change has no "
                "capability delta",
            )
        )
    if reached >= STATUSES.index("tasked") and not artifacts.has_tasks:
        problems.append(
            _blocker(
                "missing_artifact",
                f"`status: {status}` is past planning, but tasks.md does not exist",
            )
        )
    if (
        artifacts.design_required
        and reached >= STATUSES.index("designed")
        and not artifacts.has_design
    ):
        problems.append(
            _blocker(
                "missing_artifact",
                f"`status: {status}` is past design, but design.md does not exist",
            )
        )
    return problems


def _action(
    action_id: str, label: str, blockers: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    blockers = blockers or []
    return {
        "id": action_id,
        "label": label,
        "state": "blocked" if blockers else "available",
        "blockers": blockers,
    }


def action_rail(artifacts: ChangeArtifacts) -> dict[str, Any]:
    """Return the driven rail the UI renders for one change.

    Every status offers exactly one primary action so the panel always has a
    next step to show, plus the retries and corrections that make a stalled
    change recoverable without touching the database.
    """

    status = artifacts.status
    actions: list[dict[str, Any]] = []
    primary: str | None = None

    def add(
        action_id: str,
        label: str,
        blockers: list[dict[str, Any]] | None = None,
        *,
        is_primary: bool = False,
    ) -> None:
        nonlocal primary
        actions.append(_action(action_id, label, blockers))
        if is_primary:
            primary = action_id

    # Whether autopilot is carrying this change right now. A hold is the agent
    # saying it wants a person, so it suspends the carrying everywhere rather
    # than only at the gate it was raised on.
    carrying = artifacts.autopilot and not artifacts.held

    def gate(artifact: str, approve_id: str, approve_label: str, redraft: str) -> None:
        """Offer one approval gate, honouring autopilot.

        With autopilot on and no hold raised, the change is not waiting on the
        reader — the agent carries it through — so the rail leads with the run
        action and keeps approving available as an override. A hold flips it
        back: the agent has said this one needs a person, and that is the only
        thing the rail should be pointing at.
        """

        blockers = artifact_blockers(artifacts, artifact)
        auto = carrying and not human_only_gate(artifacts, artifact) and not blockers
        if auto:
            add("autopilot_continue", "Continue", is_primary=True)
            add(approve_id, approve_label, blockers)
        else:
            add(approve_id, approve_label, blockers, is_primary=True)
        add(f"draft_{artifact if artifact != 'specs' else 'specs'}", redraft)

    if status == "drafting":
        add("draft_proposal", "Draft proposal", is_primary=True)
    elif status == "proposed":
        gate("proposal", "approve_proposal", "Approve proposal", "Redraft in chat")
    elif status == "specifying":
        add("draft_specs", "Draft spec deltas", is_primary=True)
    elif status == "specified":
        gate("specs", "approve_specs", "Approve specs", "Redraft in chat")
    elif status == "designing":
        add("draft_design", "Draft design", is_primary=True)
    elif status == "designed":
        gate("design", "approve_design", "Approve design", "Redraft in chat")
    elif status == "tasking":
        add("draft_tasks", "Draft tasks", is_primary=True)
    elif status == "tasked":
        gate("tasks", "approve_tasks", "Approve tasks", "Replan in chat")
    elif status == "implementing":
        # Lead with the work that is actually outstanding. Verification is the
        # phase that follows, but while tasks are unchecked it is blocked, and
        # leading with it meant arriving at `implementing` to find the
        # highlighted button refusing to run and the one you wanted drawn as a
        # secondary beside it.
        remaining = _implementation_blockers(artifacts)
        if carrying:
            add("autopilot_continue", "Continue", is_primary=True)
            add("start_implementation", "Run implementation")
            add("start_verification", "Run verification", remaining)
        elif remaining:
            add("start_implementation", "Run implementation", is_primary=True)
            add("start_verification", "Run verification", remaining)
        else:
            add("start_verification", "Run verification", is_primary=True)
            add("start_implementation", "Re-run implementation")
    elif status == "verifying":
        # The same gate the service enforces, so the rail never offers a
        # "Mark ready" that the next request refuses.
        if carrying:
            add("autopilot_continue", "Continue", is_primary=True)
            add("mark_ready", "Mark ready", archive_blockers(artifacts))
        else:
            add("mark_ready", "Mark ready", archive_blockers(artifacts), is_primary=True)
        add("start_verification", "Re-run verification")
    elif status == "ready":
        add("archive", "Archive", archive_blockers(artifacts), is_primary=True)
        # Archiving rewrites the catalogue and is undone only by another change,
        # so the rail always offers a dry read of what the fold would produce.
        add("check_archive", "Check what archiving changes")
    elif status == "archived":
        pass

    if status not in TERMINAL_STATUSES:
        add("cancel", "Cancel change")

    return {
        "status": status,
        "primary_action": primary,
        "actions": actions,
        "required_approvals": list(required_approvals(artifacts)),
        "problems": declared_status_problems(artifacts),
        "autopilot": artifacts.autopilot,
        "hold": dict(artifacts.hold) if artifacts.hold else None,
        "human_only_gates": sorted(
            AUTOPILOT_HUMAN_ONLY.get(artifacts.risk, frozenset())
        ),
    }


__all__ = [
    "APPROVAL_ARTIFACTS",
    "APPROVAL_GATE",
    "AUTOPILOT_HUMAN_ONLY",
    "ChangeArtifacts",
    "DESIGN_REQUIRED_RISK",
    "RISK_TIERS",
    "STATUSES",
    "Status",
    "TERMINAL_STATUSES",
    "action_rail",
    "archive_blockers",
    "artifact_blockers",
    "human_only_gate",
    "declared_status_problems",
    "required_approvals",
    "status_after_approval",
]
