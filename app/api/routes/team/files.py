"""Uploads, workspace media proxy, and flat workspace file listing.

Two endpoints, one root (see :mod:`app.core.paths`):

- ``GET /api/team/{sid}/uploads/{filename}`` →
  ``{EVOFLUX_WORKSPACE_DIR}/{sid}/uploads/{filename}``
  User-uploaded attachments. Flat namespace (UUID-named by the uploader).

- ``GET /api/team/{sid}/media/{path}`` → ``{EVOFLUX_WORKSPACE_DIR}/{sid}/{path}``
  Agent workspace output (files written by the write/shell tools). Nested
  paths allowed. Target of bare markdown image refs rendered by the
  assistant: ``![alt](chart.png)`` → ``/api/team/{sid}/media/chart.png``.

``GET /api/team/{sid}/files`` provides a flat recursive listing of the
agent workspace — powers the "Artifacts" panel in the web UI.
"""

from __future__ import annotations

import asyncio
import difflib
import mimetypes
import os
import subprocess
import uuid
from pathlib import Path

from app.agent.tools.builtin.filesystem._ignore import (
    _SKIPPED_DIR_NAMES,
    is_gitignored as _shared_is_gitignored,
    load_gitignore_rules as _shared_load_gitignore_rules,
    matches_gitignore_pattern as _shared_matches_gitignore_pattern,
)

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.schemas.team import (
    CodingWorkspaceFilesResponse,
    WorkspaceFileInfo,
    WorkspaceFilesResponse,
)
from app.core.db import async_session_factory
from app.core.paths import session_workspace_dir, uploads_dir, workspace_dir
from app.models.chat import ChatSession
from app.services import team_manager
from app.services.office_preview_service import (
    OFFICE_PREVIEW_CSP,
    OfficePreviewError,
    OfficePreviewUnsupportedError,
    render_office_preview,
)
from app.services.workspace_file_watcher import workspace_file_watcher


class WorkspaceSetRequest(BaseModel):
    path: str | None = None  # None → reset to session default sandbox


router = APIRouter()


# ── Path-safety helpers ───────────────────────────────────────────────────────


