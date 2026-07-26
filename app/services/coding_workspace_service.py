from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingWorkspace


async def upsert_coding_workspace(
    db: AsyncSession,
    *,
    path: str,
    kind: str = "repo",
    source_path: str | None = None,
    name: str | None = None,
    managed: bool = False,
    hidden: bool = False,
    deleted_at: datetime | None = None,
) -> CodingWorkspace:
    resolved_path = str(Path(path).expanduser().resolve())
    resolved_source = (
        str(Path(source_path).expanduser().resolve()) if source_path else None
    )
    row = (
        await db.exec(
            select(CodingWorkspace).where(CodingWorkspace.path == resolved_path)
        )
    ).first()
    if row is None:
        row = CodingWorkspace(path=resolved_path)
    preserve_worktree = (
        row.kind == "worktree" and kind == "repo" and resolved_source is None
    )
    if not preserve_worktree:
        row.kind = kind
        row.source_path = resolved_source
        row.name = name or Path(resolved_path).name
        row.managed = managed
    elif name:
        row.name = name
    row.hidden = hidden
    row.deleted_at = deleted_at
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def hide_coding_workspace(db: AsyncSession, path: str) -> int:
    """Hide a repository and every worktree registered beneath it.

    The coding sidebar synthesizes a repository row for visible worktrees
    whose source repository is hidden. Hiding only the source therefore made
    a removed workspace appear again. Removing a repository from the sidebar
    must hide its whole worktree group.
    """
    resolved_path = str(Path(path).expanduser().resolve())
    rows = list(
        (
            await db.exec(
                select(CodingWorkspace).where(CodingWorkspace.path == resolved_path)
            )
        ).all()
    )
    worktree_rows = list(
        (
            await db.exec(
                select(CodingWorkspace).where(
                    CodingWorkspace.source_path == resolved_path
                )
            )
        ).all()
    )
    rows.extend(worktree_rows)
    if not rows:
        row = CodingWorkspace(
            path=resolved_path, name=Path(resolved_path).name, hidden=True
        )
        db.add(row)
        await db.flush()
        return 1
    for row in rows:
        row.hidden = True
        db.add(row)
    return len(rows)


async def mark_coding_workspace_deleted(db: AsyncSession, path: str) -> int:
    resolved_path = str(Path(path).expanduser().resolve())
    deleted_at = datetime.now(timezone.utc)
    rows = list(
        (
            await db.exec(
                select(CodingWorkspace).where(CodingWorkspace.path == resolved_path)
            )
        ).all()
    )
    if not rows:
        row = CodingWorkspace(
            path=resolved_path,
            kind="worktree",
            name=Path(resolved_path).name,
            hidden=True,
            deleted_at=deleted_at,
        )
        db.add(row)
        await db.flush()
        return 1
    for row in rows:
        row.hidden = True
        row.deleted_at = deleted_at
        db.add(row)
    return len(rows)


async def list_visible_coding_workspaces(db: AsyncSession) -> list[CodingWorkspace]:
    return list(
        (
            await db.exec(
                select(CodingWorkspace)
                .where(
                    ~col(CodingWorkspace.hidden),
                    col(CodingWorkspace.deleted_at).is_(None),
                )
                .order_by(col(CodingWorkspace.created_at).asc())
            )
        ).all()
    )


async def seed_workspace_registry_from_sessions(
    db: AsyncSession, workspaces: list[str]
) -> None:
    for workspace in workspaces:
        await upsert_coding_workspace(db, path=workspace, kind="repo", hidden=False)


async def list_workspace_paths_with_sessions(db: AsyncSession) -> list[str]:
    """Absolute paths of every visible workspace reachable by an existing session.

    A project session can read/write any repo in the project (not just the
    one it was resolved with), so every workspace belonging to a project with
    at least one session counts as "active" alongside workspaces referenced
    directly by a standalone (non-project) session. Used to scope the
    code-graph file watcher to workspaces someone has actually opened, rather
    than every workspace ever registered (e.g. added to a project but never
    used).
    """
    from app.models.chat import ChatSession, CodingProjectWorkspace

    standalone_paths = (
        await db.exec(
            select(ChatSession.workspace)
            .where(col(ChatSession.workspace).is_not(None))
            .distinct()
        )
    ).all()

    project_ids = (
        await db.exec(
            select(ChatSession.project_id)
            .where(col(ChatSession.project_id).is_not(None))
            .distinct()
        )
    ).all()

    project_paths: list[str] = []
    if project_ids:
        project_paths = list(
            (
                await db.exec(
                    select(CodingWorkspace.path)
                    .join(
                        CodingProjectWorkspace,
                        CodingProjectWorkspace.workspace_id == CodingWorkspace.id,
                    )
                    .where(col(CodingProjectWorkspace.project_id).in_(project_ids))
                    .distinct()
                )
            ).all()
        )

    candidate_paths = {p for p in (*standalone_paths, *project_paths) if p}
    if not candidate_paths:
        return []

    rows = list(
        (
            await db.exec(
                select(CodingWorkspace).where(
                    col(CodingWorkspace.path).in_(candidate_paths),
                    ~col(CodingWorkspace.hidden),
                    col(CodingWorkspace.deleted_at).is_(None),
                )
            )
        ).all()
    )
    result_paths = {row.path for row in rows}

    # Worktree sessions watch the worktree dir directly (that's the session's
    # `workspace`) — also watch its source repo so edits made there (or a
    # subsequent reindex of the source) stay in sync, mirroring the pair of
    # upsert_coding_workspace calls made when the worktree session was created.
    source_paths = {row.source_path for row in rows if row.source_path}
    if source_paths:
        source_rows = (
            await db.exec(
                select(CodingWorkspace.path).where(
                    col(CodingWorkspace.path).in_(source_paths),
                    ~col(CodingWorkspace.hidden),
                    col(CodingWorkspace.deleted_at).is_(None),
                )
            )
        ).all()
        result_paths.update(source_rows)

    return list(result_paths)
