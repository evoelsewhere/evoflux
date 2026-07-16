"""Creates or joins an AIM migration project — the backend half of
AimSetupWizard (``documents/research/aim-framework.md`` §3.12).
"""

from __future__ import annotations

from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingProject, CodingProjectWorkspace
from app.services.aim import kb_store
from app.services.aim.models import AimManifest
from app.services.aim.project import resolve_repo_identity
from app.services.coding_workspace_service import upsert_coding_workspace


async def _link_project_workspaces(
    db: AsyncSession,
    project: CodingProject,
    *,
    source_paths: list[str],
    target_path: str,
    kb_path: str,
    rulebook_id: str,
    rulebook_version: str,
) -> None:
    """Register every repo as a ``CodingWorkspace``/``CodingProjectWorkspace``
    and write the local role -> workspace_id mapping into
    ``settings["aim"]`` (§3.5) — shared by create and join, which only
    differ in where the KB repo/aim.yaml itself comes from.
    """

    async def _link(path: str, sort_order: int) -> str:
        ws = await upsert_coding_workspace(db, path=path, kind="repo")
        db.add(
            CodingProjectWorkspace(
                project_id=project.id, workspace_id=ws.id, sort_order=sort_order
            )
        )
        return str(ws.id)

    order = 0
    source_ws_ids: list[str] = []
    for path in source_paths:
        source_ws_ids.append(await _link(path, order))
        order += 1
    target_ws_id = await _link(target_path, order)
    order += 1
    kb_ws_id = await _link(kb_path, order)

    project.settings = {
        "aim": {
            "rulebook": {"id": rulebook_id, "version": rulebook_version},
            "roles": {
                "source": source_ws_ids,
                "target": [target_ws_id],
                "kb": [kb_ws_id],
            },
        }
    }
    db.add(project)
    await db.flush()


async def create_aim_project(
    db: AsyncSession,
    *,
    name: str,
    rulebook_id: str,
    rulebook_version: str,
    source_paths: list[str],
    target_path: str,
    kb_path: str,
) -> CodingProject:
    """Create a brand-new AIM project: scaffolds a fresh KB repo from the
    template, writes its ``aim.yaml`` (the shareable manifest, keyed by
    repo identity — not this machine's local paths), and registers all
    workspaces.
    """
    kb_root = Path(kb_path).expanduser().resolve()
    kb_store.scaffold_kb_from_template(kb_root)
    kb_store.create_manifest(
        kb_root,
        rulebook_id=rulebook_id,
        rulebook_version=rulebook_version,
        source_identities=[resolve_repo_identity(p) for p in source_paths],
        target_identities=[resolve_repo_identity(target_path)],
    )

    project = CodingProject(name=name, kind="aim", settings={})
    db.add(project)
    await db.flush()
    await _link_project_workspaces(
        db,
        project,
        source_paths=source_paths,
        target_path=target_path,
        kb_path=str(kb_root),
        rulebook_id=rulebook_id,
        rulebook_version=rulebook_version,
    )
    _install_rulebook_best_effort(rulebook_id)
    await db.refresh(project)
    return project


def _install_rulebook_best_effort(rulebook_id: str) -> None:
    """Pack content installation must never fail project setup."""
    from loguru import logger

    try:
        from app.services.aim.rulebook_install import install_rulebook_content

        install_rulebook_content(rulebook_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("aim_rulebook_install_failed rulebook={} error={}", rulebook_id, exc)


async def preview_aim_manifest(kb_path: str) -> AimManifest:
    """Read ``aim.yaml`` at *kb_path* without creating anything — the
    "Join existing" wizard step's preview, before the user maps each
    identity to a local repo path.
    """
    return kb_store.read_manifest(Path(kb_path).expanduser().resolve())


async def join_aim_project(
    db: AsyncSession,
    *,
    name: str,
    kb_path: str,
    source_paths: list[str],
    target_path: str,
) -> CodingProject:
    """Join an existing AIM project: clone the KB repo locally first, then
    call this with a local path for each identity ``aim.yaml`` lists (in
    the same order — the wizard shows the user the identities to map, not
    the rulebook/project name, which come straight from the manifest).
    """
    kb_root = Path(kb_path).expanduser().resolve()
    manifest = kb_store.read_manifest(kb_root)

    project = CodingProject(name=name, kind="aim", settings={})
    db.add(project)
    await db.flush()
    await _link_project_workspaces(
        db,
        project,
        source_paths=source_paths,
        target_path=target_path,
        kb_path=str(kb_root),
        rulebook_id=manifest.rulebook.id,
        rulebook_version=manifest.rulebook.version,
    )
    _install_rulebook_best_effort(manifest.rulebook.id)
    await db.refresh(project)
    return project
