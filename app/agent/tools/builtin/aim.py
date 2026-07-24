"""``aim_units`` / ``aim_compare`` — the state tool and compare engine for
AIM migration projects (``documents/research/aim-framework.md`` §3.5/§3.8).

Both resolve the current AIM project the same way ``code_graph`` tools
resolve a workspace's project (``CodingWorkspace`` -> ``CodingProject``),
then find the KB repo's path via
``CodingProject.settings["aim"]["roles"]["kb"]`` — a local workspace_id ->
``CodingWorkspace.path`` lookup (the shareable project manifest, keyed by
repo identity rather than a local id, lives in the KB's own ``aim.yaml``).
If no project / no ``aim`` role mapping exists yet — AIM-2's setup wizard
hasn't run, or this is being exercised from a plain Coding session pointed
straight at a KB repo for testing — both tools fall back to treating the
session's own sandboxed workspace as the KB root, and skip DB-side
recording (which needs a resolved project) with a clear note in the result
rather than failing outright.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid7

from pydantic import BeforeValidator, Field
from sqlmodel import select

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, Tool
from app.agent.state import AgentState
from app.core import db as db_module
from app.models.aim import AimClaim, AimLink, AimRun, AimUnit
from app.models.chat import CodingProject, CodingWorkspace
from app.services import code_graph_service as code_svc
from app.services import coding_project_service as proj_svc
from app.services.aim import kb_store
from app.services.aim.canonicalize import load_profile
from app.services.aim.compare import compare_dirs, write_report
from app.services.aim.models import (
    VALID_PHASES,
    VALID_PROJECT_PHASES,
    CanonicalProfile,
    is_valid_project_phase,
    is_valid_unit_phase,
)
from app.services.aim.readiness import (
    evaluate_pipeline,
    evaluate_transition,
    resolve_mapping_path,
)
from app.services.aim.reindex import upsert_unit


def _current_workflow_execution_id() -> str | None:
    """The workflow execution driving this tool call, if any — stamped onto
    ``AimRun`` rows so a run traces back to its pipeline execution. ``None``
    for a plain slash-command call, or an agent-turn tool call (which the
    context var doesn't reach; those still link via ``session_id``)."""
    from app.workflow.exec_context import current_execution_id

    return current_execution_id.get()


async def _current_workflow_name(db) -> str | None:
    execution_id = _current_workflow_execution_id()
    if not execution_id:
        return None
    try:
        parsed_id = UUID(execution_id)
    except ValueError:
        return None
    from app.models.workflow import WorkflowExecution

    execution = await db.get(WorkflowExecution, parsed_id)
    return execution.definition_name if execution is not None else None


def _json_coerce(value: object) -> object:
    """Accept a JSON-encoded string where a list/dict parameter is expected.

    Smaller models routinely serialize array/object tool arguments as a
    string (``"[\\"a.java\\"]"`` instead of ``["a.java"]``) and then retry
    the identical malformed call forever when validation bounces it —
    observed live with aim-lead stuck on ``set_phase`` ``target_paths``.
    Parsing the obvious case costs nothing and unsticks the loop; anything
    that doesn't parse falls through to normal validation.
    """
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("[", "{")):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


async def _resolve_project_and_kb_root(db) -> tuple[UUID | None, Path]:
    sandbox = get_sandbox()
    workspace_id = await code_svc.resolve_workspace_id(
        db, path=str(sandbox.workspace_root)
    )
    if workspace_id is not None:
        for project_id in await proj_svc.get_projects_for_workspace(db, workspace_id):
            project = await db.get(CodingProject, project_id)
            if project is None or project.kind != "aim":
                continue
            kb_ids = (project.settings.get("aim") or {}).get("roles", {}).get("kb")
            # AIM-2's project_setup stores role ids as lists; earlier
            # projects may carry a bare string. Accept both.
            if isinstance(kb_ids, str):
                kb_ids = [kb_ids]
            for kb_id in kb_ids or []:
                try:
                    kb_workspace = await db.get(CodingWorkspace, UUID(str(kb_id)))
                except ValueError:
                    continue
                if kb_workspace is not None:
                    return project_id, Path(kb_workspace.path)
            return project_id, sandbox.workspace_root
    return None, sandbox.workspace_root


#: A single path component: no separators, no ``..``, no absolute/drive
#: prefixes. Unit modules/names and case-set ids all become path segments
#: under the KB root, so they must not be able to escape it.
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_component(value: str, *, label: str) -> str:
    """Validate that *value* is a single, traversal-safe path component.

    These tools resolve raw model-supplied strings (``unit``, ``case_set``)
    into filesystem paths under the KB root and deliberately run outside the
    agent sandbox, so a ``../`` here would read/write anywhere. Reject
    anything that isn't a plain name.
    """
    candidate = value.strip()
    if candidate in ("", ".", "..") or not _SAFE_COMPONENT_RE.match(candidate):
        raise ValueError(
            f"{label} must be a simple name (letters, digits, '.', '_', '-', "
            f"no path separators), got {value!r}"
        )
    return candidate


