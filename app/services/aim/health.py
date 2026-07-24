"""Operational health checks for an AIM migration project."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingProject
from app.services.aim import kb_store
from app.services.aim.project import (
    resolve_kb_workspace_path,
    resolve_source_workspace_paths,
    resolve_target_workspace_path,
)
from app.services.aim.rulebook import (
    read_rulebook_manifest,
    resolve_rulebook_dir,
    resolve_rulebook_path,
)

HealthStatus = Literal["pass", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class HealthCheck:
    id: str
    label: str
    status: HealthStatus
    message: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ProjectHealth:
    status: Literal["ready", "degraded", "blocked"]
    checks: tuple[HealthCheck, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "failed_count": sum(check.status == "fail" for check in self.checks),
            "warning_count": sum(check.status == "warn" for check in self.checks),
        }


def _git_check(label: str, path: Path) -> HealthCheck:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return HealthCheck(
            id=f"git_{label}",
            label=f"{label.upper()} git",
            status="warn",
            message=f"Git status unavailable: {exc}",
        )
    if result.returncode != 0:
        return HealthCheck(
            id=f"git_{label}",
            label=f"{label.upper()} git",
            status="warn",
            message="Directory is not a git worktree.",
        )
    changes = [line for line in result.stdout.splitlines() if line.strip()]
    if changes:
        return HealthCheck(
            id=f"git_{label}",
            label=f"{label.upper()} git",
            status="warn",
            message=f"{len(changes)} uncommitted path(s).",
        )
    return HealthCheck(
        id=f"git_{label}",
        label=f"{label.upper()} git",
        status="pass",
        message="Worktree is clean.",
    )


async def evaluate_project_health(
    db: AsyncSession, project: CodingProject
) -> ProjectHealth:
    checks: list[HealthCheck] = []
    source_paths = [
        Path(path) for path in await resolve_source_workspace_paths(db, project)
    ]
    target_raw = await resolve_target_workspace_path(db, project)
    kb_raw = await resolve_kb_workspace_path(db, project)
    target = Path(target_raw) if target_raw else None
    kb_root = Path(kb_raw) if kb_raw else None

    missing_sources = [str(path) for path in source_paths if not path.is_dir()]
    if not source_paths or missing_sources:
        checks.append(
            HealthCheck(
                id="sources",
                label="Source estate",
                status="fail",
                message=(
                    "No source repositories are mapped."
                    if not source_paths
                    else "Missing source repositories: " + ", ".join(missing_sources)
                ),
            )
        )
    else:
        checks.append(
            HealthCheck(
                id="sources",
                label="Source estate",
                status="pass",
                message=f"{len(source_paths)} source repository path(s) are available.",
            )
        )

    target_files = (
        [path for path in target.iterdir() if path.name != ".git"]
        if target is not None and target.is_dir()
        else []
    )
    checks.append(
        HealthCheck(
            id="target_base",
            label="Target base",
            status="pass" if target_files else "fail",
            message=(
                f"Target base contains {len(target_files)} top-level item(s)."
                if target_files
                else "Target base is missing or empty. Scaffold build, conventions, and CI first."
            ),
        )
    )

    manifest = None
    if kb_root is None or not kb_root.is_dir():
        checks.append(
            HealthCheck(
                id="kb",
                label="Knowledge base",
                status="fail",
                message="KB repository is not available on this machine.",
            )
        )
    else:
        try:
            manifest = kb_store.read_manifest(kb_root)
            checks.append(
                HealthCheck(
                    id="kb",
                    label="Knowledge base",
                    status="pass" if manifest.state_schema >= 2 else "warn",
                    message=(
                        f"State schema {manifest.state_schema} is active."
                        if manifest.state_schema >= 2
                        else "Legacy state schema: transitions are not fully verifiable."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                HealthCheck(
                    id="kb",
                    label="Knowledge base",
                    status="fail",
                    message=f"aim.yaml is invalid: {exc}",
                )
            )

    try:
        pack = resolve_rulebook_dir(kb_root) if kb_root is not None else None
        pack_model = read_rulebook_manifest(kb_root) if kb_root is not None else None
        pack_manifest = pack_model.model_dump() if pack_model is not None else {}
    except (FileNotFoundError, ValueError) as exc:
        pack = None
        pack_manifest = {}
        rulebook_error = str(exc)
    else:
        rulebook_error = ""
    checks.append(
        HealthCheck(
            id="rulebook",
            label="Rulebook",
            status="pass" if pack is not None and pack_manifest else "fail",
            message=(
                f"Rulebook {manifest.rulebook.id} v{manifest.rulebook.version} resolved."
                if pack is not None and pack_manifest and manifest is not None
                else rulebook_error or "KB-local rulebook manifest is missing."
            ),
        )
    )

    capabilities = pack_manifest.get("capabilities")
    incomplete_capabilities = (
        [
            f"{name}={status}"
            for name, status in capabilities.items()
            if status != "ready"
        ]
        if isinstance(capabilities, dict)
        else ["capabilities are not declared"]
    )
    checks.append(
        HealthCheck(
            id="capabilities",
            label="Rulebook capabilities",
            status="fail" if incomplete_capabilities else "pass",
            message=(
                "Not production-ready: " + ", ".join(incomplete_capabilities)
                if incomplete_capabilities
                else "All lifecycle capabilities are ready."
            ),
        )
    )

    profile_path = (
        pack / "canonicalizers" / f"{manifest.compare_default_profile}.yaml"
        if pack is not None and manifest is not None
        else None
    )
    checks.append(
        HealthCheck(
            id="canonicalizer",
            label="Canonicalizer",
            status="pass"
            if profile_path is not None and profile_path.is_file()
            else "fail",
            message=(
                f"Profile {manifest.compare_default_profile!r} is available."
                if profile_path is not None
                and profile_path.is_file()
                and manifest is not None
                else "Pinned canonicalizer profile is missing."
            ),
        )
    )

    runner_declarations = pack_manifest.get("runners")
    runner_errors: list[str] = []
    if not isinstance(runner_declarations, dict) or not runner_declarations:
        runner_errors.append("rulebook declares no legacy/target runners")
    elif kb_root is not None:
        for role, declared_path in runner_declarations.items():
            try:
                path = resolve_rulebook_path(kb_root, str(declared_path))
            except ValueError:
                runner_errors.append(f"{role} runner path is invalid")
                continue
            if not path.is_file():
                runner_errors.append(f"{role} runner is missing")
                continue
            try:
                content = path.read_text(encoding="utf-8").lower()
            except (OSError, UnicodeDecodeError):
                runner_errors.append(f"{role} runner is unreadable")
                continue
            if (
                "todo:" in content
                or "run_target stub" in content
                or "run_legacy stub" in content
            ):
                runner_errors.append(f"{role} runner is still a template")
    checks.append(
        HealthCheck(
            id="runners",
            label="Execution runners",
            status="fail" if runner_errors else "pass",
            message="; ".join(runner_errors)
            if runner_errors
            else "Runner entrypoints are present.",
        )
    )

    if kb_root is not None and kb_root.is_dir():
        scanned_units, scan_errors = kb_store.scan_units(kb_root)
        invalid_units: list[str] = list(scan_errors)
        state_schema = manifest.state_schema if manifest is not None else 1
        for module, name, frontmatter, _ in scanned_units:
            error = kb_store.validate_unit_state(
                kb_root,
                module,
                name,
                frontmatter,
                state_schema=state_schema,
            )
            if error:
                invalid_units.append(error)
        checks.append(
            HealthCheck(
                id="unit_state",
                label="Unit state integrity",
                status="fail" if invalid_units else "pass",
                message=(
                    f"{len(invalid_units)} unit state error(s): {invalid_units[0]}"
                    if invalid_units
                    else "All indexed KB unit states are verifiable."
                ),
            )
        )
        checks.append(_git_check("kb", kb_root))
    if target is not None and target.is_dir():
        checks.append(_git_check("target", target))

    overall: Literal["ready", "degraded", "blocked"]
    if any(check.status == "fail" for check in checks):
        overall = "blocked"
    elif any(check.status == "warn" for check in checks):
        overall = "degraded"
    else:
        overall = "ready"
    return ProjectHealth(status=overall, checks=tuple(checks))
