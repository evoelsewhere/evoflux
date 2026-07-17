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
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid7

from pydantic import BeforeValidator, Field
from sqlmodel import select

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, Tool
from app.agent.state import AgentState
from app.core import db as db_module
from app.models.aim import AimLink, AimRun, AimUnit
from app.models.chat import CodingProject, CodingWorkspace
from app.services import code_graph_service as code_svc
from app.services import coding_project_service as proj_svc
from app.services.aim import kb_store
from app.services.aim.canonicalize import load_profile
from app.services.aim.compare import compare_dirs, write_report
from app.services.aim.models import CanonicalProfile
from app.services.aim.reindex import upsert_unit


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


def _split_unit(unit: str) -> tuple[str, str]:
    if "/" not in unit:
        raise ValueError(
            f"unit must be 'module/name' (e.g. 'core-batch/PAYROLL01'), got {unit!r}"
        )
    module, name = unit.split("/", 1)
    return module, name


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
            module, name = _split_unit(unit)
            existing = kb_store.read_unit(kb_root, module, name)
            if existing is None and kind is None:
                raise ValueError(
                    f"Unit {unit} doesn't exist yet — pass 'kind' to create it."
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
            )
            frontmatter, _ = kb_store.read_unit(kb_root, module, name)
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
            run = AimRun(
                unit_id=row.id,
                kind=run_kind,
                verdict=verdict,
                case_set=case_set,
                stats=stats or {},
                report_path=report_path,
                session_id=UUID(raw_sid) if raw_sid else None,
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
            link = AimLink(
                project_id=project_id,
                from_ref=from_ref,
                to_ref=to_ref,
                kind=link_kind,
                note=note,
            )
            db.add(link)
            await db.commit()
            return f"Linked {from_ref} -> {to_ref} ({link_kind})"

        raise ValueError(f"Unknown action: {action!r}")  # pragma: no cover — Literal-exhaustive


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
)


# ═══════════════════════════════════════════════════════════════════════════
# aim_compare
# ═══════════════════════════════════════════════════════════════════════════


def _builtin_rulebooks_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "builtin_aim" / "rulebooks"


async def _resolve_canonical_profile(
    kb_root: Path, profile_override: str | None, rulebook_dir_override: str | None
) -> CanonicalProfile:
    profile_id = profile_override
    rulebook_id: str | None = None
    if profile_id is None:
        try:
            manifest = kb_store.read_manifest(kb_root)
            profile_id = manifest.compare_default_profile
            rulebook_id = manifest.rulebook.id
        except FileNotFoundError:
            profile_id = "default"

    rulebook_dir = (
        Path(rulebook_dir_override)
        if rulebook_dir_override
        else (_builtin_rulebooks_dir() / rulebook_id if rulebook_id else None)
    )
    if rulebook_dir is not None:
        canonicalizer_path = rulebook_dir / "canonicalizers" / f"{profile_id}.yaml"
        if canonicalizer_path.exists():
            return load_profile(canonicalizer_path)
    return CanonicalProfile(id=profile_id or "default")


async def _aim_compare(
    unit: Annotated[
        str, Field(description="Unit key as 'module/name', e.g. 'core-batch/PAYROLL01'.")
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
    rulebook_dir: Annotated[
        str | None,
        Field(
            description="Override path to the rulebook directory containing canonicalizers/ (defaults to the bundled AIM rulebook named in aim.yaml)."
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

        golden_case_dir = (
            kb_root / "golden" / "units" / module / name / "cases" / case_set
        )
        expected_dir = golden_case_dir / "expected"
        if not expected_dir.is_dir():
            return json.dumps(
                {
                    "verdict": "error",
                    "diff_count": 0,
                    "clusters": [],
                    "error": f"No golden case at {expected_dir}",
                }
            )

        resolved_actual_dir = (
            Path(actual_dir)
            if actual_dir
            else Path(".aim-actuals") / module / name / case_set
        )
        if not resolved_actual_dir.is_absolute():
            resolved_actual_dir = kb_root / resolved_actual_dir

        canonical_profile = await _resolve_canonical_profile(
            kb_root, profile, rulebook_dir
        )
        report = compare_dirs(expected_dir, resolved_actual_dir, canonical_profile)

        report_dir = kb_root / "runs" / module / name / uuid7().hex
        json_path, _md_path = write_report(report, report_dir)

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
                run_verdict = report.verdict if report.verdict in ("pass", "fail") else "error"
                raw_sid = _state.metadata.get("session_id") if _state else None
                run = AimRun(
                    unit_id=row.id,
                    kind="compare",
                    verdict=run_verdict,
                    case_set=case_set,
                    stats={"diff_count": report.diff_count},
                    report_path=str(json_path),
                    session_id=UUID(raw_sid) if raw_sid else None,
                )
                db.add(run)
                await db.commit()

        result = report.to_dict()
        result["report_path"] = str(json_path)
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
)
