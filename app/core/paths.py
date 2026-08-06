"""Centralised path helpers for session-scoped on-disk resources.

Single root per session — uploads live *inside* the workspace:

- ``workspace_dir(session_id)`` → ``{EVOFLUX_WORKSPACE_DIR}/{session_id}``
  Agent workspace — where write/shell tools produce files.  Bounded by
  the sandbox.  Served publicly via the ``/media/`` proxy so the web UI
  can render images the assistant references in markdown.

- ``uploads_dir(session_id)`` → ``{workspace_dir(session_id)}/uploads``
  User-uploaded attachment files (UUID-named, validated at upload).
  Fed to the LLM via curated multimodal rehydration
  (``build_parts_from_metas``) and mounted read-only into every session
  sandbox. Work sessions can also address them as ``uploads/<filename>``;
  Coding sessions use the absolute path supplied in the model-facing
  attachment hint so repositories remain untouched.

  The absolute file path is persisted in the attachment meta dict
  (``att["path"]``) so rehydration is a pure path lookup — no derivation
  from the message's session id.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def workspace_dir(session_id: str) -> Path:
    """Return the per-session agent workspace root (team sandbox)."""
    return Path(settings.EVOFLUX_WORKSPACE_DIR) / session_id


def session_workspace_dir(session_id: str, workspace: str | None = None) -> Path:
    """Return the session workspace or exact coding workspace."""
    if workspace:
        return Path(workspace).resolve()
    return workspace_dir(session_id)


def uploads_dir(session_id: str) -> Path:
    """Return the per-session directory for user-uploaded attachments.

    Lives under the app-managed Work session root. ``SandboxConfig`` mounts
    it read-only for Coding sessions whose primary workspace is a repo.
    """
    return workspace_dir(session_id) / "uploads"


def session_uploads_dir(session_id: str) -> Path:
    """Return app-managed uploads storage for the session.

    Coding mode still uses the exact project directory as the sandbox root,
    but uploads remain under ``EVOFLUX_WORKSPACE_DIR`` so production/dev
    storage follows the same APP_ENV-derived roots as normal sessions.
    """
    return uploads_dir(session_id)
