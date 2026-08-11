"""Resolves an AIM project's role -> workspace-path mapping from
``CodingProject.settings["aim"]["roles"]`` (local ``workspace_id``s — the
per-machine mapping; the shareable manifest, keyed by repo identity, lives
in the KB repo's own ``aim.yaml``). Used by the chat route (primary
workspace = target) and team/sandbox construction (read-only = source).
See ``documents/research/aim-framework.md`` §3.3/§3.5.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingProject, CodingWorkspace


def _strip_url_credentials(url: str) -> str:
    """Remove any ``user:token@`` userinfo from a ``scheme://…`` URL.

    A credentialed HTTPS remote (``https://user:ghp_xxx@host/repo.git``) must
    never be written into the shared ``aim.yaml`` — it would leak the token to
    everyone who clones the KB. scp-style remotes (``git@host:path``, no
    ``://``) carry only a username and are left untouched.
    """
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@]+@(.*)$", url)
    return f"{match.group(1)}{match.group(2)}" if match else url


def resolve_repo_identity(path: str) -> str:
    """Best-effort, machine-independent identity for a repo: its git
    ``remote.origin.url`` if one is configured, else the directory's
    basename.

    This is what gets written into the KB's ``aim.yaml`` (§3.5) — a
    teammate cloning the KB on a different machine, where absolute paths
    necessarily differ, still recognizes "this identity is the same repo"
    and only has to supply a local path, not re-derive the whole project
    config. Any embedded credentials are stripped first.
    """
    try:
        result = subprocess.run(
            ["git", "-C", path, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = result.stdout.strip()
        if result.returncode == 0 and url:
            return _strip_url_credentials(url)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(path).name


async def _resolve_role_paths(
    db: AsyncSession, project: CodingProject, role: str
) -> list[str]:
    aim_settings = project.settings.get("aim") or {}
    workspace_ids = (aim_settings.get("roles") or {}).get(role) or []
    paths: list[str] = []
    for workspace_id in workspace_ids:
        try:
            workspace = await db.get(CodingWorkspace, UUID(str(workspace_id)))
        except ValueError:
            continue
        if workspace is not None:
            paths.append(workspace.path)
    return paths


async def resolve_target_workspace_path(
    db: AsyncSession, project: CodingProject
) -> str | None:
    paths = await _resolve_role_paths(db, project, "target")
    return paths[0] if paths else None


async def resolve_kb_workspace_path(
    db: AsyncSession, project: CodingProject
) -> str | None:
    paths = await _resolve_role_paths(db, project, "kb")
    return paths[0] if paths else None


async def resolve_source_workspace_paths(
    db: AsyncSession, project: CodingProject
) -> list[str]:
    return await _resolve_role_paths(db, project, "source")
