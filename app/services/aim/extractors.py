"""Resolve structural-extractor parsers for AIM source workspaces.

The bridge described in aim-framework.md §3.9: a project rulebook's
``extractors/*.yaml`` configs become :class:`StructuralParser` instances
that the repository-local ``code_index`` registry appends to its builtin
tree-sitter parsers. Refreshing an AIM project's *source* repository then
indexes COBOL/JCL/VB6 symbols, relations, and source chunks for the unified
``code_context`` tool and API.

Only source-role workspaces get extractors: the target repo is written in
a modern stack the builtin parsers already cover, and the KB repo is
markdown. The only rulebook is ``<kb>/rulebook/`` in the project KB.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from loguru import logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingProject, CodingProjectWorkspace, CodingWorkspace
from app.services.code_index.parsers.base import LanguageParser

_ROOT_CONFIG_PATHS: dict[Path, tuple[Path, ...]] = {}
_ROOT_CONFIG_PATHS_LOCK = threading.RLock()


def _code_index_parsers_for_root(root: Path) -> list[LanguageParser]:
    """Resolve the active AIM rulebook parsers for one repository root."""

    from app.services.code_index.parsers.structural import load_structural_parsers

    with _ROOT_CONFIG_PATHS_LOCK:
        paths = list(_ROOT_CONFIG_PATHS.get(root.expanduser().resolve(), ()))
    return cast(list[LanguageParser], load_structural_parsers(paths))


def activate_code_index_bridge() -> None:
    """Expose AIM rulebook extractors through the repository-local index."""

    from app.services.code_index.parsers.registry import register_extra_parser_provider

    register_extra_parser_provider(_code_index_parsers_for_root)


async def refresh_code_index_bridge(db: AsyncSession) -> None:
    """Refresh source-root → rulebook extractor mappings from live AIM projects."""

    from app.services.aim.project import (
        resolve_kb_workspace_path,
        resolve_source_workspace_paths,
    )

    projects = (
        await db.exec(
            select(CodingProject)
            .where(CodingProject.kind == "aim")
            .where(col(CodingProject.deleted_at).is_(None))
        )
    ).all()
    mappings: dict[Path, list[Path]] = {}
    for project in projects:
        kb_path = await resolve_kb_workspace_path(db, project)
        if not kb_path:
            continue
        configs = extractor_config_paths(Path(kb_path))
        if not configs:
            continue
        for source_path in await resolve_source_workspace_paths(db, project):
            root = Path(source_path).expanduser().resolve()
            bucket = mappings.setdefault(root, [])
            bucket.extend(path for path in configs if path not in bucket)
    with _ROOT_CONFIG_PATHS_LOCK:
        _ROOT_CONFIG_PATHS.clear()
        _ROOT_CONFIG_PATHS.update(
            {root: tuple(paths) for root, paths in mappings.items()}
        )
    activate_code_index_bridge()


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
        manifest = validate_rulebook_identity(kb_root)
    except (FileNotFoundError, ValueError):
        return []
    if manifest.parser_strategy == "none":
        return []
    paths: list[Path] = []
    for relative in manifest.extractors:
        try:
            paths.append(resolve_rulebook_path(kb_root, str(relative)))
        except ValueError as exc:
            logger.warning("aim_extractor_path_invalid path={} error={}", relative, exc)
    return [path for path in paths if path.is_file()]


async def parser_strategy_for_workspace(
    db: AsyncSession, workspace_id: UUID
) -> Literal["tree_sitter", "structural", "none"] | None:
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.aim.rulebook import validate_rulebook_identity

    memberships = await db.exec(
        select(CodingProject)
        .join(
            CodingProjectWorkspace,
            col(CodingProjectWorkspace.project_id) == col(CodingProject.id),
        )
        .where(col(CodingProjectWorkspace.workspace_id) == workspace_id)
        .where(col(CodingProject.kind) == "aim")
        .where(col(CodingProject.deleted_at).is_(None))
    )
    strategies: list[Literal["tree_sitter", "structural", "none"]] = []
    for project in memberships.all():
        source_ids = ((project.settings.get("aim") or {}).get("roles") or {}).get(
            "source"
        ) or []
        if str(workspace_id) not in source_ids:
            continue
        kb_path = await resolve_kb_workspace_path(db, project)
        if not kb_path:
            continue
        try:
            strategies.append(validate_rulebook_identity(Path(kb_path)).parser_strategy)
        except (FileNotFoundError, ValueError):
            continue
    if not strategies:
        return None
    if "tree_sitter" in strategies:
        return "tree_sitter"
    if "structural" in strategies:
        return "structural"
    return "none"


async def structural_parsers_for_workspace(
    db: AsyncSession, workspace_id: UUID
) -> list[LanguageParser]:
    """StructuralParsers to add when reindexing ``workspace_id``, if any.

    Non-empty only when the workspace is registered as a *source* repo of
    an AIM project; then the project's rulebook supplies the configs. A
    workspace in several AIM projects (unusual) gets the union, first
    rulebook first — extension collisions resolve to the later parser via
    registry ordering, which is as good a tiebreak as any.
    """
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.code_index.parsers.structural import load_structural_parsers

    memberships = await db.exec(
        select(CodingProject)
        .join(
            CodingProjectWorkspace,
            col(CodingProjectWorkspace.project_id) == col(CodingProject.id),
        )
        .where(col(CodingProjectWorkspace.workspace_id) == workspace_id)
        .where(col(CodingProject.kind) == "aim")
        .where(col(CodingProject.deleted_at).is_(None))
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
    return cast(list[LanguageParser], parsers)


async def structural_parsers_for_path(
    db: AsyncSession, root_path: str
) -> list[LanguageParser]:
    """Like :func:`structural_parsers_for_workspace`, keyed by path — for
    callers that have not resolved a ``CodingWorkspace`` row yet."""
    row = await db.exec(
        select(CodingWorkspace).where(col(CodingWorkspace.path) == root_path)
    )
    workspace = row.first()
    if workspace is None or workspace.id is None:
        return []
    return await structural_parsers_for_workspace(db, workspace.id)
