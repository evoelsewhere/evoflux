"""Team lifecycle manager.

Teams are loaded lazily on first use and evicted after an idle window.

Usage::

    team_manager.validate_agents_dir()               # startup (parse-only)
    team = await team_manager.get_or_start_team()    # on demand
    await team_manager.stop()                        # shutdown

Lazy lifecycle
--------------

The default team (and per-workspace coding teams) are not built on
server startup.  ``get_or_start_team()`` and ``get_or_start_coding_team()``
build them on the first incoming request (chat, scheduler fire,
``/team/agents``, etc.) and cache them in module state.

After an idle window with no working members, teams are evicted on the
next ``get_or_start_*`` call:

* Default team — ``_DEFAULT_TEAM_IDLE_SECONDS`` (1 hour)
* Coding teams — ``_CODING_TEAM_IDLE_SECONDS`` (30 minutes)

Eviction is opportunistic (no background timer); the cost of an
evicted-then-re-requested team is one ``load_team_from_dir`` + ``team.start()``
on the next request (~10–100 ms), which is below user-perceptible
latency on a chat send.

Live-config refresh — no team reload
------------------------------------

Agents now refresh themselves at the start of their next turn when
their tracked config files (their own ``.md`` and ``mcp.json``) change on
disk. Skill bodies are progressively loaded and are not agent-config
dependencies. See ``app.agent.loader.stamp_agent_files``
and ``TeamMemberBase._detect_config_drift``.  Production code paths
(``/api/mcp``, ``/api/skills``, ``/api/agents``) therefore do **not**
call :func:`reload`.

:func:`reload` is retained as a legacy admin tool for operational forced
rebuilds and as a hook for tests; do not call it from request handlers.
It rebuilds the entire team — stopping in-flight agents and rotating
session IDs — which is exactly what the live-config mechanism was
introduced to avoid.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.core.config import settings
from app.core.app_mode import AppMode, parse_app_mode
from app.core.metrics import TEAM_RESOLUTION_DURATION

if TYPE_CHECKING:
    from app.agent.mode.team.team import AgentTeam


def load_team_from_dir(*args: Any, **kwargs: Any) -> Any:
    """Lazy compatibility wrapper for the heavyweight agent loader."""
    from app.agent.loader import load_team_from_dir as load

    return load(*args, **kwargs)


def validate_agent_config_dir(agents_dir: Path) -> str | None:
    """Patch-compatible lazy wrapper for parse-only startup validation."""
    from app.agent.config import validate_agent_config_dir as validate

    return validate(agents_dir)


# ── Diff dataclass ───────────────────────────────────────────────────────────


@dataclass
class TeamDiff:
    """Difference between the previous and new team after a reload."""

    added: list[str]  # agent names added
    removed: list[str]  # agent names removed
    changed: list[str]  # agent names where model / tools / skills changed
    lead: str  # name of the new lead
    members: list[str]  # names of all members (excluding lead)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "lead": self.lead,
            "members": self.members,
        }


# ── Module-level state ───────────────────────────────────────────────────────

_team: "AgentTeam | None" = None
_team_last_used: float = 0.0
_session_teams: dict[str, "AgentTeam"] = {}
_session_team_last_used: dict[str, float] = {}
_coding_teams: dict[tuple[str, str], "AgentTeam"] = {}
_coding_team_last_used: dict[tuple[str, str], float] = {}
_DEFAULT_TEAM_IDLE_SECONDS = 60 * 60
_CODING_TEAM_IDLE_SECONDS = 30 * 60
# ``_lock`` protects cache dictionaries only. Team construction performs file
# IO and provider/tool assembly, so it must never run while this global lock is
# held. Per-identity build locks provide single-flight construction without
# blocking an unrelated workspace or session.
_lock = asyncio.Lock()
_build_locks: dict[tuple[str, ...], asyncio.Lock] = {}
_prewarm_tasks: dict[tuple[str, str, str], asyncio.Task[None]] = {}
_session_epochs: dict[str, int] = {}


class TeamBuildInvalidatedError(ValueError):
    """Raised when session teardown wins a race with cold team construction."""


def _build_lock(*identity: str) -> asyncio.Lock:
    return _build_locks.setdefault(tuple(identity), asyncio.Lock())


def prewarm_session_team(*, mode: str, session_id: str, workspace: str | None) -> None:
    """Warm the selected session's team without delaying history rendering."""

    if mode == "coding" and (
        not workspace or not Path(workspace).expanduser().is_dir()
    ):
        return
    if mode not in {"work", "coding"}:
        return
    key = (mode, workspace or "", session_id)
    current = (
        current_coding_team_for_session(workspace, session_id)
        if mode == "coding" and workspace
        else current_team_for_session(session_id)
    )
    if current is not None:
        return
    pending = _prewarm_tasks.get(key)
    if pending is not None and not pending.done():
        return

    async def _warm() -> None:
        try:
            if mode == "coding" and workspace:
                await get_or_start_coding_team(workspace, session_id, mode=mode)
            elif mode == "work":
                await get_or_start_team_for_session(session_id)
        except asyncio.CancelledError:
            raise
        except TeamBuildInvalidatedError:
            logger.debug(
                "team_prewarm_invalidated mode={} session_id={}",
                mode,
                session_id,
            )
        except Exception as exc:
            logger.warning(
                "team_prewarm_failed mode={} session_id={} error={}",
                mode,
                session_id,
                exc,
            )

    task = asyncio.create_task(_warm(), name=f"team-prewarm:{session_id}")
    _prewarm_tasks[key] = task

    def _forget(completed: asyncio.Task[None]) -> None:
        if _prewarm_tasks.get(key) is completed:
            _prewarm_tasks.pop(key, None)

    task.add_done_callback(_forget)


