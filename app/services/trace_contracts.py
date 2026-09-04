"""Typed, provider-neutral EASD contracts shared by API and runtime."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import PurePosixPath
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TraceRiskTier = Literal["trivial", "standard", "cross_layer", "critical"]
TraceDeliveryMode = Literal["direct", "planned"]
TraceEvidenceKind = Literal["machine", "review", "manual", "waiver"]
TraceEvidenceResult = Literal["passed", "failed", "inconclusive", "waived"]
TracePlanMissionKind = Literal[
    "implementation",
    "integration",
    "review",
    "verification",
]
TracePlanIsolation = Literal["auto", "shared", "worktree"]
TraceConstraintKind = Literal[
    "architecture", "compatibility", "security", "operational", "product"
]

_VERIFICATION_PROGRAM_ACTIONS: dict[str, set[str] | None] = {
    "bun": {"run", "test"},
    "bundle": {"exec"},
    "cargo": {"check", "clippy", "fmt", "test"},
    "composer": {"check", "test"},
    "dotnet": {"build", "test"},
    "git": {"diff", "status"},
    "go": {"test"},
    "gradle": {"build", "check", "test"},
    "gradlew": {"build", "check", "test"},
    "make": None,
    "mvn": {"test", "verify"},
    "mvnw": {"test", "verify"},
    "npm": {"run", "test"},
    "phpunit": None,
    "pnpm": {"run", "test"},
    "pytest": None,
    "ruff": {"check", "format"},
    "swift": {"build", "test"},
    "ty": {"check"},
    "uv": {"run"},
    "xcodebuild": {"build", "test"},
}

_SCRIPT_VERBS = ("build", "check", "lint", "test", "typecheck", "verify")


def parse_verification_command(command: str) -> list[str]:
    """Parse one approved non-shell verification command into argv."""
    if not command.strip() or any(token in command for token in ("\n", "\r", "\x00")):
        raise ValueError("verification commands must be single non-blank lines")
    if any(operator in command for operator in ("&&", "||", ";", "|", ">", "<")):
        raise ValueError(
            "verification commands cannot contain shell composition or redirection"
        )
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValueError("verification command has invalid quoting") from exc
    if not parts:
        raise ValueError("verification command must not be blank")
    program = PurePosixPath(parts[0]).name
    if parts[0] != program and parts[0] not in {"./gradlew", "./mvnw"}:
        raise ValueError(
            "verification programs must use a PATH name or approved wrapper"
        )
    if program in {"python", "python3"}:
        if (
            len(parts) < 3
            or parts[1] != "-m"
            or parts[2]
            not in {
                "compileall",
                "pytest",
            }
        ):
            raise ValueError(
                "python verification commands require -m pytest/compileall"
            )
        return parts
    allowed_actions = _VERIFICATION_PROGRAM_ACTIONS.get(program)
    if program not in _VERIFICATION_PROGRAM_ACTIONS:
        raise ValueError(f"unsupported verification program: {program}")
    if allowed_actions is not None and (
        len(parts) < 2 or parts[1] not in allowed_actions
    ):
        raise ValueError(f"unsupported {program} verification action")
    if program in {"bun", "npm", "pnpm"} and parts[1] == "run":
        if len(parts) < 3 or not any(
            verb in parts[2].lower() for verb in _SCRIPT_VERBS
        ):
            raise ValueError(
                f"{program} verification scripts must be build/check/lint/test/verify"
            )
    if program == "bundle" and (len(parts) < 3 or parts[2] not in {"rspec", "rubocop"}):
        raise ValueError("bundle verification commands require exec rspec/rubocop")
    if program == "uv":
        if len(parts) < 3 or parts[2] not in {"pytest", "ruff", "ty"}:
            raise ValueError("uv verification commands require run pytest/ruff/ty")
    if program == "make" and (
        len(parts) < 2
        or not any(
            token in parts[1].lower() for token in ("test", "check", "lint", "verify")
        )
    ):
        raise ValueError("make verification target must be test/check/lint/verify")
    return parts


def _default_evidence_kinds() -> list[TraceEvidenceKind]:
    return ["machine", "review", "manual"]


PLANNED_FLOW_TRIGGERS: tuple[str, ...] = (
    "multi_repository",
    "cross_layer",
    "security",
    "migration",
    "persistence",
    "public_compatibility",
    "concurrency",
    "critical_risk",
    "disjoint_ownership",
)
"""The only conditions that may force `planned`.

