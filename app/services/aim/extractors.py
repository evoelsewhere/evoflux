"""Resolve structural-extractor parsers for AIM source workspaces.

The bridge described in aim-framework.md §3.9: a project rulebook's
``extractors/*.yaml`` configs become :class:`StructuralParser` instances
that ``build_registry(extra_parsers=...)`` appends to the builtin
tree-sitter parsers — so reindexing an AIM project's *source* workspace
puts a COBOL/JCL/VB6 estate straight into ``code_nodes``/``code_edges``/FTS
and every existing code-graph tool works on it unchanged.

Only source-role workspaces get extractors: the target repo is written in
a modern stack the builtin parsers already cover, and the KB repo is
markdown. The only rulebook is ``<kb>/rulebook/`` in the project KB.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from loguru import logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingProject, CodingProjectWorkspace, CodingWorkspace


def extractor_config_paths(kb_root: Path) -> list[Path]:
    """Extractor config files a rulebook declares, in manifest order.

    Example files are inert until explicitly listed under ``extractors`` in
    ``rulebook.yaml``. Missing or invalid local rulebooks resolve to an empty
    list; Project Health surfaces the configuration error to the operator.
    """
    from app.services.aim.rulebook import (
        resolve_rulebook_path,
        validate_rulebook_identity,
    )

    try:
        manifest = validate_rulebook_identity(kb_root).model_dump()
    except (FileNotFoundError, ValueError):
        return []
    declared = manifest.get("extractors")
    if not isinstance(declared, list):
        return []
    paths: list[Path] = []
    for relative in declared:
        try:
            paths.append(resolve_rulebook_path(kb_root, str(relative)))
        except ValueError as exc:
            logger.warning("aim_extractor_path_invalid path={} error={}", relative, exc)
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
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.code_graph.parsers.structural import load_structural_parsers

    memberships = await db.exec(
        select(CodingProject)
        .join(
            CodingProjectWorkspace,
            col(CodingProjectWorkspace.project_id) == col(CodingProject.id),
        )
        .where(col(CodingProjectWorkspace.workspace_id) == workspace_id)
        .where(col(CodingProject.kind) == "aim")
    )
    config_paths: list[Path] = []
    for project in memberships.all():
        aim_settings = project.settings.get("aim") or {}
        source_ids = (aim_settings.get("roles") or {}).get("source") or []
        if str(workspace_id) not in source_ids:
            continue
        kb_path = await resolve_kb_workspace_path(db, project)
        if not kb_path:
            continue
        config_paths.extend(extractor_config_paths(Path(kb_path)))
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
    row = await db.exec(
        select(CodingWorkspace).where(col(CodingWorkspace.path) == root_path)
    )
    workspace = row.first()
    if workspace is None or workspace.id is None:
        return []
    return await structural_parsers_for_workspace(db, workspace.id)
