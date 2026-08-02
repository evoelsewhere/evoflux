"""Team endpoints — all under /team.

Router groups (split across modules to keep each file focused on one
resource):

- :mod:`app.api.routes.team.chat` — POST /chat, GET /{sid}/stream,
  GET /agents, GET /sessions, DELETE /sessions/{sid}, GET /{sid}/history
- :mod:`app.api.routes.team.files` — GET /{sid}/uploads/{filename},
  GET /{sid}/media/{path}, GET /{sid}/files
- :mod:`app.api.routes.team.todos` — GET /sessions/{sid}/todos
- :mod:`app.api.routes.team.permissions` — GET /{sid}/permissions,
  POST /{sid}/permissions/{request_id}/reply
- :mod:`app.api.routes.team.questions` — POST /{sid}/questions/{request_id}/reply

The combined :data:`router` is mounted under ``/api/team`` by
:func:`app.api.app.create_app`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.team import (
    browser,
    chat,
    files,
    git,
    permissions,
    presentation_renderer,
    projects,
    questions,
    reviews,
    terminal,
    todos,
    webbridge,
    worktrees,
)

# Back-compat re-export: some tests import ``_serialize_agent`` directly
# from the package.  New code should import from the owning submodule.
from app.api.routes.team.chat import _serialize_agent

router = APIRouter()
router.include_router(browser.router)
router.include_router(chat.router)
router.include_router(files.router)
router.include_router(git.router)
router.include_router(todos.router)
router.include_router(permissions.router)
router.include_router(presentation_renderer.router)
router.include_router(questions.router)
router.include_router(reviews.router)
router.include_router(terminal.router)
router.include_router(worktrees.router)
router.include_router(projects.router)
router.include_router(webbridge.router, prefix="/webbridge")

__all__ = ["router", "_serialize_agent"]
