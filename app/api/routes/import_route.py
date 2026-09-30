"""Import API routes.

Provides endpoints for detecting, previewing, and executing data imports
from external AI tools (Claude, ChatGPT, Codex, Cursor).

All endpoints accept a **local filesystem path** — the Python sidecar reads
files directly.  No web upload, no temp staging.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.services.import_service import (
    detect_conflicts,
    execute_import,
    get_bundle,
    parse_import,
    remove_bundle,
    store_bundle,
)

router = APIRouter()


# ── Request / Response schemas ───────────────────────────────────────────────


class DetectRequest(BaseModel):
    """Path to a local file or directory to import from."""

    path: str = Field(..., description="Absolute path to the export file or directory")
    source: str | None = Field(
        None,
        description="Explicit source identifier (e.g. 'claude_web'). "
        "If omitted, auto-detection is attempted.",
    )


class ImportItemPreview(BaseModel):
    id: str
    kind: str
    label: str
    preview: str
    action: str
    conflicts: list[str] = Field(default_factory=list)
    target_name: str


class DetectResponse(BaseModel):
    import_id: str
    detected_source: str
    path: str
    summary: dict[str, Any]
    items: list[ImportItemPreview] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UpdateItemRequest(BaseModel):
    """Update conflict resolution for a single item."""

    action: str = Field(
        ..., description="Resolution: 'import', 'skip', 'replace', or 'rename'"
    )


class ExecuteResponse(BaseModel):
    imported: dict[str, int]
    skipped: dict[str, int]
    errors: list[dict[str, Any]]


class HistoryItem(BaseModel):
    import_id: str
    source: str
    path: str
    item_count: int
    summary: dict[str, Any]


class ScanResult(BaseModel):
    """A discovered importable source on the local machine."""

    source: str
    path: str
    label: str
    description: str
    estimated_items: int


class ScanResponse(BaseModel):
    discovered: list[ScanResult]


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/scan", response_model=ScanResponse)
async def import_scan() -> ScanResponse:
    """Scan the local machine for common AI tool data locations.

    Returns a list of discovered sources with estimated item counts.
    """
    import os
    from pathlib import Path

    home = Path.home()
    discovered: list[ScanResult] = []

    # Claude.ai: look for exported JSON/ZIP in common locations
    for search_dir in [home / "Downloads", home / "Desktop", home]:
        if not search_dir.is_dir():
            continue
        for f in search_dir.iterdir():
            if f.is_file() and f.suffix.lower() in (".json", ".zip"):
                name_lower = f.name.lower()
                if "claude" in name_lower and "export" in name_lower:
                    discovered.append(
                        ScanResult(
                            source="claude_web",
                            path=str(f),
                            label=f"Claude.ai export: {f.name}",
                            description=f"Export file in {search_dir.name}",
                            estimated_items=0,
                        )
                    )

    # Claude Desktop / Claude Code: ~/.claude/
    claude_dir = home / ".claude"
    if claude_dir.is_dir():
        session_count = 0
        project_names: list[str] = []
        projects_dir = claude_dir / "projects"
        if projects_dir.is_dir():
            for proj in projects_dir.iterdir():
                if not proj.is_dir():
                    continue
                # Sessions are JSONL files directly in the project dir
                proj_sessions = list(proj.glob("*.jsonl"))
                # Also check sessions/ subdirectory
                sessions_sub = proj / "sessions"
                if sessions_sub.is_dir():
                    proj_sessions.extend(sessions_sub.glob("*.jsonl"))
                if proj_sessions:
                    session_count += len(proj_sessions)
                    project_names.append(proj.name)

        # Parse installed plugins and enumerate their skills
        import json as json_mod

        plugin_count = 0
        skill_count = 0
        skill_names: list[str] = []
        installed_plugins = claude_dir / "plugins" / "installed_plugins.json"
        if installed_plugins.is_file():
            try:
                plugins_data = json_mod.loads(
                    installed_plugins.read_text(encoding="utf-8")
                )
                plugins_dict = (
                    plugins_data.get("plugins", {})
                    if isinstance(plugins_data, dict)
                    else {}
                )
                plugin_count = len(plugins_dict)
                # Enumerate skills from each plugin's cache directory
                for plugin_name, installs in plugins_dict.items():
                    if not isinstance(installs, list) or not installs:
                        continue
                    install = installs[0]
                    install_path = install.get("installPath", "")
                    if not install_path:
                        continue
                    plugin_dir = Path(install_path)
                    skills_dir = plugin_dir / "skills"
                    if skills_dir.is_dir():
                        for skill_dir in skills_dir.iterdir():
                            if (
                                skill_dir.is_dir()
                                and (skill_dir / "SKILL.md").is_file()
                            ):
                                skill_count += 1
                                skill_names.append(skill_dir.name)
            except (ValueError, OSError):
                pass

        # Standalone plugins: any dir with skills/ or plugin.json
        standalone_skill_count = 0
        skip_dirs = {
            "projects",
            "plugins",
            "sessions",
            "commands",
            "browser",
            "cache",
            "plans",
        }
        for child in claude_dir.iterdir():
            if not child.is_dir() or child.name in skip_dirs:
                continue
            child_skills = child / "skills"
            if child_skills.is_dir():
                for s in child_skills.iterdir():
                    if s.is_dir() and (s / "SKILL.md").is_file():
                        standalone_skill_count += 1
                        skill_names.append(f"{child.name}:{s.name}")

        # MCP config: .mcp.json or any standalone plugin with mcp.json
        has_mcp = (claude_dir / ".mcp.json").is_file()
        for child in claude_dir.iterdir():
            if child.is_dir() and child.name not in skip_dirs:
                if (child / "mcp.json").is_file():
                    has_mcp = True
                    break

        # Plans
        plan_count = 0
        plans_dir = claude_dir / "plans"
        if plans_dir.is_dir():
            plan_count = len(list(plans_dir.glob("*.md")))

        # Commands (slash commands)
        cmd_count = 0
        commands_dir = claude_dir / "commands"
        if commands_dir.is_dir():
            cmd_count = len(list(commands_dir.glob("*.md")))

        total_skill_count = skill_count + standalone_skill_count
        total = (
            session_count
            + plugin_count
            + total_skill_count
            + (1 if has_mcp else 0)
            + plan_count
            + cmd_count
        )
        if total > 0:
            parts: list[str] = []
            if session_count:
                parts.append(
                    f"{session_count} sessions across {len(project_names)} projects"
                )
            if plugin_count:
                parts.append(f"{plugin_count} plugins")
            if total_skill_count:
                parts.append(f"{total_skill_count} skills")
            if cmd_count:
                parts.append(f"{cmd_count} commands")
            if plan_count:
                parts.append(f"{plan_count} plans")
            if has_mcp:
                parts.append("MCP config")
            discovered.append(
                ScanResult(
                    source="claude_code",
                    path=str(claude_dir),
                    label="Claude Desktop / Claude Code",
                    description=", ".join(parts),
                    estimated_items=total,
                )
            )

    # ChatGPT: look for export ZIP/JSON in Downloads
    for search_dir in [home / "Downloads", home / "Desktop"]:
        if not search_dir.is_dir():
            continue
        for f in search_dir.iterdir():
            if f.is_file() and f.suffix.lower() in (".json", ".zip"):
                name_lower = f.name.lower()
                if ("chatgpt" in name_lower or "conversations" in name_lower) and (
                    "export" in name_lower or "share" in name_lower
                ):
                    discovered.append(
                        ScanResult(
                            source="chatgpt",
                            path=str(f),
                            label=f"ChatGPT export: {f.name}",
                            description=f"Export file in {search_dir.name}",
                            estimated_items=0,
                        )
                    )

    # Codex: ~/.codex/ — sessions nested by year/month/day
    codex_dir = home / ".codex"
    if codex_dir.is_dir():
        session_count = 0
        sessions_dir = codex_dir / "sessions"
        if sessions_dir.is_dir():
            # Sessions are nested: sessions/2026/09/<day>/thread.jsonl
            session_count = len(list(sessions_dir.rglob("*.jsonl")))
        has_instructions = (codex_dir / "instructions.md").is_file()
        total = session_count + (1 if has_instructions else 0)
        if total > 0:
            discovered.append(
                ScanResult(
                    source="codex",
                    path=str(codex_dir),
                    label="Codex CLI",
                    description=f"{session_count} sessions"
                    + (", instructions" if has_instructions else ""),
                    estimated_items=total,
                )
            )

    # Cursor: look for .cursor/ in cwd and common project dirs
    cwd = Path(os.getcwd())
    cursor_dir = cwd / ".cursor"
    cursorrules = cwd / ".cursorrules"
    if cursor_dir.is_dir() or cursorrules.is_file():
        rule_count = 0
        rules_dir = cursor_dir / "rules"
        if rules_dir.is_dir():
            rule_count = len(list(rules_dir.glob("*.mdc")))
        has_mcp = (cursor_dir / "mcp.json").is_file()
        total = rule_count + (1 if cursorrules.is_file() else 0) + (1 if has_mcp else 0)
        if total > 0:
            parts = []
            if rule_count:
                parts.append(f"{rule_count} rules")
            if cursorrules.is_file():
                parts.append(".cursorrules")
            if has_mcp:
                parts.append("MCP config")
            discovered.append(
                ScanResult(
                    source="cursor",
                    path=str(cwd),
                    label="Cursor (current workspace)",
                    description=", ".join(parts),
                    estimated_items=total,
                )
            )

    # Workspace-level configs: CLAUDE.md, AGENTS.md, .github/copilot-instructions.md
    workspace_items: list[str] = []
    if (cwd / "CLAUDE.md").is_file():
        workspace_items.append("CLAUDE.md")
    if (cwd / "AGENTS.md").is_file():
        workspace_items.append("AGENTS.md")
    if (cwd / ".github" / "copilot-instructions.md").is_file():
        workspace_items.append("Copilot instructions")
    if (cwd / ".windsurfrules").is_file():
        workspace_items.append(".windsurfrules")
    if workspace_items:
        discovered.append(
            ScanResult(
                source="generic",
                path=str(cwd),
                label="Workspace instructions",
                description=", ".join(workspace_items),
                estimated_items=len(workspace_items),
            )
        )

    # Common project directories: scan for .claude/, .cursor/, .codex/
    for project_dir_name in ("projects", "dev", "code", "repos", "work"):
        project_base = home / project_dir_name
        if not project_base.is_dir():
            continue
        # Only scan immediate children (max depth 1)
        try:
            for child in project_base.iterdir():
                if not child.is_dir():
                    continue
                child_items: list[str] = []
                if (child / ".claude").is_dir() or (child / "CLAUDE.md").is_file():
                    child_items.append("Claude config")
                if (child / ".cursor").is_dir() or (child / ".cursorrules").is_file():
                    child_items.append("Cursor config")
                if (child / ".codex").is_dir():
                    child_items.append("Codex config")
                if child_items:
                    discovered.append(
                        ScanResult(
                            source="generic",
                            path=str(child),
                            label=f"{child.name} ({project_dir_name}/)",
                            description=", ".join(child_items),
                            estimated_items=len(child_items),
                        )
                    )
        except OSError:
            continue

    return ScanResponse(discovered=discovered)


@router.get("/auto-sync")
async def get_auto_sync_settings() -> dict[str, Any]:
    """Return the current auto-sync settings."""
    from app.core.runtime_settings import load_runtime_settings

    settings = load_runtime_settings()
    cfg = settings.import_auto_sync
    return {
        "enabled": cfg.enabled,
        "scan_interval_seconds": cfg.scan_interval_seconds,
        "notify_new_items": cfg.notify_new_items,
    }


@router.put("/auto-sync")
async def update_auto_sync_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Update auto-sync settings in settings.yaml."""
    import yaml

    settings_path = Path.home() / ".evoflux" / "dev" / "config" / "settings.yaml"
    if not settings_path.exists():
        settings_path = Path(".evoflux") / "dev" / "config" / "settings.yaml"

    # Load current
    try:
        with open(settings_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        data = {}

    # Update
    import_cfg = data.get("import_auto_sync", {})
    if "enabled" in body:
        import_cfg["enabled"] = bool(body["enabled"])
    if "scan_interval_seconds" in body:
        import_cfg["scan_interval_seconds"] = int(body["scan_interval_seconds"])
    if "notify_new_items" in body:
        import_cfg["notify_new_items"] = bool(body["notify_new_items"])
    data["import_auto_sync"] = import_cfg

    # Write back
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save settings: {exc}")

    return {
        "enabled": import_cfg.get("enabled", False),
        "scan_interval_seconds": import_cfg.get("scan_interval_seconds", 300),
        "notify_new_items": import_cfg.get("notify_new_items", True),
    }


@router.post("/detect", response_model=DetectResponse)
async def import_detect(
    body: DetectRequest,
    db: DbSession,
) -> DetectResponse:
    """Auto-detect the source format and return a preview bundle.

    Accepts a local filesystem path.  The Python sidecar reads the file
    directly — no upload required.  Runs conflict detection against the DB
    to mark items that were already imported.
    """
    path = Path(body.path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")

    bundle = parse_import(path, source=body.source)
    if bundle.source == "unknown" or not bundle.items:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Could not detect import format",
                "warnings": bundle.warnings,
            },
        )

    # Run conflict detection to mark already-imported items
    await detect_conflicts(db, bundle)

    import_id = uuid.uuid4().hex[:16]
    store_bundle(import_id, bundle)

    # Count new vs already-imported
    new_count = sum(1 for it in bundle.items if it.action != "skip")
    already_count = sum(1 for it in bundle.items if it.action == "skip")

    # Build item previews
    items: list[ImportItemPreview] = []
    for i, item in enumerate(bundle.items):
        preview_parts: list[str] = []
        if item.kind == "session":
            msg_count = len(item.data.get("messages", []))
            preview_parts.append(f"{msg_count} messages")
            created = item.data.get("created_at", "")[:10]
            if created:
                preview_parts.append(f"created {created}")
        elif item.kind == "agent":
            preview_parts.append(item.data.get("description", "")[:60])
        elif item.kind == "skill":
            preview_parts.append(item.data.get("description", "")[:60])
        elif item.kind == "mcp_server":
            preview_parts.append("MCP server config")
        elif item.kind == "knowledge":
            preview_parts.append(item.data.get("filename", ""))
        elif item.kind == "setting":
            preview_parts.append("Settings/credentials")

        if item.action == "skip":
            preview_parts.append("already imported")

        items.append(
            ImportItemPreview(
                id=f"{import_id}_{i}",
                kind=item.kind,
                label=item.label,
                preview=", ".join(preview_parts) if preview_parts else item.kind,
                action=item.action,
                conflicts=item.conflicts,
                target_name=item.data.get("title")
                or item.data.get("name")
                or item.label,
            )
        )

    # Summary counts
    kind_counts: dict[str, int] = {}
    for item in bundle.items:
        kind_counts[item.kind] = kind_counts.get(item.kind, 0) + 1

    return DetectResponse(
        import_id=import_id,
        detected_source=bundle.source,
        path=str(path),
        summary={
            "total_items": len(bundle.items),
            "new_items": new_count,
            "already_imported": already_count,
            "conflicts": sum(1 for it in bundle.items if it.conflicts),
            **kind_counts,
        },
        items=items,
        warnings=bundle.warnings,
    )