Delivery flow must be decided by properties of the change. Reasoning from the
permissions of the current phase — "authoring forbids editing product files",
"the runtime guard blocks implementation" — holds for every run, so it cannot
distinguish one change from another; accepting it routes every run to `planned`
and silently defeats the lightest-safe-flow rule.
"""

_NON_DRIVER_RATIONALE_MARKERS: tuple[str, ...] = (
    "during authoring",
    "in this phase",
    "lifecycle",
    "runtime guard",
    "runtime blocks",
    "blocks implementation",
    "not permitted in this phase",
    "not yet allowed",
    "phase permission",
    "tool restriction",
)


class TraceDeliveryFlow(BaseModel):
    """User-reviewable execution path recommended during specification."""

    model_config = ConfigDict(extra="forbid")

    mode: TraceDeliveryMode = "planned"
    rationale: str = Field(
        default="Plan is required by default until direct eligibility is proven.",
        min_length=1,
        max_length=4000,
    )
    confidence: float = Field(default=1.0, ge=0, le=1)
    required_by: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("rationale")
    @classmethod
    def _strip_rationale(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("delivery flow rationale must not be blank")
        return stripped

    @field_validator("required_by")
    @classmethod
    def _clean_required_by(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def normalize_flow_trigger(value: str) -> str | None:
    """Map one free-text `required_by` entry onto a known planned-flow trigger.

    Returns None when the entry names no recognized condition. Kept tolerant on
    wording so an agent may write "cross-layer change" or "Cross layer" and
    still match, while "EASD lifecycle" or "repo runtime guard" does not.
    """

    key = re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")
    if not key:
        return None
    aliases = {
        "multi_repo": "multi_repository",
        "multiple_repositories": "multi_repository",
        "cross_repository": "multi_repository",
        "crosslayer": "cross_layer",
        "multi_layer": "cross_layer",
        "auth": "security",
        "authentication": "security",
        "authorization": "security",
        "schema_migration": "migration",
        "database_migration": "migration",
        "data_migration": "migration",
        "public_api": "public_compatibility",
        "public_contract": "public_compatibility",
        "backward_compatibility": "public_compatibility",
        "ordering": "concurrency",
        "critical": "critical_risk",
        "shared_paths": "disjoint_ownership",
        "path_ownership": "disjoint_ownership",
        "breadth": "disjoint_ownership",
    }
    if key in PLANNED_FLOW_TRIGGERS:
        return key
    if key in aliases:
        return aliases[key]
    for trigger in PLANNED_FLOW_TRIGGERS:
        if trigger in key:
            return trigger
    for alias, trigger in aliases.items():
        if alias in key:
            return trigger
    return None


def validate_delivery_flow_reasoning(flow: TraceDeliveryFlow) -> list[str]:
    """Return blocking reasons why this flow recommendation is not admissible.

    Enforced at the specification-submission boundary rather than on the model,
    so already-persisted contracts keep loading and the provisional default
    stays constructible. An empty list means the recommendation is admissible.
    """

    problems: list[str] = []
    lowered = flow.rationale.casefold()
    marker = next((m for m in _NON_DRIVER_RATIONALE_MARKERS if m in lowered), None)
    if marker is not None:
        problems.append(
            "delivery_flow.rationale must describe this change, not the "
            f"permissions of the current phase (found {marker!r}). Phase "
            "restrictions hold for every run and cannot select a flow."
        )
    matched = [
        item for item in flow.required_by if normalize_flow_trigger(item) is not None
    ]
    unmatched = [
        item for item in flow.required_by if normalize_flow_trigger(item) is None
    ]
    if unmatched:
        problems.append(
            "delivery_flow.required_by entries name no recognized planned-flow "
            "condition: "
            + ", ".join(repr(item) for item in unmatched)
            + ". Recognized conditions: "
            + ", ".join(PLANNED_FLOW_TRIGGERS)
            + "."
        )
    if flow.mode == "planned" and not matched:
        problems.append(
            "a planned delivery_flow must name at least one matched condition in "
            "required_by (" + ", ".join(PLANNED_FLOW_TRIGGERS) + "). If none "
            "applies, recommend direct."
        )
    if flow.mode == "direct" and matched:
        problems.append(
            "a direct delivery_flow must leave required_by empty; matched "
            "conditions (" + ", ".join(matched) + ") force planned."
        )
    return problems


class TraceEvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_kinds: list[TraceEvidenceKind] = Field(
        default_factory=_default_evidence_kinds,
        min_length=1,
        max_length=4,
    )
    machine_required: bool = False
    minimum_passes: int = Field(default=1, ge=1, le=20)

    @field_validator("allowed_kinds")
    @classmethod
    def _unique_kinds(cls, value: list[TraceEvidenceKind]) -> list[TraceEvidenceKind]:
        return list(dict.fromkeys(value))


class TraceCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Z][A-Z0-9_-]+$")
    statement: str = Field(min_length=1, max_length=4000)
    required: bool = True
    evidence_policy: TraceEvidencePolicy = Field(default_factory=TraceEvidencePolicy)

    @field_validator("id", "statement")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class TraceImpactTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=240)
    path: str = Field(min_length=1, max_length=4096)
    module: str | None = Field(default=None, max_length=240)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("repository", "path", "reason")
    @classmethod
    def _strip_target_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("path")
    @classmethod
    def _safe_target_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("impact target paths must be repository-relative")
        return str(path)


class TraceConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TraceConstraintKind
    statement: str = Field(min_length=1, max_length=4000)
    source_refs: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("statement")
    @classmethod
    def _strip_statement(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("source_refs")
    @classmethod
    def _safe_constraint_refs(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            item = raw.strip()
            if not item:
                continue
            path = PurePosixPath(item.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("constraint source_refs must be repository-relative")
            cleaned.append(str(path))
        return list(dict.fromkeys(cleaned))


class TraceVerificationProbe(BaseModel):
    """One executed verification command and the exit code it produced.

    A verification command is frozen into an immutable accepted Spec, so a
    command that cannot run makes every machine-required acceptance criterion
    unsatisfiable and costs a whole new revision to repair. Probes make the
    author state, with provenance, that each command was actually executed
    before it was persisted — turning an invisible assumption into an auditable
    claim a reviewer can re-run.
    """

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=2_000)
    exit_code: int = Field(ge=-256, le=256)
    detail: str = Field(default="", max_length=4_000)

    @field_validator("command")
    @classmethod
    def _strip_command(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("probe command must not be blank")
        return stripped

    #: Exit codes that mean the command never ran: the program is missing, the
    #: command is not on the approved allowlist, or it hung.
    UNRUNNABLE_EXIT_CODES: ClassVar[frozenset[int]] = frozenset({124, 126, 127})

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    @property
    def runnable(self) -> bool:
        """Whether the repository can execute this command at all.

        Authoring runs before implementation, so a test command is *expected*
        to fail at that point — that is what specification-first means.
        Requiring exit 0 pushes an author toward a command that passes today
        rather than one that proves the accepted behavior tomorrow, so
        admissibility checks runnability instead of success.
        """

        return self.exit_code not in self.UNRUNNABLE_EXIT_CODES


def validate_verification_probes(
    specification: "TraceSpecification",
    probes: list[TraceVerificationProbe],
) -> list[str]:
    """Return blocking reasons why this specification's commands are unproven."""

    problems: list[str] = []
    by_command = {probe.command: probe for probe in probes}
    machine_required = sorted(
        criterion.id
        for criterion in specification.criteria
        if criterion.required and criterion.evidence_policy.machine_required
    )
    for command in specification.verification_commands:
        probe = by_command.get(command)
        if probe is None:
            problems.append(
                f"verification command {command!r} was never executed, so nothing "
                "shows this repository can run it."
            )
            continue
        if not probe.runnable and machine_required:
            problems.append(
                f"verification command {command!r} could not be executed "
                f"(exit {probe.exit_code}: {probe.detail.strip()[:200] or 'no output'}), "
                "but "
                + ", ".join(machine_required)
                + " require machine evidence. Resolve the entry point this "
                "repository actually provides — a project virtualenv "
                "interpreter, a lockfile-managed runner, or the configured "
                "toolchain — and submit again. A command that runs and reports "
                "failing tests is fine at this stage: the implementation does "
                "not exist yet."
            )
    if machine_required and not specification.verification_commands:
        problems.append(
            ", ".join(machine_required)
            + " require machine evidence, so the specification must persist at "
            "least one executable verification command."
        )
    unknown = [
        probe.command
        for probe in probes
        if probe.command not in set(specification.verification_commands)
    ]
    if unknown:
        problems.append(
            "probes report commands that the specification does not persist: "
            + ", ".join(repr(item) for item in unknown)
        )
    return problems