def _resolve_agents_dir() -> Path:
    path = Path(settings.AGENTS_DIR)
    return path if path.is_absolute() else Path.cwd() / path


def _resolve_coding_agents_dir() -> Path:
    return _resolve_agents_dir() / "coding"


def _resolve_workspace(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve()


def validate_workspace(workspace: str) -> str:
    """Validate that workspace exists and is a directory.

    Note: This only checks existence and type, not allowlist.
    Any directory on the machine can be opened as a coding workspace.
    Auth is handled by desktop-token middleware at the API layer.
    """
    resolved = _resolve_workspace(workspace)
    if not resolved.is_dir():
        raise ValueError(f"Workspace does not exist or is not a directory: {resolved}")
    return str(resolved)


def _team_is_idle(team: "AgentTeam") -> bool:
    return all(member.state != "working" for member in team.all_members)


# Back-compat alias — older call sites (tests) may import the coding-specific name.
_coding_team_is_idle = _team_is_idle


def _maybe_pop_idle_default_team_locked(
    now: float,
) -> "AgentTeam | None":
    """Return the default team for eviction, or ``None`` if it should stay.

    Caller must release the lock before stopping the returned team to avoid
    holding ``_lock`` across the team's shutdown work.
    """
    global _team, _team_last_used
    if _team is None:
        return None
    if now - _team_last_used <= _DEFAULT_TEAM_IDLE_SECONDS:
        return None
    if not _team_is_idle(_team):
        return None
    expired = _team
    _team = None
    _team_last_used = 0.0
    return expired


def _pop_idle_session_teams_locked(now: float) -> list[tuple[str, "AgentTeam"]]:
    expired = [
        session_id
        for session_id, last_used in _session_team_last_used.items()
        if now - last_used > _DEFAULT_TEAM_IDLE_SECONDS
        and (team := _session_teams.get(session_id)) is not None
        and _team_is_idle(team)
    ]
    popped: list[tuple[str, "AgentTeam"]] = []
    for session_id in expired:
        team = _session_teams.pop(session_id, None)
        _session_team_last_used.pop(session_id, None)
        if team is not None:
            popped.append((session_id, team))
    return popped


def _pop_idle_coding_teams_locked(
    now: float,
) -> list[tuple[tuple[str, str], "AgentTeam"]]:
    expired = [
        key
        for key, last_used in _coding_team_last_used.items()
        if now - last_used > _CODING_TEAM_IDLE_SECONDS
        and (team := _coding_teams.get(key)) is not None
        and _coding_team_is_idle(team)
    ]
    popped: list[tuple[tuple[str, str], "AgentTeam"]] = []
    for key in expired:
        team = _coding_teams.pop(key, None)
        _coding_team_last_used.pop(key, None)
        if team is not None:
            popped.append((key, team))
    return popped


async def _stop_coding_teams(
    teams: list[tuple[tuple[str, str], "AgentTeam"]],
) -> None:
    for (workspace, session_id), team in teams:
        try:
            await team.stop()
        except Exception:
            logger.exception(
                "coding_team_idle_stop_error workspace={} session_id={}",
                workspace,
                session_id,
            )
        else:
            logger.info(
                "coding_team_idle_stopped workspace={} session_id={}",
                workspace,
                session_id,
            )


async def _stop_session_teams(teams: list[tuple[str, "AgentTeam"]]) -> None:
    for session_id, team in teams:
        try:
            await team.stop()
        except Exception:
            logger.exception("team_session_idle_stop_error session_id={}", session_id)
        else:
            logger.info("team_session_idle_stopped session_id={}", session_id)


async def stop_sessions(session_ids: set[str]) -> None:
    """Stop and evict every live team owned by the supplied sessions."""
    if not session_ids:
        return
    async with _lock:
        session_teams: list[tuple[str, "AgentTeam"]] = []
        coding_teams: list[tuple[tuple[str, str], "AgentTeam"]] = []
        for session_id in session_ids:
            _session_epochs[session_id] = _session_epochs.get(session_id, 0) + 1
            team = _session_teams.pop(session_id, None)
            _session_team_last_used.pop(session_id, None)
            if team is not None:
                session_teams.append((session_id, team))
        for key in list(_coding_teams):
            if key[1] not in session_ids:
                continue
            team = _coding_teams.pop(key)
            _coding_team_last_used.pop(key, None)
            coding_teams.append((key, team))
    await _stop_session_teams(session_teams)
    await _stop_coding_teams(coding_teams)


def current_team() -> "AgentTeam | None":
    return _team


def current_team_for_workspace(workspace: str | None) -> "AgentTeam | None":
    if not workspace:
        return _team
    key_workspace = str(_resolve_workspace(workspace))
    for (stored_workspace, _session_id), team in _coding_teams.items():
        if stored_workspace == key_workspace:
            return team
    return None


def current_coding_team_for_session(
    workspace: str, session_id: str
) -> "AgentTeam | None":
    return _coding_teams.get((str(_resolve_workspace(workspace)), session_id))


def current_team_for_session(session_id: str) -> "AgentTeam | None":
    return _session_teams.get(session_id)


def find_team_for_session(session_id: str) -> "AgentTeam | None":
    """Any live team currently bound to *session_id*, regardless of mode —
    work teams key by session id, coding teams by (workspace, session).
    Used by the workflow runner, which only has a session id."""
    team = _session_teams.get(session_id)
    if team is not None:
        return team
    for (_workspace, stored_session), coding_team in _coding_teams.items():
        if stored_session == session_id:
            return coding_team
    return None


def has_active_team_turn() -> bool:
    """Return whether any live Work or Coding team is inside a turn boundary."""

    teams = [
        team
        for team in [_team, *_session_teams.values(), *_coding_teams.values()]
        if team
    ]
    return any(team.has_active_user_turn() for team in teams)


def set_team(team: "AgentTeam | None") -> None:
    """Replace the current team reference without running the lifecycle.

    Intended for tests that need to inject a pre-built ``AgentTeam`` into
    the FastAPI dependency without starting the real team.  Production
    code should use :func:`get_or_start_team` / :func:`reload` / :func:`stop`.
    """
    global _team, _team_last_used
    _team = team
    _team_last_used = time.monotonic() if team is not None else 0.0


# ── Lifecycle ────────────────────────────────────────────────────────────────


def validate_agents_dir() -> bool:
    """Parse-only check that the agents directory is loadable.

    Called from the FastAPI lifespan at startup so a malformed config
    surfaces immediately (server fails to boot) instead of on the first
    chat request.  Does **not** build or cache an ``AgentTeam`` — that
    happens lazily on the first call to :func:`get_or_start_team`.

    Returns ``True`` when the directory contains a valid lead, ``False``
    when it is empty or missing.  Re-raises ``ValueError`` from the loader
    on parse errors.
    """
    agents_dir = _resolve_agents_dir()
    lead_name = validate_agent_config_dir(agents_dir)
    if lead_name is None:
        logger.warning("team_manager_agents_dir_empty path={}", agents_dir)
        return False
    logger.debug(
        "team_manager_agents_dir_validated path={} lead={}", agents_dir, lead_name
    )
    return True


async def get_or_start_team() -> "AgentTeam | None":
    """Return the cached default team, building it on first use.

    Evicts the cached team if it has been idle for longer than
    ``_DEFAULT_TEAM_IDLE_SECONDS`` and has no working members.  Returns
    ``None`` when the agents directory is empty or missing (mirroring
    the legacy ``start()`` behaviour so callers can render a friendly
    "no agents configured" response).
    """
    global _team, _team_last_used

    resolution_started = time.perf_counter()
    async with _build_lock("default"):
        async with _lock:
            now = time.monotonic()
            expired = _maybe_pop_idle_default_team_locked(now)
            cached = _team
            if cached is not None:
                _team_last_used = now

        if cached is not None:
            result: "AgentTeam | None" = cached
            resolution_result = "cached"
        else:
            agents_dir = _resolve_agents_dir()
            # Sync file IO (glob + Markdown parsing) — keep it off the event
            # loop and outside the global state lock.
            candidate = await asyncio.to_thread(load_team_from_dir, agents_dir)
            if candidate is None:
                logger.warning("team_manager_no_agents path={}", agents_dir)
                result = None
                resolution_result = "missing"
            else:
                await candidate.start()
                async with _lock:
                    _team = candidate
                    _team_last_used = time.monotonic()
                logger.info("team_manager_started lead={}", candidate.lead.name)
                result = candidate
                resolution_result = "cold"

    TEAM_RESOLUTION_DURATION.labels(mode="work", result=resolution_result).observe(
        time.perf_counter() - resolution_started
    )

    if expired is not None:
        try:
            await expired.stop()
        except Exception:
            logger.exception("team_manager_idle_stop_error")
        else:
            logger.info("team_manager_idle_stopped")

    return result


async def get_or_start_team_for_session(session_id: str) -> "AgentTeam | None":
    """Return the default-mode team instance dedicated to one chat session."""
    global _team_last_used

    resolution_started = time.perf_counter()
    async with _build_lock("session", session_id):
        async with _lock:
            now = time.monotonic()
            build_epoch = _session_epochs.get(session_id, 0)
            expired_default = _maybe_pop_idle_default_team_locked(now)
            expired_sessions = _pop_idle_session_teams_locked(now)
            existing = _session_teams.get(session_id)
            if existing is not None:
                _session_team_last_used[session_id] = now

        if existing is not None:
            result: "AgentTeam | None" = existing
            resolution_result = "cached"
        else:
            agents_dir = _resolve_agents_dir()
            candidate = await asyncio.to_thread(load_team_from_dir, agents_dir)
            if candidate is None:
                logger.warning("team_manager_no_agents path={}", agents_dir)
                result = None
                resolution_result = "missing"
            else:
                await candidate.start()
                invalidated = False
                async with _lock:
                    if _session_epochs.get(session_id, 0) != build_epoch:
                        invalidated = True
                    else:
                        _session_teams[session_id] = candidate
                        now = time.monotonic()
                        _session_team_last_used[session_id] = now
                        _team_last_used = now
                if invalidated:
                    await candidate.stop()
                    raise TeamBuildInvalidatedError(
                        f"Session {session_id} was removed while its team was starting."
                    )
                logger.info(
                    "team_manager_session_started session_id={} lead={}",
                    session_id,
                    candidate.lead.name,
                )
                result = candidate
                resolution_result = "cold"

    TEAM_RESOLUTION_DURATION.labels(mode="work", result=resolution_result).observe(
        time.perf_counter() - resolution_started
    )

    if expired_default is not None:
        try:
            await expired_default.stop()
        except Exception:
            logger.exception("team_manager_idle_stop_error")
        else:
            logger.info("team_manager_idle_stopped")
    await _stop_session_teams(expired_sessions)

    return result


async def stop() -> None:
    """Stop the current team (if any) on server shutdown."""
    global _team, _team_last_used
    prewarm_tasks = tuple(_prewarm_tasks.values())
    _prewarm_tasks.clear()
    for task in prewarm_tasks:
        task.cancel()
    if prewarm_tasks:
        await asyncio.gather(*prewarm_tasks, return_exceptions=True)
    async with _lock:
        default_team = _team
        session_teams = list(_session_teams.items())
        coding_teams = list(_coding_teams.items())
        _team = None
        _team_last_used = 0.0
        _session_teams.clear()
        _session_team_last_used.clear()
        _coding_teams.clear()
        _coding_team_last_used.clear()
    if default_team is not None:
        try:
            await default_team.stop()
        except Exception:
            logger.exception("team_manager_stop_error")
    await _stop_session_teams(session_teams)
    await _stop_coding_teams(coding_teams)


async def get_or_start_coding_team(
    workspace: str,
    session_id: str,
    extra_workspace_paths: list[str] | None = None,
    *,
    mode: str = "coding",
    read_only_paths: list[str] | None = None,
) -> "AgentTeam":
    """Build (or return the cached) project-scoped coding team for *workspace*.

    ``read_only_paths`` marks repos as write-denied — see
    ``SandboxConfig.read_only_paths``.
    """
    resolved_mode = parse_app_mode(mode)
    if resolved_mode is not AppMode.CODING:
        raise ValueError("Coding team manager only accepts mode='coding'.")
    mode = resolved_mode.value
    resolved_workspace = validate_workspace(workspace)
    key = (resolved_workspace, session_id)
    resolution_started = time.perf_counter()
    async with _build_lock("coding", resolved_workspace, session_id):
        async with _lock:
            now = time.monotonic()
            build_epoch = _session_epochs.get(session_id, 0)
            expired = _pop_idle_coding_teams_locked(now)
            existing = _coding_teams.get(key)
            if existing is not None:
                _coding_team_last_used[key] = now

        if existing is not None:
            team = existing
            resolution_result = "cached"
        else:
            agents_dir = _resolve_coding_agents_dir()
            team = await asyncio.to_thread(
                load_team_from_dir,
                agents_dir,
                mode=mode,
                workspace=resolved_workspace,
            )
            if team is None:
                raise ValueError(
                    f"No {mode} agents found in '{agents_dir}'. "
                    "Create at least one .md file with 'role: lead'."
                )
            await team.start()
            invalidated = False
            async with _lock:
                if _session_epochs.get(session_id, 0) != build_epoch:
                    invalidated = True
                else:
                    _coding_teams[key] = team
                    _coding_team_last_used[key] = time.monotonic()
            if invalidated:
                await team.stop()
                raise TeamBuildInvalidatedError(
                    f"Session {session_id} was removed while its team was starting."
                )
            logger.info(
                "coding_team_started mode={} workspace={} session_id={} lead={}",
                mode,
                resolved_workspace,
                session_id,
                team.lead.name,
            )
            resolution_result = "cold"

        # Refresh project visibility on both cached and newly built teams.
        if extra_workspace_paths is not None:
            team.extra_workspace_paths = extra_workspace_paths
        if read_only_paths is not None:
            team.read_only_paths = read_only_paths

    TEAM_RESOLUTION_DURATION.labels(mode=mode, result=resolution_result).observe(
        time.perf_counter() - resolution_started
    )

    await _stop_coding_teams(expired)
    return team


# ── Hot reload ───────────────────────────────────────────────────────────────


def _team_snapshot(team: "AgentTeam") -> dict[str, dict]:
    """Capture per-agent fingerprint used to compute the diff."""
    snapshot: dict[str, dict] = {}
    members = [team.lead, *team.members.values()]
    for m in members:
        agent = m.agent
        snapshot[agent.name] = {
            "description": agent.description or "",
            "model": agent.model_id,
            "tools": sorted(t.name for t in agent._tools.values()),
            "skills": sorted(agent.skills or []),
            "system_prompt": agent.system_prompt,
        }
    return snapshot


def _compute_diff(before: dict[str, dict] | None, team: "AgentTeam") -> TeamDiff:
    after = _team_snapshot(team)
    before = before or {}

    before_names = set(before.keys())
    after_names = set(after.keys())

    added = sorted(after_names - before_names)
    removed = sorted(before_names - after_names)
    changed = sorted(
        name for name in before_names & after_names if before[name] != after[name]
    )

    members = sorted(team.members.keys())
    return TeamDiff(
        added=added,
        removed=removed,
        changed=changed,
        lead=team.lead.name,
        members=members,
    )


async def reload() -> TeamDiff:
    """Rebuild the team from ``AGENTS_DIR`` and atomically swap it in.

    .. warning::
        Legacy admin path.  Calling this stops every agent (cancelling
        any in-flight tool execution, rotating session IDs, emitting a
        premature ``done`` event for the active turn).  Production code
        should rely on the live-config refresh mechanism instead — see
        the module docstring.

    Raises ``ValueError`` (from :func:`load_team_from_dir`) on any validation
    failure — the running team is untouched in that case.
    """
    global _team, _team_last_used
    async with _lock:
        agents_dir = _resolve_agents_dir()

        # 1. Build candidate first — throws on validation failure, running
        #    team stays live.
        candidate = load_team_from_dir(agents_dir)
        if candidate is None:
            raise ValueError(
                f"No agents found in '{agents_dir}'. "
                "Create at least one .md file with 'role: lead' before reloading."
            )

        # 2. Snapshot the old team (for diff) and stop it.
        before_snapshot = _team_snapshot(_team) if _team is not None else None
        old_team = _team
        if old_team is not None:
            try:
                await old_team.stop()
            except Exception:
                logger.exception("team_manager_reload_stop_error")

        # 3. Start the new one.  ``app.api.deps.get_team`` will pick it up
        #    via :func:`current_team` on the next request.
        await candidate.start()
        _team = candidate
        _team_last_used = time.monotonic()

        diff = _compute_diff(before_snapshot, candidate)
        logger.info(
            "team_manager_reloaded lead={} added={} removed={} changed={}",
            diff.lead,
            diff.added,
            diff.removed,
            diff.changed,
        )
        return diff


# ── Live-config refresh ──────────────────────────────────────────────────────


def refresh_idle_agents(team: "AgentTeam") -> None:
    """Detect and apply config drift for all idle (non-working) agents.

    This is the same mechanism agents use at start-of-turn, hoisted into
    a service function so the ``GET /team/agents`` route can serve fresh
    frontmatter without knowing about ``TeamMemberBase`` internals.

    Working agents are skipped — refreshing them would race ``agent.run()``
    swapping ``self.agent`` mid-execution.

    Errors are swallowed and logged so a single bad agent config never
    breaks the listing endpoint.
    """
    for member in [team.lead, *team.members.values()]:
        if member.state == "working":
            continue
        try:
            member.refresh_if_dirty()
        except Exception as exc:
            logger.warning(
                "team_agents_refresh_failed name={} error={}", member.name, exc
            )


def refresh_blueprints(team: "AgentTeam") -> None:
    """Rediscover member ``.md`` files for *team* and update its blueprint
    registry in place.

    The source directory is derived from ``team.mode`` so callers
    (currently just ``GET /team/agents``) don't need to know whether they
    hold a default or a coding team. Without this, a user who creates a
    new member through the Settings → Agents page wouldn't see it appear
    in the spawnable roster until the team object is evicted and rebuilt
    — typically a server restart.

    Behaviour:

    * **New file** → register a fresh :class:`MemberBlueprint`. The lead
      will see it on its next ``team_manage`` listing.
    * **Removed file** → drop the blueprint *only if* no live instances
      reference it; otherwise leave it alone so an in-flight conversation
      can still address the agent by handle.
    * **Edited file** → no-op here. The blueprint's ``source_path`` is
      unchanged and existing instances pick up the edit via the regular
      drift mechanism on their next turn.
    * **Lead changed** → no-op. Lead lifecycle is owned by :func:`reload`,
      not by this hot-path service.
    * **Parse error in a new file** → logged and skipped; the rest of the
      directory is still processed.
    """
    from app.agent.loader import member_model_is_configured, parse_agent_md
    from app.conductor.agent_runtime import apply_managed_agent_runtime_model
    from app.agent.mode.team.team import MemberBlueprint

    agents_dir_by_mode = {
        "coding": _resolve_coding_agents_dir,
    }
    agents_dir = agents_dir_by_mode.get(team.mode, _resolve_agents_dir)()
    if not agents_dir.exists():
        return

    md_files = sorted(agents_dir.glob("*.md"))
    seen: set[str] = set()
    for md_path in md_files:
        try:
            cfg = apply_managed_agent_runtime_model(
                parse_agent_md(md_path), source_path=md_path
            )
        except Exception as exc:
            logger.warning(
                "blueprint_refresh_parse_failed path={} error={}", md_path.name, exc
            )
            continue
        # Skip the lead — its file lives in the same directory but is owned
        # by :func:`reload`, not by this hot-path discovery.
        if cfg.role != "member" or not member_model_is_configured(cfg.model):
            continue
        if "#" in cfg.name or cfg.name == team.lead.name:
            # Same invariants ``load_team_from_dir`` enforces; silently
            # drop the bad file rather than 500 the listing endpoint.
            continue
        seen.add(cfg.name)
        existing = team.blueprints.get(cfg.name)
        if existing is None:
            team.blueprints[cfg.name] = MemberBlueprint(
                name=cfg.name,
                description=cfg.description or cfg.name,
                source_path=md_path,
            )
            logger.info("blueprint_added name={} path={}", cfg.name, md_path.name)
        elif existing.source_path != md_path:
            # File renamed but ``name:`` kept — repoint so the next spawn
            # reads from the new location.
            existing.source_path = md_path

    for name in list(team.blueprints.keys()):
        if name in seen:
            continue
        # Don't pull the rug out from under a live conversation: if any
        # instance of this blueprint is still in the roster, leave the
        # blueprint in place so its handle still resolves.
        if team.live_instances_for_blueprint(name):
            continue
        team.blueprints.pop(name, None)
        logger.info("blueprint_removed name={}", name)


# ── Skill cache invalidation ─────────────────────────────────────────────────


def invalidate_skill_cache() -> None:
    """Clear the ``discover_skills`` lru_cache so the next tool call
    picks up skill content or mode-scope edits. No team reload needed.
    """
    from app.agent.tools.builtin.skill import _discover_skills_cached

    _discover_skills_cached.cache_clear()
    logger.info("team_manager_skill_cache_invalidated")
