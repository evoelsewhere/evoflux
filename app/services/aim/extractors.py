"""Resolve structural-extractor parsers for AIM source workspaces.

The bridge described in aim-framework.md §3.9: a rulebook pack's
``extractors/*.yaml`` configs become :class:`StructuralParser` instances
that ``build_registry(extra_parsers=...)`` appends to the builtin
tree-sitter parsers — so reindexing an AIM project's *source* workspace
puts a COBOL/JCL/VB6 estate straight into ``code_nodes``/``code_edges``/FTS
and every existing code-graph tool works on it unchanged.

Only source-role workspaces get extractors: the target repo is written in
a modern stack the builtin parsers already cover, and the KB repo is
markdown. Rulebooks resolve from the builtin packs directory
(``app/agent/builtin_aim/rulebooks/``) by the id recorded in
``project.settings["aim"]["rulebook"]`` at project setup.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.chat import CodingProject, CodingProjectWorkspace, CodingWorkspace


def _builtin_rulebooks_dir() -> Path:
    from app.agent.tools.builtin import aim as aim_tools

    return aim_tools._builtin_rulebooks_dir()


def extractor_config_paths(rulebook_id: str) -> list[Path]:
    """Extractor config files a rulebook declares, in manifest order.

    Reads the pack's ``rulebook.yaml`` ``extractors:`` list; falls back to
    globbing ``extractors/*.yaml`` for packs that predate the manifest key.
    Unknown rulebook ids resolve to an empty list — a project created
    against a rulebook this install doesn't ship simply indexes with the
    builtin parsers only.
    """
    import yaml

    pack_dir = _builtin_rulebooks_dir() / rulebook_id
    manifest_path = pack_dir / "rulebook.yaml"
    if not manifest_path.is_file():
        return []
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning(
            "aim_rulebook_manifest_invalid rulebook={} error={}", rulebook_id, exc
        )
        return []
    declared = manifest.get("extractors")
    if isinstance(declared, list):
        paths = [pack_dir / str(rel) for rel in declared]
    else:
        paths = sorted((pack_dir / "extractors").glob("*.yaml"))
    return [path for path in paths if path.is_file()]


async def structural_parsers_for_workspace(
    db: AsyncSession, workspace_id: UUID
) -> list:
    """StructuralParsers to add when reindexing ``workspace_id``, if any.

    Non-empty only when the workspace is registered as a *source* repo of
    an AIM project; then the project's rulebook supplies the configs. A
    workspace in several AIM projects (unusual) gets the union, first
    rulebook first — extension collisions resolve to the later parser via
    registry ordering, which is as good a tiebreak as any.
    """
    from app.services.code_graph.parsers.structural import load_structural_parsers

    memberships = await db.execute(
        select(CodingProject)
        .join(
            CodingProjectWorkspace,
            col(CodingProjectWorkspace.project_id) == col(CodingProject.id),
        )
        .where(col(CodingProjectWorkspace.workspace_id) == workspace_id)
        .where(col(CodingProject.kind) == "aim")
    )
    config_paths: list[Path] = []
    seen: set[str] = set()
    for project in memberships.scalars().all():
        aim_settings = project.settings.get("aim") or {}
        source_ids = (aim_settings.get("roles") or {}).get("source") or []
        if str(workspace_id) not in source_ids:
            continue
        rulebook_id = (aim_settings.get("rulebook") or {}).get("id")
        if not rulebook_id or rulebook_id in seen:
            continue
        seen.add(rulebook_id)
        config_paths.extend(extractor_config_paths(rulebook_id))
    if not config_paths:
        return []
    parsers = load_structural_parsers(config_paths)
    if parsers:
        logger.info(
            "aim_structural_parsers_loaded workspace_id={} parsers={}",
            workspace_id,
            [parser.name for parser in parsers],
        )
    return parsers


async def structural_parsers_for_path(db: AsyncSession, root_path: str) -> list:
    """Like :func:`structural_parsers_for_workspace`, keyed by path — for
    callers that haven't resolved a CodingWorkspace row yet."""
    row = await db.execute(
        select(CodingWorkspace).where(col(CodingWorkspace.path) == root_path)
    )
    workspace = row.scalars().first()
    if workspace is None or workspace.id is None:
        return []
    return await structural_parsers_for_workspace(db, workspace.id)