class TraceSpecification(BaseModel):
    """Normalized immutable specification payload stored in a revision."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    problem: str = Field(min_length=1, max_length=12000)
    outcome: str = Field(min_length=1, max_length=12000)
    goals: list[str] = Field(default_factory=list, max_length=100)
    non_goals: list[str] = Field(default_factory=list, max_length=100)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    impact_targets: list[TraceImpactTarget] = Field(
        default_factory=list, max_length=200
    )
    constraints: list[TraceConstraint] = Field(default_factory=list, max_length=100)
    verification_commands: list[str] = Field(default_factory=list, max_length=50)
    risk_tier: TraceRiskTier = "standard"
    delivery_flow: TraceDeliveryFlow = Field(default_factory=TraceDeliveryFlow)
    criteria: list[TraceCriterion] = Field(min_length=1, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def _ignore_legacy_schema_version(cls, value):
        if isinstance(value, dict) and "schema_version" in value:
            value = {
                key: item for key, item in value.items() if key != "schema_version"
            }
        return value

    @field_validator("title", "problem", "outcome")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("goals", "non_goals", "verification_commands")
    @classmethod
    def _clean_lines(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("verification_commands")
    @classmethod
    def _safe_verification_commands(cls, value: list[str]) -> list[str]:
        for command in value:
            parse_verification_command(command)
        return value

    @field_validator("source_refs")
    @classmethod
    def _safe_source_refs(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            item = raw.strip()
            if not item:
                continue
            if item.startswith(("https://", "http://")):
                cleaned.append(item)
                continue
            path = PurePosixPath(item.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    "source_refs must be repository-relative paths or HTTP(S) URLs"
                )
            cleaned.append(str(path))
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def _unique_criteria(self) -> "TraceSpecification":
        ids = [criterion.id for criterion in self.criteria]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError("duplicate criterion IDs: " + ", ".join(duplicates))
        return self

    def normalized(self) -> dict:
        return self.model_dump(mode="json")

    def content_hash(self) -> str:
        raw = json.dumps(
            self.normalized(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def criterion_ids(self) -> set[str]:
        return {criterion.id for criterion in self.criteria}


class TracePlanMission(BaseModel):
    """One immutable planned mission derived from an accepted specification."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_-]+$")
    kind: TracePlanMissionKind
    title: str = Field(min_length=1, max_length=240)
    goal: str = Field(min_length=1, max_length=4000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)
    target_repositories: list[str] = Field(default_factory=list, max_length=20)
    target_paths: list[str] = Field(default_factory=list, max_length=100)
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    expected_output: str = Field(min_length=1, max_length=4000)
    constraints: list[str] = Field(default_factory=list, max_length=100)
    verification_commands: list[str] = Field(default_factory=list, max_length=50)
    isolation: TracePlanIsolation = "auto"

    @field_validator("id", "title", "goal", "expected_output")
    @classmethod
    def _strip_mission_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator(
        "acceptance_criteria",
        "target_repositories",
        "depends_on",
        "constraints",
    )
    @classmethod
    def _clean_mission_lines(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("target_paths")
    @classmethod
    def _safe_mission_paths(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            path = PurePosixPath(raw.strip().replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("plan target_paths must be repository-relative")
            cleaned.append(str(path))
        return list(dict.fromkeys(item for item in cleaned if item not in {"", "."}))

    @field_validator("verification_commands")
    @classmethod
    def _safe_mission_commands(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        for command in cleaned:
            parse_verification_command(command)
        return cleaned


class TracePlan(BaseModel):
    """Normalized immutable execution plan for one accepted spec hash."""

    model_config = ConfigDict(extra="forbid")

    spec_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    review_required: bool = False
    integration_owner: str | None = Field(default=None, max_length=64)
    missions: list[TracePlanMission] = Field(min_length=1, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def _ignore_legacy_schema_version(cls, value):
        if isinstance(value, dict) and "schema_version" in value:
            value = {
                key: item for key, item in value.items() if key != "schema_version"
            }
        return value

    @model_validator(mode="after")
    def _valid_mission_graph(self) -> "TracePlan":
        mission_ids = [mission.id for mission in self.missions]
        duplicates = sorted(
            {item for item in mission_ids if mission_ids.count(item) > 1}
        )
        if duplicates:
            raise ValueError("duplicate plan mission IDs: " + ", ".join(duplicates))
        known = set(mission_ids)
        if self.integration_owner is not None and self.integration_owner not in known:
            raise ValueError("integration_owner must reference a plan mission")
        for mission in self.missions:
            unknown = sorted(set(mission.depends_on) - known)
            if unknown:
                raise ValueError(
                    f"plan mission {mission.id} has unknown dependencies: "
                    + ", ".join(unknown)
                )
            if mission.id in mission.depends_on:
                raise ValueError(f"plan mission {mission.id} cannot depend on itself")

        indegree = {mission_id: 0 for mission_id in mission_ids}
        dependents: dict[str, list[str]] = {
            mission_id: [] for mission_id in mission_ids
        }
        for mission in self.missions:
            indegree[mission.id] = len(mission.depends_on)
            for dependency in mission.depends_on:
                dependents[dependency].append(mission.id)
        ready = [mission_id for mission_id, count in indegree.items() if count == 0]
        visited = 0
        while ready:
            current = ready.pop()
            visited += 1
            for dependent in dependents[current]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if visited != len(mission_ids):
            raise ValueError("plan mission dependencies must be acyclic")
        return self

    def normalized(self) -> dict:
        return self.model_dump(mode="json")

    def content_hash(self) -> str:
        raw = json.dumps(
            self.normalized(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def mission_ids(self) -> set[str]:
        return {mission.id for mission in self.missions}

    def criterion_ids(self) -> set[str]:
        return {
            criterion_id
            for mission in self.missions
            for criterion_id in mission.acceptance_criteria
        }

    def implementation_criterion_ids(self) -> set[str]:
        return {
            criterion_id
            for mission in self.missions
            if mission.kind in {"implementation", "integration"}
            for criterion_id in mission.acceptance_criteria
        }


class TraceReviewCriterion(BaseModel):
    """One cited review verdict submitted by a runtime-identified reviewer."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=3, max_length=64)
    result: Literal["passed", "failed", "inconclusive"]
    summary: str = Field(min_length=1, max_length=4000)

    @field_validator("criterion_id", "summary")
    @classmethod
    def _strip_review_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


__all__ = [
    "TraceCriterion",
    "TraceConstraint",
    "TraceConstraintKind",
    "TraceEvidenceKind",
    "TraceEvidencePolicy",
    "TraceEvidenceResult",
    "TraceRiskTier",
    "TraceReviewCriterion",
    "TraceImpactTarget",
    "TracePlan",
    "TracePlanIsolation",
    "TracePlanMission",
    "TracePlanMissionKind",
    "TraceSpecification",
    "parse_verification_command",
]