@router.get("/preview/{import_id}", response_model=DetectResponse)
async def import_preview(import_id: str) -> DetectResponse:
    """Return the current preview for a previously detected import."""
    bundle = get_bundle(import_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Import not found")

    items: list[ImportItemPreview] = []
    for i, item in enumerate(bundle.items):
        preview_parts: list[str] = []
        if item.kind == "session":
            msg_count = len(item.data.get("messages", []))
            preview_parts.append(f"{msg_count} messages")
            created = item.data.get("created_at", "")[:10]
            if created:
                preview_parts.append(f"created {created}")

        items.append(
            ImportItemPreview(
                id=f"{import_id}_{i}",
                kind=item.kind,
                label=item.label,
                preview=", ".join(preview_parts) if preview_parts else item.kind,
                action=item.action,
                conflicts=item.conflicts,
                target_name=item.data.get("title")
                or item.data.get("name")
                or item.label,
            )
        )

    kind_counts: dict[str, int] = {}
    for item in bundle.items:
        kind_counts[item.kind] = kind_counts.get(item.kind, 0) + 1

    return DetectResponse(
        import_id=import_id,
        detected_source=bundle.source,
        path=bundle.metadata.get("source_path", ""),
        summary={
            "total_items": len(bundle.items),
            "conflicts": sum(1 for it in bundle.items if it.conflicts),
            **kind_counts,
        },
        items=items,
        warnings=bundle.warnings,
    )


@router.patch("/preview/{import_id}/items/{item_index}")
async def update_item_action(
    import_id: str,
    item_index: int,
    body: UpdateItemRequest,
) -> dict[str, str]:
    """Update the conflict resolution action for a specific item."""
    bundle = get_bundle(import_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Import not found")

    if item_index < 0 or item_index >= len(bundle.items):
        raise HTTPException(status_code=400, detail="Invalid item index")

    allowed = {"import", "skip", "replace", "rename"}
    if body.action not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Allowed: {allowed}",
        )

    bundle.items[item_index].action = body.action  # type: ignore[assignment]
    return {"status": "ok"}


@router.post("/execute/{import_id}", response_model=ExecuteResponse)
async def import_execute(
    import_id: str,
    db: DbSession,
) -> ExecuteResponse:
    """Execute the import, writing accepted items to EvoFlux data stores."""
    bundle = get_bundle(import_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Import not found")

    # Detect conflicts against current DB state
    await detect_conflicts(db, bundle)

    # Reset actions for items that now have conflicts (unless user overrode)
    for item in bundle.items:
        if item.conflicts and item.action == "import":
            item.action = "skip"

    # Execute
    result = await execute_import(db, bundle)

    return ExecuteResponse(
        imported=result.imported,
        skipped=result.skipped,
        errors=result.errors,
    )


@router.delete("/{import_id}")
async def import_cancel(import_id: str) -> dict[str, str]:
    """Cancel and clean up a pending import."""
    remove_bundle(import_id)
    return {"status": "cancelled"}


@router.get("/history")
async def import_history(
    db: DbSession,
) -> dict[str, Any]:
    """Return past import operations from the history table."""
    from json import JSONDecodeError, loads

    from sqlmodel import select

    from app.models.import_job import ImportJob

    stmt = select(ImportJob).order_by(ImportJob.created_at.desc()).limit(50)
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    items: list[dict[str, Any]] = []
    for job in jobs:
        imported: dict[str, Any] = {}
        skipped: dict[str, Any] = {}
        try:
            imported = loads(job.imported_counts)
        except (JSONDecodeError, TypeError):
            pass
        try:
            skipped = loads(job.skipped_counts)
        except (JSONDecodeError, TypeError):
            pass

        items.append(
            {
                "import_id": job.id,
                "source": job.source,
                "path": job.source_path,
                "detected_format": job.detected_format,
                "status": job.status,
                "imported": imported,
                "skipped": skipped,
                "error_count": job.error_count,
                "item_count": job.item_count,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat()
                if job.completed_at
                else None,
            }
        )

    return {"imports": items}