def _split_unit(unit: str) -> tuple[str, str]:
    if "/" not in unit:
        raise ValueError(
            f"unit must be 'module/name' (e.g. 'core-batch/PAYROLL01'), got {unit!r}"
        )
    module, name = unit.split("/", 1)
    return (
        _safe_component(module, label="unit module"),
        _safe_component(name, label="unit name"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# aim_units
# ═══════════════════════════════════════════════════════════════════════════


async def _aim_units(
    action: Annotated[
        Literal[
            "get", "list", "set_phase", "set_project_phase", "record_run", "add_link"
        ],
        Field(description="Which operation to perform."),
    ],
    unit: Annotated[
        str | None,
        Field(
            description=(
                "Unit key as 'module/name' (e.g. 'core-batch/PAYROLL01'). "
                "Required for get/set_phase/record_run."
            )
        ),
    ] = None,
    phase: Annotated[
        str | None,
        Field(
            description=(
                "New phase: inventory|understood|designed|converted|equivalent|"
                "cutover. For set_phase (unit) or set_project_phase (project)."
            )
        ),
    ] = None,
    wave: Annotated[int | None, Field(description="Wave number (set_phase).")] = None,
    assignee: Annotated[
        str | None, Field(description="Claim the unit for this handle (set_phase).")
    ] = None,
    kind: Annotated[
        str | None,
        Field(
            description="Unit kind, e.g. program|job|screen — required to create a new unit (set_phase)."
        ),
    ] = None,
    source_paths: Annotated[
        list[str] | None,
        BeforeValidator(_json_coerce),
        Field(description="Source file paths for this unit (set_phase)."),
    ] = None,
    target_paths: Annotated[
        list[str] | None,
        BeforeValidator(_json_coerce),
        Field(description="Target file paths for this unit (set_phase)."),
    ] = None,
    depends_on: Annotated[
        list[str] | None,
        BeforeValidator(_json_coerce),
        Field(
            description="Other unit keys ('module/name') this one depends on (set_phase)."
        ),
    ] = None,
    complexity: Annotated[
        dict | None,
        BeforeValidator(_json_coerce),
        Field(
            description='Free-form complexity info, e.g. {"score": "medium"} (set_phase).'
        ),
    ] = None,
    expected_revision: Annotated[
        int | None,
        Field(
            description=(
                "Optional optimistic revision for set_phase. The update is "
                "rejected if the KB unit has changed since it was read."
            )
        ),
    ] = None,
    phase_filter: Annotated[
        str | None, Field(description="For action='list' — only units in this phase.")
    ] = None,
    wave_filter: Annotated[
        int | None, Field(description="For action='list' — only units in this wave.")
    ] = None,
    format: Annotated[
        Literal["text", "json"] | None,
        Field(
            description=(
                "For action='list' — 'json' returns "
                '{"units": [...], "count": N} for machine consumers '
                "(workflow tool nodes); default 'text' stays human-readable."
            )
        ),
    ] = None,
    run_kind: Annotated[
        Literal["compare", "convert", "test"] | None,
        Field(description="For action='record_run'."),
    ] = None,
    verdict: Annotated[
        Literal["pass", "fail", "acceptable_diff", "error"] | None,
        Field(description="For action='record_run'."),
    ] = None,
    case_set: Annotated[
        str | None,
        Field(description="For action='record_run' — e.g. 'smoke' or 'full'."),
    ] = None,
    report_path: Annotated[
        str | None,
        Field(description="For action='record_run' — path to the compare report."),
    ] = None,
    stats: Annotated[
        dict | None,
        BeforeValidator(_json_coerce),
        Field(description="For action='record_run' — free-form run stats."),
    ] = None,
    from_ref: Annotated[
        str | None,
        Field(description="For action='add_link', e.g. 'rule:BR-CORE-0001'."),
    ] = None,
    to_ref: Annotated[
        str | None,
        Field(description="For action='add_link', e.g. 'unit:core-batch/PAYROLL01'."),
    ] = None,
    link_kind: Annotated[
        str | None,
        Field(
            description="For action='add_link' — relationship, e.g. 'implements', 'tested_by', 'cites'."
        ),
    ] = None,
    note: Annotated[
        str | None, Field(description="For action='add_link' — free text.")
    ] = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Read and update AIM migration-project state.

    The knowledge-base (KB) repo is the system of record; this tool writes
    there first (frontmatter for units, aim.yaml for project phase) and
    best-effort mirrors into a local index table for fast dashboard
    queries — never the other way around.
    """
    async with db_module.async_session_factory() as db:
        project_id, kb_root = await _resolve_project_and_kb_root(db)

        if action == "get":
            if not unit:
                raise ValueError("action='get' requires 'unit'.")
            module, name = _split_unit(unit)
            result = kb_store.read_unit(kb_root, module, name)
            if result is None:
                return f"No unit doc found at modules/{module}/{name}.md"
            frontmatter, body = result
            return json.dumps(
                {"unit": unit, **frontmatter.model_dump(), "body_preview": body[:500]},
                indent=2,
            )

        if action == "list":
            units = kb_store.list_units(kb_root)
            if phase_filter:
                units = [u for u in units if u[2].phase == phase_filter]
            if wave_filter is not None:
                units = [u for u in units if u[2].wave == wave_filter]
            if format == "json":
                return json.dumps(
                    {
                        "units": [
                            {
                                "module": u_module,
                                "name": u_name,
                                "kind": fm.kind,
                                "phase": fm.phase,
                                "wave": fm.wave,
                                "assignee": fm.assignee,
                            }
                            for u_module, u_name, fm, _ in units
                        ],
                        "count": len(units),
                    }
                )
            if not units:
                filters = []
                if phase_filter:
                    filters.append(f"phase={phase_filter}")
                if wave_filter is not None:
                    filters.append(f"wave={wave_filter}")
                suffix = f" (filter: {', '.join(filters)})" if filters else ""
                return f"No units found in the KB.{suffix}"
            lines = [f"{len(units)} unit(s):"]
            for u_module, u_name, fm, _ in units:
                lines.append(
                    f"- {u_module}/{u_name} [{fm.kind}] phase={fm.phase} "
                    f"wave={fm.wave} assignee={fm.assignee}"
                )
            return "\n".join(lines)

        if action == "set_phase":
            if not unit:
                raise ValueError("action='set_phase' requires 'unit'.")
            if phase is not None and not is_valid_unit_phase(phase):
                raise ValueError(
                    f"Invalid unit phase {phase!r}. Valid phases: "
                    f"{', '.join(VALID_PHASES)}."
                )
            module, name = _split_unit(unit)
            existing = kb_store.read_unit(kb_root, module, name)
            if kind is not None and (kb_root / "aim.yaml").is_file():
                from app.services.aim.rulebook import validate_unit_kind

                try:
                    validate_unit_kind(kb_root, kind)
                except FileNotFoundError:
                    pass
            if existing is None and kind is None:
                raise ValueError(
                    f"Unit {unit} doesn't exist yet — pass 'kind' to create it."
                )
            if existing is None and phase not in (None, "inventory"):
                raise ValueError(
                    f"New unit {unit} must start at phase inventory, not {phase}."
                )

            transition_id: str | None = None
            next_revision = 0
            if existing is not None:
                current, _body = existing
                if (
                    expected_revision is not None
                    and expected_revision != current.revision
                ):
                    raise ValueError(
                        f"Stale unit revision for {unit}: expected {expected_revision}, "
                        f"current {current.revision}. Refresh and retry."
                    )
                next_revision = current.revision + 1
                if phase is not None and phase != current.phase:
                    if project_id is None:
                        raise ValueError(
                            "Cannot transition phases without a resolved AIM project."
                        )
                    workflow_execution_id = _current_workflow_execution_id()
                    workflow_name = await _current_workflow_name(db)
                    compare_pass = False
                    conversion_verified = False
                    understanding_verified = False
                    pass_run: AimRun | None = None
                    conversion_evidence: Path | None = None
                    understanding_evidence: Path | None = None
                    if phase == "understood" and workflow_execution_id:
                        from app.services.aim.understanding import (
                            has_understanding_evidence,
                            understanding_evidence_path,
                        )

                        understanding_evidence = understanding_evidence_path(
                            kb_root, unit, workflow_execution_id
                        )
                        understanding_verified = has_understanding_evidence(
                            kb_root, unit, workflow_execution_id
                        )
                    if (
                        phase == "equivalent"
                        and project_id is not None
                        and workflow_execution_id
                    ):
                        indexed_unit = (
                            await db.exec(
                                select(AimUnit).where(
                                    AimUnit.project_id == project_id,
                                    AimUnit.module == module,
                                    AimUnit.name == name,
                                )
                            )
                        ).first()
                        if indexed_unit is not None:
                            pass_run = (
                                await db.exec(
                                    select(AimRun).where(
                                        AimRun.unit_id == indexed_unit.id,
                                        AimRun.kind == "compare",
                                        AimRun.verdict == "pass",
                                        AimRun.workflow_execution_id
                                        == workflow_execution_id,
                                    )
                                )
                            ).first()
                            compare_pass = pass_run is not None
                    if phase == "converted" and workflow_execution_id:
                        from app.services.aim.verification import (
                            conversion_evidence_path,
                            has_conversion_evidence,
                        )

                        conversion_evidence = conversion_evidence_path(
                            kb_root, unit, workflow_execution_id
                        )
                        conversion_verified = has_conversion_evidence(
                            kb_root, unit, workflow_execution_id
                        )
                    readiness = evaluate_transition(
                        kb_root,
                        module,
                        name,
                        phase,
                        workflow_name=workflow_name,
                        understanding_verified=understanding_verified,
                        compare_pass=compare_pass,
                        conversion_verified=conversion_verified,
                    )
                    if not readiness.allowed:
                        raise ValueError(
                            f"Cannot transition {unit}: "
                            + "; ".join(readiness.blockers)
                        )
                    assert workflow_execution_id is not None
                    assert workflow_name is not None
                    claim = (
                        await db.exec(
                            select(AimClaim).where(
                                AimClaim.unit_id
                                == (
                                    select(AimUnit.id)
                                    .where(
                                        AimUnit.project_id == project_id,
                                        AimUnit.module == module,
                                        AimUnit.name == name,
                                    )
                                    .scalar_subquery()
                                ),
                                AimClaim.workflow_execution_id
                                == UUID(workflow_execution_id),
                                AimClaim.lease_expires_at > datetime.now(timezone.utc),
                            )
                        )
                    ).first()
                    if claim is None:
                        raise ValueError(
                            f"Cannot transition {unit}: workflow execution does "
                            "not hold an active unit claim."
                        )
                    evidence_refs: list[str] = []
                    if phase == "understood":
                        evidence_refs.append(f"modules/{module}/{name}.md")
                        if understanding_evidence is not None:
                            evidence_refs.append(
                                understanding_evidence.relative_to(kb_root).as_posix()
                            )
                    elif phase == "designed":
                        mapping_path = resolve_mapping_path(kb_root, module, name)
                        if mapping_path is not None:
                            evidence_refs.append(
                                mapping_path.relative_to(kb_root).as_posix()
                            )
                    elif phase == "converted" and conversion_evidence is not None:
                        evidence_refs.append(
                            conversion_evidence.relative_to(kb_root).as_posix()
                        )
                    elif phase == "equivalent" and pass_run is not None:
                        evidence_refs.append(f"run:{pass_run.id}")
                        if pass_run.report_path:
                            evidence_refs.append(pass_run.report_path)
                    elif phase == "cutover" and current.wave is not None:
                        evidence_refs.append(f"state/cutover/wave-{current.wave}.yaml")
                    raw_sid = _state.metadata.get("session_id") if _state else None
                    transition_id = kb_store.write_transition_event(
                        kb_root,
                        module,
                        name,
                        from_phase=current.phase,
                        to_phase=phase,
                        revision=next_revision,
                        workflow_name=workflow_name,
                        workflow_execution_id=workflow_execution_id,
                        session_id=raw_sid,
                        evidence_refs=evidence_refs,
                    )
            doc_path = kb_store.write_unit(
                kb_root,
                module,
                name,
                kind=kind,
                phase=phase,
                wave=wave,
                assignee=assignee,
                source_paths=source_paths,
                target_paths=target_paths,
                depends_on=depends_on,
                complexity=complexity,
                revision=next_revision,
                last_transition_id=transition_id,
            )
            frontmatter, _ = kb_store.read_unit(kb_root, module, name)
            if transition_id is not None:
                kb_store.sync_project_phase_from_units(kb_root)
            if project_id is not None:
                rel_path = str(doc_path.relative_to(kb_root))
                await upsert_unit(db, project_id, module, name, frontmatter, rel_path)
                await db.commit()
                suffix = ""
            else:
                suffix = " (no AIM project resolved — KB updated, DB index not synced)"
            return f"Updated {unit}: phase={frontmatter.phase}{suffix}"

        if action == "set_project_phase":
            if not phase:
                raise ValueError("action='set_project_phase' requires 'phase'.")
            if not is_valid_project_phase(phase):
                raise ValueError(
                    f"Invalid project phase {phase!r}. Valid phases: "
                    f"{', '.join(VALID_PROJECT_PHASES)}."
                )
            kb_store.write_manifest_phase(kb_root, phase)
            return f"Project phase set to '{phase}' in {kb_root / 'aim.yaml'}"

        if action == "record_run":
            if not unit or not run_kind or not verdict:
                raise ValueError(
                    "action='record_run' requires 'unit', 'run_kind', and 'verdict'."
                )
            if project_id is None:
                return (
                    "Cannot record a run: no AIM project resolved for this "
                    "workspace. Open this session against a project with an "
                    "'aim' role mapping."
                )
            module, name = _split_unit(unit)
            row = (
                await db.exec(
                    select(AimUnit).where(
                        AimUnit.project_id == project_id,
                        AimUnit.module == module,
                        AimUnit.name == name,
                    )
                )
            ).first()
            if row is None:
                return (
                    f"Cannot record a run: unit {unit} is not indexed yet "
                    "(run action='set_phase' first)."
                )
            raw_sid = _state.metadata.get("session_id") if _state else None
            run_id = uuid7()
            created_at = datetime.now(timezone.utc)
            raw_sid = _state.metadata.get("session_id") if _state else None
            session_id = UUID(raw_sid) if raw_sid else None
            workflow_execution_id = _current_workflow_execution_id()
            kb_store.write_run_meta(
                kb_root,
                module,
                name,
                run_id=run_id,
                kind=run_kind,
                verdict=verdict,
                case_set=case_set,
                stats=stats or {},
                report_path=report_path,
                session_id=session_id,
                workflow_execution_id=workflow_execution_id,
                created_at=created_at,
            )
            run = AimRun(
                id=run_id,
                unit_id=row.id,
                kind=run_kind,
                verdict=verdict,
                case_set=case_set,
                stats=stats or {},
                report_path=report_path,
                session_id=session_id,
                workflow_execution_id=workflow_execution_id,
                created_at=created_at,
            )
            db.add(run)
            await db.commit()
            return f"Recorded {run_kind} run for {unit}: verdict={verdict}"

        if action == "add_link":
            if not from_ref or not to_ref or not link_kind:
                raise ValueError(
                    "action='add_link' requires 'from_ref', 'to_ref', and 'link_kind'."
                )
            if project_id is None:
                return "Cannot add a link: no AIM project resolved for this workspace."
            link_id = uuid7()
            created_at = datetime.now(timezone.utc)
            kb_store.write_link_meta(
                kb_root,
                link_id=link_id,
                from_ref=from_ref,
                to_ref=to_ref,
                kind=link_kind,
                note=note,
                created_at=created_at,
            )
            link = AimLink(
                id=link_id,
                project_id=project_id,
                from_ref=from_ref,
                to_ref=to_ref,
                kind=link_kind,
                note=note,
                created_at=created_at,
            )
            db.add(link)
            await db.commit()
            return f"Linked {from_ref} -> {to_ref} ({link_kind})"

        raise ValueError(
            f"Unknown action: {action!r}"
        )  # pragma: no cover — Literal-exhaustive


aim_units = Tool(
    _aim_units,
    name="aim_units",
    description=(
        "Read and update AIM migration-project state: get/list units, set a "
        "unit's phase/wave/assignee, set the project's overall phase, record "
        "a compare/convert/test run, or add a traceability link. The "
        "knowledge-base repo is always the source of truth."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Inspect or update AIM migration units, phases, runs, and traceability links.",
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_readiness
# ═══════════════════════════════════════════════════════════════════════════


async def _aim_readiness(
    pipeline: Annotated[str, Field(description="AIM workflow name to evaluate.")],
    unit: Annotated[
        str | None, Field(description="Optional module/name unit input.")
    ] = None,
    wave: Annotated[int | None, Field(description="Optional wave input.")] = None,
    case_set: Annotated[
        str | None, Field(description="Optional golden case set input.")
    ] = None,
) -> str:
    async with db_module.async_session_factory() as db:
        _project_id, kb_root = await _resolve_project_and_kb_root(db)
    result = evaluate_pipeline(
        kb_root,
        pipeline,
        unit=unit,
        wave=wave,
        case_set=case_set,
    )
    return json.dumps(result.to_dict())


aim_readiness = Tool(
    _aim_readiness,
    name="aim_readiness",
    description=(
        "Evaluate whether an AIM pipeline is ready to start. Returns "
        "ready|blocked plus deterministic blockers and selected units."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Check AIM pipeline prerequisites and blockers.",
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_understanding
# ═══════════════════════════════════════════════════════════════════════════


async def _aim_understanding(
    action: Annotated[
        Literal["snapshot", "verify"], Field(description="Evidence operation.")
    ],
    units: Annotated[
        list[str],
        BeforeValidator(_json_coerce),
        Field(description="Dependency-ordered module/name unit list."),
    ],
    baseline: Annotated[
        dict[str, str] | None,
        BeforeValidator(_json_coerce),
        Field(description="Snapshot digests returned by the snapshot action."),
    ] = None,
) -> str:
    execution_id = _current_workflow_execution_id()
    if not execution_id:
        raise ValueError("AIM understanding evidence requires a workflow execution.")
    async with db_module.async_session_factory() as db:
        _project_id, kb_root = await _resolve_project_and_kb_root(db)
    from app.services.aim.understanding import (
        snapshot_understanding,
        verify_understanding,
    )

    if action == "snapshot":
        return json.dumps(
            {
                "status": "snapshotted",
                "units": units,
                "digests": snapshot_understanding(kb_root, units),
            }
        )
    if baseline is None:
        raise ValueError("action='verify' requires baseline digests.")
    paths = verify_understanding(kb_root, units, baseline, execution_id=execution_id)
    return json.dumps(
        {
            "status": "pass",
            "count": len(paths),
            "evidence_paths": [str(path.relative_to(kb_root)) for path in paths],
        }
    )


aim_understanding = Tool(
    _aim_understanding,
    name="aim_understanding",
    description=(
        "Snapshot AIM unit documentation and verify same-execution understanding "
        "changes before phase transition."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Verify same-attempt AIM understanding evidence.",
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_claim
# ═══════════════════════════════════════════════════════════════════════════


async def _aim_claim(
    action: Annotated[
        Literal["acquire", "release", "list"], Field(description="Claim operation.")
    ],
    unit: Annotated[
        str | None, Field(description="Optional module/name unit scope.")
    ] = None,
    units: Annotated[
        list[str] | None,
        BeforeValidator(_json_coerce),
        Field(description="Optional explicit module/name unit list."),
    ] = None,
    wave: Annotated[int | None, Field(description="Optional whole-wave scope.")] = None,
    lease_seconds: Annotated[
        int, Field(description="Lease duration in seconds, 60..14400.")
    ] = 7200,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    execution_id_raw = _current_workflow_execution_id()
    if action != "list" and not execution_id_raw:
        raise ValueError("AIM claims may only be changed by workflow tool nodes.")
    try:
        execution_id = UUID(execution_id_raw) if execution_id_raw else None
    except ValueError as exc:
        raise ValueError("Workflow execution id is not a UUID.") from exc
    lease_seconds = max(60, min(lease_seconds, 14400))

    async with db_module.async_session_factory() as db:
        project_id, _kb_root = await _resolve_project_and_kb_root(db)
        if project_id is None:
            raise ValueError("AIM claims require a resolved AIM project.")
        query = select(AimUnit).where(AimUnit.project_id == project_id)
        requested_keys: set[tuple[str, str]] | None = None
        if units:
            requested_keys = {_split_unit(key) for key in units}
        elif unit:
            module, name = _split_unit(unit)
            query = query.where(AimUnit.module == module, AimUnit.name == name)
        elif wave is not None:
            query = query.where(AimUnit.wave == wave)
        elif action != "list":
            raise ValueError("action acquire/release requires unit, units, or wave.")
        matched_units = (await db.exec(query)).all()
        if requested_keys is not None:
            matched_units = [
                row for row in matched_units if (row.module, row.name) in requested_keys
            ]
        if action != "list" and not matched_units:
            raise ValueError("No AIM units matched the requested claim scope.")

        now = datetime.now(timezone.utc)
        existing_rows = (
            (
                await db.exec(
                    select(AimClaim).where(
                        AimClaim.project_id == project_id,
                        AimClaim.unit_id.in_([row.id for row in matched_units]),
                    )
                )
            ).all()
            if matched_units
            else []
        )
        by_unit = {row.unit_id: row for row in existing_rows}

        if action == "list":
            active = [row for row in existing_rows if row.lease_expires_at > now]
            return json.dumps(
                {
                    "status": "ok",
                    "claims": [
                        {
                            "unit_id": str(row.unit_id),
                            "workflow_execution_id": str(row.workflow_execution_id),
                            "workflow_name": row.workflow_name,
                            "lease_expires_at": row.lease_expires_at.isoformat(),
                        }
                        for row in active
                    ],
                }
            )

        assert execution_id is not None
        workflow_name = await _current_workflow_name(db)
        if not workflow_name:
            raise ValueError("Workflow execution was not found.")
        raw_sid = _state.metadata.get("session_id") if _state else None
        session_id = UUID(raw_sid) if raw_sid else None

        if action == "acquire":
            blocked = [
                row
                for row in existing_rows
                if row.lease_expires_at > now
                and row.workflow_execution_id != execution_id
            ]
            if blocked:
                return json.dumps(
                    {
                        "status": "blocked",
                        "blockers": [
                            "unit is owned by workflow execution "
                            f"{row.workflow_execution_id} until "
                            f"{row.lease_expires_at.isoformat()}"
                            for row in blocked
                        ],
                    }
                )
            expires_at = now + timedelta(seconds=lease_seconds)
            for unit_row in matched_units:
                claim = by_unit.get(unit_row.id)
                if claim is None:
                    claim = AimClaim(
                        project_id=project_id,
                        unit_id=unit_row.id,
                        workflow_execution_id=execution_id,
                        workflow_name=workflow_name,
                        session_id=session_id,
                        lease_expires_at=expires_at,
                    )
                else:
                    claim.workflow_execution_id = execution_id
                    claim.workflow_name = workflow_name
                    claim.session_id = session_id
                    claim.lease_expires_at = expires_at
                db.add(claim)
            await db.commit()
            return json.dumps(
                {
                    "status": "acquired",
                    "count": len(matched_units),
                    "lease_expires_at": expires_at.isoformat(),
                }
            )

        not_owned = [
            row for row in existing_rows if row.workflow_execution_id != execution_id
        ]
        if not_owned:
            raise ValueError(
                "Claim is owned by workflow execution "
                f"{not_owned[0].workflow_execution_id}."
            )
        for row in existing_rows:
            await db.delete(row)
        await db.commit()
        return json.dumps({"status": "released", "count": len(existing_rows)})


aim_claim = Tool(
    _aim_claim,
    name="aim_claim",
    description=(
        "Acquire, release, or list exclusive expiring AIM unit/wave claims. "
        "Mutation is restricted to workflow tool nodes."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Acquire or release exclusive AIM migration work.",
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_capture
# ═══════════════════════════════════════════════════════════════════════════


async def _aim_capture(
    unit: Annotated[str, Field(description="Unit key as module/name.")],
    case_set: Annotated[
        str, Field(description="Golden case set to capture from the legacy source.")
    ] = "smoke",
    overwrite: Annotated[
        bool,
        Field(
            description="Replace an existing expected baseline after explicit approval."
        ),
    ] = False,
) -> str:
    from app.services.aim.runners import capture_legacy_case

    async with db_module.async_session_factory() as db:
        _project_id, kb_root = await _resolve_project_and_kb_root(db)
    result = await capture_legacy_case(
        kb_root,
        unit,
        case_set,
        overwrite=overwrite,
    )
    module, name = unit.split("/", 1)
    expected_dir = (
        kb_root / "golden" / "units" / module / name / "cases" / case_set / "expected"
    )
    return json.dumps(
        {
            "status": "captured",
            "unit": result.unit,
            "case_set": result.case_set,
            "expected_dir": str(expected_dir),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )


aim_capture = Tool(
    _aim_capture,
    name="aim_capture",
    description=(
        "Run the rulebook legacy runner into staging and promote fresh output "
        "to a validated golden case. Existing expected output is protected "
        "unless overwrite is explicitly approved."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Capture a trusted legacy golden baseline.",
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_execute
# ═══════════════════════════════════════════════════════════════════════════


async def _aim_execute(
    unit: Annotated[str, Field(description="Unit key as module/name.")],
    case_set: Annotated[
        str, Field(description="Golden case set to execute.")
    ] = "smoke",
) -> str:
    from app.services.aim.runners import execute_target_case

    async with db_module.async_session_factory() as db:
        _project_id, kb_root = await _resolve_project_and_kb_root(db)
    result = await execute_target_case(kb_root, unit, case_set)
    return json.dumps(
        {
            "status": "succeeded",
            "unit": result.unit,
            "case_set": result.case_set,
            "actual_dir": str(result.actual_dir),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )


aim_execute = Tool(
    _aim_execute,
    name="aim_execute",
    description=(
        "Execute a rulebook target runner for one golden case set, clearing "
        "stale actuals and failing unless fresh output files are produced."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Run a migrated unit against a golden case set.",
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_verify
# ═══════════════════════════════════════════════════════════════════════════


async def _aim_verify(
    unit: Annotated[str, Field(description="Unit key as module/name.")],
) -> str:
    from app.services.aim.project import resolve_target_workspace_path
    from app.services.aim.verification import verify_target_conversion

    execution_id = _current_workflow_execution_id()
    if not execution_id:
        raise ValueError(
            "AIM target verification may only run in a workflow tool node."
        )
    async with db_module.async_session_factory() as db:
        project_id, kb_root = await _resolve_project_and_kb_root(db)
        if project_id is None:
            raise ValueError("AIM target verification requires a resolved project.")
        project = await db.get(CodingProject, project_id)
        if project is None:
            raise ValueError("AIM project was not found.")
        target_path = await resolve_target_workspace_path(db, project)
    if not target_path:
        raise ValueError("AIM project has no target workspace.")
    evidence = await verify_target_conversion(
        kb_root,
        Path(target_path),
        unit,
        execution_id=execution_id,
    )
    return json.dumps({"status": "pass", "unit": unit, "evidence_path": str(evidence)})


aim_verify = Tool(
    _aim_verify,
    name="aim_verify",
    description=(
        "Run a unit's deterministic target verification command and write "
        "same-attempt conversion evidence required for phase transition."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Verify a converted unit build and tests.",
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_compare
# ═══════════════════════════════════════════════════════════════════════════


async def _resolve_canonical_profile(
    kb_root: Path, profile_override: str | None
) -> CanonicalProfile:
    # Read the manifest regardless of a profile override: the override only
    # names WHICH profile to load, not where from. Canonicalizers always come
    # from the KB-local rulebook pinned by aim.yaml.
    profile_id = profile_override
    manifest_found = False
    try:
        manifest = kb_store.read_manifest(kb_root)
        manifest_found = True
        if profile_id is None:
            profile_id = manifest.compare_default_profile
    except FileNotFoundError:
        if profile_id is None:
            profile_id = "default"
    profile_id = _safe_component(profile_id or "default", label="profile")

    rulebook_dir: Path | None
    if manifest_found:
        from app.services.aim.rulebook import resolve_rulebook_dir

        rulebook_dir = resolve_rulebook_dir(kb_root)
    else:
        rulebook_dir = None

    if rulebook_dir is not None:
        canonicalizer_path = rulebook_dir / "canonicalizers" / f"{profile_id}.yaml"
        if canonicalizer_path.exists():
            return load_profile(canonicalizer_path)
    if manifest_found:
        location = (
            str(rulebook_dir / "canonicalizers" / f"{profile_id}.yaml")
            if rulebook_dir is not None
            else "the KB-local rulebook"
        )
        raise FileNotFoundError(
            f"Canonicalizer profile {profile_id!r} was not found in {location}"
        )
    return CanonicalProfile(id=profile_id or "default")


def _compare_error(kind: str, message: str) -> str:
    return json.dumps(
        {
            "verdict": "error",
            "diff_count": 0,
            "clusters": [],
            "report_path": None,
            "error_kind": kind,
            "error": message,
        }
    )


async def _aim_compare(
    unit: Annotated[
        str,
        Field(description="Unit key as 'module/name', e.g. 'core-batch/PAYROLL01'."),
    ],
    case_set: Annotated[
        str,
        Field(
            description="Golden case id under golden/units/<module>/<name>/cases/, e.g. 'smoke' or 'full'."
        ),
    ] = "smoke",
    profile: Annotated[
        str | None,
        Field(
            description="Canonicalizer profile id override (defaults to the KB's aim.yaml compare_default_profile)."
        ),
    ] = None,
    actual_dir: Annotated[
        str | None,
        Field(
            description=(
                "Path to the actual output to compare (absolute, or relative to the "
                "KB root). Defaults to '.aim-actuals/<module>/<name>/<case_set>/'."
            )
        ),
    ] = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Deterministically compare a migration unit's actual output against its
    golden master, canonicalizing both sides first per the project's
    rulebook profile. Returns a compact JSON verdict — judgment about
    whether any diff is a real defect belongs to a separate triage step,
    not this tool.
    """
    async with db_module.async_session_factory() as db:
        project_id, kb_root = await _resolve_project_and_kb_root(db)
        module, name = _split_unit(unit)
        try:
            case_set = _safe_component(case_set, label="case_set")
        except ValueError as exc:
            return _compare_error("invalid_input", str(exc))

        golden_case_dir = (
            kb_root / "golden" / "units" / module / name / "cases" / case_set
        )
        expected_dir = golden_case_dir / "expected"
        if not expected_dir.is_dir():
            return _compare_error(
                "missing_golden_case", f"No golden case at {expected_dir}"
            )

        from app.services.aim.golden import GoldenCaseError, load_golden_case_meta

        try:
            golden_meta = load_golden_case_meta(golden_case_dir)
        except GoldenCaseError as exc:
            return _compare_error(exc.kind, str(exc))
        if (
            profile
            and golden_meta.canonicalizer_profile
            and profile != golden_meta.canonicalizer_profile
        ):
            return _compare_error(
                "canonicalizer_mismatch",
                f"Requested profile {profile!r} does not match golden metadata "
                f"profile {golden_meta.canonicalizer_profile!r}",
            )

        resolved_actual_dir = (
            Path(actual_dir)
            if actual_dir
            else Path(".aim-actuals") / module / name / case_set
        )
        # A relative actual_dir is resolved under (and confined to) the KB
        # root — the default already is; a caller-supplied ``../`` must not
        # escape. An absolute path is allowed by contract (e.g. a build
        # output dir in the target workspace).
        if not resolved_actual_dir.is_absolute():
            resolved_actual_dir = (kb_root / resolved_actual_dir).resolve()
            kb_root_resolved = kb_root.resolve()
            if not resolved_actual_dir.is_relative_to(kb_root_resolved):
                return _compare_error("invalid_input", "actual_dir escapes the KB root")

        try:
            canonical_profile = await _resolve_canonical_profile(
                kb_root,
                profile or golden_meta.canonicalizer_profile,
            )
        except (FileNotFoundError, ValueError, OSError) as exc:
            return _compare_error("missing_canonicalizer", str(exc))
        report = compare_dirs(expected_dir, resolved_actual_dir, canonical_profile)

        run_id = uuid7()
        report_dir = kb_root / "runs" / module / name / str(run_id)
        json_path, _md_path = write_report(report, report_dir)
        # Stored KB-relative, not absolute: the KB workspace's checkout path
        # is a per-machine/per-session detail, but "runs/.../report.json"
        # inside it is stable — record_run readers resolve it against
        # whatever the project's KB path is *now* (see get_aim_run).
        report_rel_path = str(json_path.relative_to(kb_root))

        raw_sid = _state.metadata.get("session_id") if _state else None
        session_id = UUID(raw_sid) if raw_sid else None
        workflow_execution_id = _current_workflow_execution_id()
        created_at = datetime.now(timezone.utc)
        kb_store.write_run_meta(
            kb_root,
            module,
            name,
            run_id=run_id,
            kind="compare",
            verdict=report.verdict,
            case_set=case_set,
            stats={"diff_count": report.diff_count},
            report_path=report_rel_path,
            session_id=session_id,
            workflow_execution_id=workflow_execution_id,
            created_at=created_at,
        )

        if project_id is not None:
            row = (
                await db.exec(
                    select(AimUnit).where(
                        AimUnit.project_id == project_id,
                        AimUnit.module == module,
                        AimUnit.name == name,
                    )
                )
            ).first()
            if row is not None:
                run_verdict = (
                    report.verdict if report.verdict in ("pass", "fail") else "error"
                )
                run = AimRun(
                    id=run_id,
                    unit_id=row.id,
                    kind="compare",
                    verdict=run_verdict,
                    case_set=case_set,
                    stats={"diff_count": report.diff_count},
                    report_path=report_rel_path,
                    session_id=session_id,
                    workflow_execution_id=workflow_execution_id,
                    created_at=created_at,
                )
                db.add(run)
                await db.commit()

        result = report.to_dict()
        result["report_path"] = report_rel_path
        result["golden"] = golden_meta.model_dump(mode="json")
        result["canonicalizer_profile"] = canonical_profile.id
        return json.dumps(result)


aim_compare = Tool(
    _aim_compare,
    name="aim_compare",
    description=(
        "Deterministically compare a migration unit's actual output against "
        "its golden master for a given case set, after canonicalizing both "
        "sides. Returns verdict (pass|fail|error), diff_count, and diff "
        "clusters as JSON; writes a full report next to the golden case."
    ),
    tiers=("aim",),
    deferred=True,
    deferred_summary="Compare a migrated unit's output with its canonical golden master.",
)