def _safe_resolve(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root`` with traversal protection.

    Raises ``HTTPException(400)`` on traversal attempts (``..``, absolute
    paths, symlink escapes) and on empty paths.  Raises ``HTTPException(404)``
    when the resolved target does not exist or is not a regular file.
    """
    if not rel or rel.strip() == "":
        raise HTTPException(status_code=400, detail="Empty media path.")

    # Reject absolute paths and Windows drive letters early.
    candidate = Path(rel)
    if candidate.is_absolute() or (len(rel) >= 2 and rel[1] == ":"):
        raise HTTPException(status_code=400, detail="Absolute media paths rejected.")

    try:
        resolved = (root / candidate).resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except (OSError, RuntimeError):
        raise HTTPException(status_code=400, detail="Invalid media path.")

    # Containment check — fails on ``..`` escapes and symlinks pointing outside.
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="Media path escapes session root.")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Media file not found.")

    return resolved


def _guess_media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    # Windows MIME maps often omit modern types the UI still serves.
    return _FALLBACK_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


_FALLBACK_MEDIA_TYPES = {
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".wasm": "application/wasm",
}


async def _session_workspace(session_id: str) -> Path:
    """Resolve a session's workspace root, tolerating absent DB rows.

    Coding-mode sessions stash an absolute project path in
    ``ChatSession.workspace``; normal sessions leave it ``NULL`` and fall
    back to the per-session sandbox directory under
    ``EVOFLUX_WORKSPACE_DIR``. The fallback uses this module's local
    ``workspace_dir`` reference so tests can monkey-patch it.
    """
    row = None
    try:
        async with async_session_factory() as db:
            row = await db.get(ChatSession, uuid.UUID(session_id))
    except Exception:
        row = None
    if row is not None and row.workspace:
        return session_workspace_dir(session_id, row.workspace)
    return workspace_dir(session_id)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/{session_id}/uploads/{filename}")
async def get_uploaded_file(session_id: str, filename: str) -> FileResponse:
    """Serve a user-uploaded attachment from the session's uploads dir.

    Flat namespace — ``filename`` must not contain path separators.
    """
    # Reject anything that looks like a path — uploads are flat.
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid upload filename.")

    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    resolved = _safe_resolve(uploads_dir(session_id), filename)
    return FileResponse(
        path=str(resolved),
        media_type=_guess_media_type(resolved),
        filename=resolved.name,
    )


@router.get("/{session_id}/media/{file_path:path}")
async def get_workspace_media(
    session_id: str,
    file_path: str,
    download: bool = Query(default=False),
) -> FileResponse:
    """Serve a file from the session's agent workspace.

    Supports nested subpaths (e.g. ``output/chart.png``).  Path traversal is
    rejected; symlink escapes outside the workspace root are rejected via
    containment check on the resolved path.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    # Workspace state is authoritative — when the session is in a reverted
    # tail, :mod:`app.services.snapshot_service` has already restored the
    # filesystem to the boundary's snapshot, so files that should be
    # hidden simply do not exist on disk and ``_safe_resolve`` 404s.
    resolved = _safe_resolve(await _session_workspace(session_id), file_path)

    return FileResponse(
        path=str(resolved),
        media_type=_guess_media_type(resolved),
        filename=resolved.name,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{session_id}/office-preview/{file_path:path}")
async def get_workspace_office_preview(
    session_id: str,
    file_path: str,
) -> FileResponse:
    """Render an OpenXML workspace document as sandbox-friendly HTML."""
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    resolved = _safe_resolve(await _session_workspace(session_id), file_path)
    try:
        preview = await asyncio.to_thread(render_office_preview, resolved)
    except OfficePreviewUnsupportedError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except OfficePreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return FileResponse(
        path=str(preview),
        media_type="text/html",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-cache",
            "Content-Security-Policy": OFFICE_PREVIEW_CSP,
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ── Workspace file listing ────────────────────────────────────────────────────
#
# Flat recursive listing of the agent workspace.
# Design choices:
#   - Flat list (not tree) — the UI groups by directory, keeps payload simple.
#   - Regular files only (no dirs, no symlinks leaving the root).
#   - Paths are relative (POSIX separators) — safe to pass back to ``/media/``.
#   - Size cap on the walk to avoid pathological workspaces blowing up the
#     response.  Beyond the cap we truncate and flag it.

_MAX_FILES_LISTED = 10_000
_MAX_GIT_DIFF_CHARS = 512 * 1024
_MAX_UNTRACKED_DIFF_BYTES = 256 * 1024


def _load_gitignore_rules(root: Path) -> list[tuple[str, bool]]:
    return _shared_load_gitignore_rules(root)


def _matches_gitignore_pattern(pattern: str, rel: str, *, is_dir: bool) -> bool:
    return _shared_matches_gitignore_pattern(pattern, rel, is_dir=is_dir)


def _is_gitignored(rel: str, *, is_dir: bool, rules: list[tuple[str, bool]]) -> bool:
    return _shared_is_gitignored(rel, is_dir=is_dir, rules=rules)


@router.get("/{session_id}/files", response_model=WorkspaceFilesResponse)
async def list_workspace_files(session_id: str) -> WorkspaceFilesResponse:
    """List every file under the session's agent workspace, recursively.

    Returns an empty list when the workspace directory does not yet exist
    (fresh session — no tool has written anything).  Hidden dotfiles are
    skipped; symlinks pointing outside the workspace root are skipped.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    # No boundary filtering needed — snapshot_service has restored the
    # workspace to the reverted-boundary state, so the on-disk file set
    # already reflects what should be visible.
    return await asyncio.to_thread(
        _list_workspace_files,
        await _session_workspace(session_id),
        session_id,
    )


@router.put("/{session_id}/workspace", response_model=WorkspaceFilesResponse)
async def set_session_workspace(
    session_id: str,
    body: WorkspaceSetRequest,
) -> WorkspaceFilesResponse:
    """Update (or reset) the workspace folder for a session.

    Pass ``path: null`` to revert to the session sandbox default.  When a
    custom path is provided it must be absolute; it will be created (including
    parent directories) if it does not already exist.
    """
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    new_workspace: str | None = None
    if body.path is not None:
        p = Path(body.path).expanduser()
        if not p.is_absolute():
            raise HTTPException(
                status_code=400, detail="Workspace path must be absolute."
            )
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=400, detail=f"Cannot create directory: {exc}"
            )
        new_workspace = str(p.resolve())

    async with async_session_factory() as db:
        row = await db.get(ChatSession, sid)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        row.workspace = new_workspace
        await db.commit()

    # Do not cold-boot a team just to update this setting.  If the Work team
    # is already cached, however, keep it aligned with the persisted row so
    # the very next agent/shell turn uses the newly selected folder.
    team_obj = team_manager.current_team_for_session(session_id)
    if team_obj is not None:
        team_obj.workspace = new_workspace

    return await asyncio.to_thread(
        _list_workspace_files, await _session_workspace(session_id), session_id
    )


@router.post("/{session_id}/files/upload", response_model=WorkspaceFilesResponse)
async def upload_workspace_files(
    session_id: str,
    files: list[UploadFile],
    subfolder: str = Query(default=""),
) -> WorkspaceFilesResponse:
    """Upload one or more files into the session workspace.

    Files land at ``<workspace_root>/<subfolder>/<filename>``.  The subfolder
    parameter is optional and defaults to the workspace root.  Path traversal
    in filenames or the subfolder is rejected.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    workspace = await _session_workspace(session_id)
    workspace.mkdir(parents=True, exist_ok=True)

    # Resolve target directory with traversal protection.
    if subfolder:
        candidate = Path(subfolder)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise HTTPException(status_code=400, detail="Invalid subfolder path.")
        target_dir = (workspace / candidate).resolve()
        try:
            target_dir.relative_to(workspace.resolve())
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Subfolder escapes workspace root."
            )
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = workspace

    written: list[str] = []
    for upload in files:
        raw_name = Path(upload.filename or "upload").name
        if not raw_name or raw_name in (".", ".."):
            continue
        dest = target_dir / raw_name
        content = await upload.read()
        try:
            await asyncio.to_thread(dest.write_bytes, content)
            written.append(raw_name)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Write failed for {raw_name}: {exc}"
            )

    return await asyncio.to_thread(_list_workspace_files, workspace, session_id)


class FileMoveRequest(BaseModel):
    from_path: str  # Relative POSIX path within workspace
    to_path: str  # Relative POSIX path within workspace


@router.post("/{session_id}/files/move", response_model=WorkspaceFilesResponse)
async def move_workspace_file(
    session_id: str,
    body: FileMoveRequest,
) -> WorkspaceFilesResponse:
    """Rename or move a file within the session workspace.

    Both ``from_path`` and ``to_path`` are relative, POSIX-separated paths.
    Parent directories for the destination are created automatically.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    workspace = await _session_workspace(session_id)
    src = _safe_resolve(workspace, body.from_path)
    dest_candidate = Path(body.to_path)
    if dest_candidate.is_absolute() or ".." in dest_candidate.parts:
        raise HTTPException(
            status_code=400, detail="Destination path must be relative."
        )
    dest = (workspace / dest_candidate).resolve()
    try:
        dest.relative_to(workspace.resolve())
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Destination escapes workspace root."
        )
    if dest == src:
        return await asyncio.to_thread(_list_workspace_files, workspace, session_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Move failed: {exc}")
    return await asyncio.to_thread(_list_workspace_files, workspace, session_id)


@router.delete(
    "/{session_id}/files/{file_path:path}", response_model=WorkspaceFilesResponse
)
async def delete_workspace_file(
    session_id: str,
    file_path: str,
) -> WorkspaceFilesResponse:
    """Delete a single file from the session workspace."""
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id.")

    workspace = await _session_workspace(session_id)
    target = _safe_resolve(workspace, file_path)
    try:
        target.unlink()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")
    return await asyncio.to_thread(_list_workspace_files, workspace, session_id)


def _list_workspace_files(root: Path, session_id: str) -> WorkspaceFilesResponse:
    workspace_root = str(root.resolve(strict=False))
    if not root.exists() or not root.is_dir():
        return WorkspaceFilesResponse(
            session_id=session_id,
            files=[],
            truncated=False,
            workspace_root=workspace_root,
        )

    root_resolved = root.resolve(strict=False)
    gitignore_rules = _load_gitignore_rules(root)
    files: list[WorkspaceFileInfo] = []
    truncated = False

    # InputBar @-mention picker policy:
    #   - Always skip ``.git/`` — VCS internals are huge and never useful to
    #     reference from a chat composer.
    #   - Otherwise allow dot-prefixed entries (``.evoflux/``, ``.github/``,
    #     ``.env.example``, …) and defer the actual filtering to ``.gitignore``.
    #     This matches what users see in their editor and honours the project's
    #     ``!`` re-include rules (e.g. ``.evoflux/commands/`` is tracked even
    #     though ``.evoflux/*`` is ignored).
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name != ".git"
            and name not in _SKIPPED_DIR_NAMES
            and not _is_gitignored(
                (current / name).relative_to(root).as_posix(),
                is_dir=True,
                rules=gitignore_rules,
            )
        )

        for filename in sorted(filenames):
            if len(files) >= _MAX_FILES_LISTED:
                truncated = True
                break
            entry = current / filename
            rel = entry.relative_to(root).as_posix()
            if _is_gitignored(rel, is_dir=False, rules=gitignore_rules):
                continue
            try:
                resolved = entry.resolve(strict=False)
                resolved.relative_to(root_resolved)
            except (OSError, ValueError):
                continue
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            mime, _ = mimetypes.guess_type(str(entry))
            files.append(
                WorkspaceFileInfo(
                    path=rel,
                    name=entry.name,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    mime=mime or "application/octet-stream",
                )
            )
        if truncated:
            break

    return WorkspaceFilesResponse(
        session_id=session_id,
        files=files,
        truncated=truncated,
        workspace_root=workspace_root,
    )


@router.get("/workspace/files/read")
async def read_coding_workspace_file(
    workspace: str, path: str, download: bool = False
) -> FileResponse:
    """Serve the raw bytes of a single file from the coding workspace.

    ``path`` is the POSIX-relative path returned by ``/workspace/files/list``
    (e.g. ``src/main.py`` or ``output/chart.png``).  Path traversal is
    rejected via containment check on the resolved path — the same guard
    used by the session media proxy.
    """
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    root = Path(resolved).resolve(strict=False)
    target = (root / path).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes workspace root.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(
        path=str(target),
        media_type=mime or "application/octet-stream",
        filename=target.name if download else None,
    )


@router.put("/workspace/files/write")
async def write_coding_workspace_file(
    workspace: str, path: str, body: dict[str, str]
) -> dict[str, bool]:
    """Write content to a single file in the coding workspace.

    Accepts JSON ``{"content": "..."}`` body.  Path traversal is rejected
    via containment check.  Parent directories are created if needed.
    """
    content = body.get("content")
    if content is None:
        raise HTTPException(status_code=422, detail="Missing 'content' field.")
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    root = Path(resolved).resolve(strict=False)
    target = (root / path).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes workspace root.")

    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_text, content, encoding="utf-8")
    return {"ok": True}


@router.get("/workspace/files/list", response_model=CodingWorkspaceFilesResponse)
async def list_coding_workspace_files(workspace: str) -> CodingWorkspaceFilesResponse:
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    listing = await asyncio.to_thread(
        _list_workspace_files, Path(resolved), "workspace"
    )
    return CodingWorkspaceFilesResponse(
        workspace=resolved,
        files=listing.files,
        truncated=listing.truncated,
    )


@router.get("/workspace/git-diff/view")
async def get_coding_workspace_git_diff(
    workspace: str,
    paths: list[str] | None = Query(None),
) -> dict:
    """Return the workspace's git diff, optionally scoped to ``paths``.

    Without ``paths`` the diff covers the entire repo (``git diff -- .``) —
    the legacy whole-repo behaviour. With ``paths`` we run
    ``git diff -- a b c`` and filter the untracked scan to those entries
    too, yielding the diff hunks for just those files. Per-file scoped
    diffs are ~5–20ms vs ~100–800ms for the whole-repo path; the SSE
    cache bridge uses them to splice live tool_end changes into the
    cached diff without paying the full refresh cost.
    """
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    root = Path(resolved)
    if not (root / ".git").exists():
        return {"workspace": resolved, "is_git_repo": False, "diff": ""}

    # Normalise + validate paths: drop empties, reject absolute or
    # parent-traversal paths so the scoped call can't leak diffs from
    # outside the workspace.
    scoped: list[str] = []
    if paths:
        for raw in paths:
            if not raw:
                continue
            normal = os.path.normpath(raw)
            if normal.startswith("..") or os.path.isabs(normal):
                raise HTTPException(
                    status_code=422,
                    detail=f"invalid path in scoped diff: {raw}",
                )
            scoped.append(normal)
    # ``git diff -- .`` covers the whole tree; ``git diff -- a b c``
    # restricts to those pathspecs (which can be files or directories).
    diff_paths = scoped if scoped else ["."]

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", resolved, "diff", "--", *diff_paths],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=f"git diff failed: {exc}") from exc

    if result.returncode != 0:
        raise HTTPException(
            status_code=500, detail=result.stderr.strip() or "git diff failed"
        )
    untracked_out = await _run_git(
        resolved, "ls-files", "--others", "--exclude-standard"
    )
    untracked = untracked_out.splitlines() if untracked_out is not None else []
    # When scoped, only synthesise untracked diffs for paths the caller
    # asked about — otherwise the response would carry diff hunks for
    # files the SSE bridge has no reason to splice.
    if scoped:
        scoped_set = set(scoped)
        untracked = [u for u in untracked if u in scoped_set]
    tracked_diff = str(result.stdout)
    full_diff = tracked_diff + await asyncio.to_thread(_untracked_diff, root, untracked)
    truncated = len(full_diff) > _MAX_GIT_DIFF_CHARS
    diff = full_diff[:_MAX_GIT_DIFF_CHARS]
    return {
        "workspace": resolved,
        "is_git_repo": True,
        "diff": diff,
        "untracked": untracked,
        "truncated": truncated,
    }


def _untracked_diff(root: Path, paths: list[str]) -> str:
    chunks: list[str] = []
    for path in paths:
        file_path = root / path
        try:
            if (
                not file_path.is_file()
                or file_path.stat().st_size > _MAX_UNTRACKED_DIFF_BYTES
            ):
                chunks.append(
                    f"\ndiff --git a/{path} b/{path}\n"
                    "new file mode 100644\n"
                    f"Binary or large file not shown: {path}\n"
                )
                continue
            lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
            chunks.append(
                f"\ndiff --git a/{path} b/{path}\n"
                "new file mode 100644\n"
                f"Binary or unreadable file not shown: {path}\n"
            )
            continue

        body = "".join(
            difflib.unified_diff(
                [],
                lines,
                fromfile="/dev/null",
                tofile=f"b/{path}",
            )
        )
        chunks.append(f"\ndiff --git a/{path} b/{path}\nnew file mode 100644\n{body}")
    return "".join(chunks)


async def _run_git(cwd: str, *args: str, timeout: float = 5.0) -> str | None:
    """Run a git command, returning stdout on success or None on any failure."""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    # ``text=True`` above guarantees a str
    return str(result.stdout)


def _parse_porcelain_v2(stdout: str) -> tuple[str | None, dict[str, int]]:
    """Parse ``git status --porcelain=v2 --branch`` output.

    Returns ``(branch, counts)`` where ``counts`` has keys ``staged``,
    ``unstaged``, ``untracked``. ``branch`` is ``None`` for detached HEAD.
    """
    branch: str | None = None
    staged = unstaged = untracked = 0
    for line in stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head ") :].strip()
            branch = None if head == "(detached)" else head
        elif line.startswith(("1 ", "2 ")):
            # XY status code in field 2 (e.g. "M.", ".M", "MM")
            parts = line.split(" ", 2)
            if len(parts) >= 2 and len(parts[1]) == 2:
                if parts[1][0] != ".":
                    staged += 1
                if parts[1][1] != ".":
                    unstaged += 1
        elif line.startswith("? "):
            untracked += 1
    return branch, {"staged": staged, "unstaged": unstaged, "untracked": untracked}


@router.get("/workspace/status")
async def get_coding_workspace_status(workspace: str) -> dict:
    """Lightweight workspace overview for the coding-mode empty state.

    Returns workspace path + name (always), and git metadata (branch, dirty
    counts, last commit) when the folder is a git repo. Failures degrade
    gracefully — missing git / dirty parse errors yield ``is_git_repo: false``
    rather than 500.
    """
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    root = Path(resolved)
    name = root.name or resolved
    payload: dict = {"workspace": resolved, "name": name, "is_git_repo": False}

    if not (root / ".git").exists():
        return payload

    status_out = await _run_git(resolved, "status", "--porcelain=v2", "--branch")
    if status_out is None:
        return payload
    branch, counts = _parse_porcelain_v2(status_out)

    head: dict | None = None
    log_out = await _run_git(resolved, "log", "-1", "--format=%h%x00%s%x00%ct")
    if log_out:
        parts = log_out.rstrip("\n").split("\x00")
        if len(parts) == 3:
            try:
                head = {
                    "sha": parts[0],
                    "subject": parts[1],
                    "timestamp": int(parts[2]),
                }
            except ValueError:
                head = None

    payload.update(
        {
            "is_git_repo": True,
            "branch": branch,
            "dirty": counts,
            "head": head,
        }
    )
    return payload


@router.get("/{session_id}/files/watch")
async def watch_session_files(session_id: str, request: Request):
    """SSE stream that emits file-change events for a session workspace.

    Same wire protocol as ``/workspace/watch`` but resolves the workspace
    path from the session record (custom path or sandbox default) so the
    caller only needs the session ID.
    """
    import json
    from typing import AsyncGenerator

    resolved = await _session_workspace(session_id)
    queue = await workspace_file_watcher.subscribe(resolved)

    async def _gen() -> AsyncGenerator[dict, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    events = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {
                        "event": "fs_change",
                        "data": json.dumps(events),
                    }
                except TimeoutError:
                    yield {"event": "keepalive", "data": "{}"}
        finally:
            await workspace_file_watcher.unsubscribe(resolved, queue)

    return EventSourceResponse(_gen())


@router.get("/workspace/watch")
async def watch_workspace_files(workspace: str, request: Request):
    """SSE stream that emits file-change events for a coding workspace.

    Each event is a JSON array of ``{type, path}`` objects where ``type``
    is ``"added"`` | ``"modified"`` | ``"deleted"`` and ``path`` is the
    workspace-relative POSIX path.

    The watcher starts when the first client connects and stops when all
    clients disconnect. Uses ``watchfiles`` (Rust ``notify`` backend) —
    typical latency is <100ms.
    """
    import json
    from typing import AsyncGenerator

    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    queue = await workspace_file_watcher.subscribe(resolved)

    async def _gen() -> AsyncGenerator[dict, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    events = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {
                        "event": "fs_change",
                        "data": json.dumps(events),
                    }
                except TimeoutError:
                    # Send keepalive so proxies don't close the connection
                    yield {"event": "keepalive", "data": "{}"}
        finally:
            await workspace_file_watcher.unsubscribe(resolved, queue)

    return EventSourceResponse(_gen())
