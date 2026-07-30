"""Operational health checks for an AIM migration project."""

from __future__ import annotations

import asyncio
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
    RulebookManifest,
    read_rulebook_manifest,
    resolve_rulebook_dir,
    resolve_rulebook_path,
)

HealthStatus = Literal["pass", "warn", "fail"]


def _declared_rulebook_assets(manifest: RulebookManifest) -> dict[str, str]:
    assets = dict(manifest.assets)
    assets.update({f"mapping:{name}": path for name, path in manifest.mappings.items()})
    if manifest.target_base:
        assets["target_base"] = manifest.target_base
    if manifest.ui_patterns:
        assets["ui_patterns"] = manifest.ui_patterns
    if manifest.parser_strategy != "none":
        assets.update(
            {
                f"extractor:{index}": path
                for index, path in enumerate(manifest.extractors)
            }
        )
    return assets


def _workspace_activation_errors(
    target: Path | None, manifest: RulebookManifest
) -> list[str]:
    declared = {
        kind: paths
        for kind, paths in manifest.workspace_activation.model_dump().items()
        if paths
    }
    if not declared:
        return []
    if target is None or not target.is_dir():
        return ["target workspace is unavailable for project customizations"]
    root = target.resolve()
    errors: list[str] = []
    for kind, paths in declared.items():
        for relative in paths:
            candidate = Path(relative)
            resolved = (root / candidate).resolve()
            if candidate.is_absolute() or not resolved.is_relative_to(root):
                errors.append(f"{kind} path escapes target workspace: {relative}")
            elif not resolved.is_file():
                errors.append(f"{kind} file is missing: {relative}")
    return errors


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
    source_paths = [
        Path(path) for path in await resolve_source_workspace_paths(db, project)
    ]
    target_raw = await resolve_target_workspace_path(db, project)
    kb_raw = await resolve_kb_workspace_path(db, project)
    target = Path(target_raw) if target_raw else None
    kb_root = Path(kb_raw) if kb_raw else None

    return await asyncio.to_thread(
        _evaluate_project_health_paths,
        source_paths,
        target,
        kb_root,
    )


def _evaluate_project_health_paths(
    source_paths: list[Path], target: Path | None, kb_root: Path | None
) -> ProjectHealth:
    checks: list[HealthCheck] = []

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
                else "All lifecycle capability switches are active."
            ),
        )
    )

    asset_errors: list[str] = []
    if pack_model is not None and kb_root is not None:
        for label, declared_path in _declared_rulebook_assets(pack_model).items():
            try:
                path = resolve_rulebook_path(kb_root, declared_path)
            except ValueError as exc:
                asset_errors.append(f"{label}: {exc}")
                continue
            if not path.is_file():
                asset_errors.append(f"{label} is missing: {declared_path}")
        if pack_model.parser_strategy != "none":
            from app.services.code_graph.parsers.structural import (
                load_structural_config,
            )

            for declared_path in pack_model.extractors:
                try:
                    path = resolve_rulebook_path(kb_root, declared_path)
                    if path.is_file():
                        load_structural_config(path)
                except (OSError, ValueError) as exc:
                    asset_errors.append(f"extractor {declared_path}: {exc}")
    checks.append(
        HealthCheck(
            id="rulebook_assets",
            label="Rulebook operational assets",
            status="fail" if asset_errors else "pass",
            message=(
                "; ".join(asset_errors)
                if asset_errors
                else "All declared rulebook assets are present and valid."
            ),
        )
    )

    activation_errors = (
        _workspace_activation_errors(target, pack_model)
        if pack_model is not None
        else []
    )
    checks.append(
        HealthCheck(
            id="workspace_activation",
            label="Project customizations",
            status="fail" if activation_errors else "pass",
            message=(
                "; ".join(activation_errors)
                if activation_errors
                else "Declared project skills, workflows, and commands are available."
            ),
        )
    )

    profile_path = (
        pack / "canonicalizers" / f"{manifest.compare_default_profile}.yaml"
        if pack is not None and manifest is not None
        else None
    )
    profile_error = ""
    if profile_path is not None and profile_path.is_file():
        try:
            from app.services.aim.canonicalize import load_profile

            load_profile(profile_path)
        except (OSError, ValueError) as exc:
            profile_error = str(exc)
    checks.append(
        HealthCheck(
            id="canonicalizer",
            label="Canonicalizer",
            status="pass"
            if profile_path is not None and profile_path.is_file() and not profile_error
            else "fail",
            message=(
                f"Profile {manifest.compare_default_profile!r} is available."
                if profile_path is not None
                and profile_path.is_file()
                and manifest is not None
                else profile_error or "Pinned canonicalizer profile is missing."
            ),
        )
    )

    runner_declarations = pack_manifest.get("runners")
    runner_errors: list[str] = []
    if not isinstance(runner_declarations, dict) or not runner_declarations:
        runner_errors.append("rulebook declares no legacy/target runners")
    elif kb_root is not None:
        for required_role in ("legacy", "target"):
            if not runner_declarations.get(required_role):
                runner_errors.append(f"rulebook declares no {required_role} runner")
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
            allowed_kinds = pack_model.unit_kinds if pack_model is not None else []
            if allowed_kinds and frontmatter.kind not in allowed_kinds:
                invalid_units.append(
                    f"{module}/{name}: kind {frontmatter.kind!r} is not allowed"
                )
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
