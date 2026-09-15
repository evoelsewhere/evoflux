# Remote Telegram: Settings Control (Mode, Model, Lead Agent) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a paired phone view and change a session's permission mode, model, and lead agent via `/settings` — Phase 2 of the control-surface spec, covering AC-48, AC-49, and AC-50. `bypass` permission mode is never offered or accepted remotely, under any code path.

**Architecture:** One new module, `app/remote/control.py`, owns every write (`set_permission_mode`, `set_lead_agent`, `set_model`) and the two bounded read helpers (`list_lead_names`, `list_model_ids`) that back the settings card's button rows — each write function replicates the exact persistence sequence its HTTP-route sibling already uses (same service-layer calls: `team_manager`, `app.agent.permission`, `app.models.chat`), so remote and desktop stay behaviorally identical, but as plain async functions `app/remote/actions.py` can call directly without HTTP. `formatting.py` gains settings-card support for the three new button rows. `actions.py` gains the `/settings` command and capability dispatch for taps.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, asyncio, pytest, pytest-asyncio.

**Spec:** [`remote-telegram-control-surface.md`](remote-telegram-control-surface.md) (amends `remote-channel-telegram.md` and `remote-telegram-response-ui.md`) — this plan implements exactly AC-48, AC-49, and AC-50. AC-51 through AC-58 (health, changes, providers-read-only, onboarding, response modes, command-set) are later phases.

## Global Constraints

- `bypass` is never settable remotely, under any command, button, callback, or forged token — excluded by name in `control.py`, not merely omitted from a menu (AC-48).
- Severity/mode/model/agent changes never bypass the service layer's own validation (`resolve_configured_lead` raises `ValueError` on an unknown name; the model registry is the sole source of valid model ids) — `control.py` surfaces those as a bounded `ControlResult`, never swallows or reinterprets them.
- Every write function takes an already-open `AsyncSession` (the caller's, per the existing `dispatch_command(db, action)` pattern in `actions.py`) — it never opens its own `async_session_factory()`.
- `app/remote/` depends only on the service layer (`app.services.*`, `app.agent.*`, `app.models.*`) — never on `app/api/routes/*` — with exactly one documented, deliberate exception: `get_registry` (model catalog) has no service-layer equivalent, so `control.py` imports it directly from `app.api.routes.agents`, called as a plain function (its `Query(...)` parameters are just OpenAPI metadata on plain defaults; it takes no `Request`/`Depends`-injected state).
- Every task cites its spec ACs, writes a failing test before implementation, and leaves the test suite green at its checkpoint.
- Commit at the end of each task.

---

## File and interface map

New units:

- `app/remote/control.py` — `ALLOWED_REMOTE_MODES`, `ControlResult`, `set_permission_mode`, `set_lead_agent`, `set_model`, `list_lead_names`, `list_model_ids`.
- `tests/remote/test_control.py`.

Changed units:

- `app/remote/formatting.py` — `render_settings_card` gains `mode_tokens`, `agent_name`/`agent_tokens`, `model_tokens` parameters; `redaction_policy`/`notify_scope`/`redaction_tokens`/`notify_scope_tokens` become optional (a later phase wires those; this phase's `/settings` doesn't supply them yet).
- `app/remote/actions.py` — `_SLASH_COMMANDS` gains `"settings"`; new `_cmd_settings`; new capability action kinds `set_mode`/`set_agent`/`set_model` in `_execute_action`.
- `tests/remote/test_formatting.py`, `tests/remote/test_actions.py` — updated/new focused evidence.

---

### Task 1: `set_permission_mode`

**ACs:** AC-48

**Files:**

- Create: `app/remote/control.py`
- Create: `tests/remote/test_control.py`

**Interfaces:**

- Produces: `ALLOWED_REMOTE_MODES: tuple[str, ...]` (`"ask"`, `"accept-edits"`, `"plan"`, `"auto"` — no `"bypass"`), `ControlResult` (`status: Literal["ok","invalid","not_found"]`, `detail: str = ""`), `async def set_permission_mode(db: AsyncSession, session_id: str, mode: str) -> ControlResult`.
- Consumes: `app.models.chat.ChatSession`, `app.services.team_manager.current_team_for_session`/`current_coding_team_for_session`, `app.agent.permission.get_services_for_stream`/`Mode`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_control.py
from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio

import app.core.db as db_module
from app.models.chat import ChatSession
from app.remote import control


@pytest_asyncio.fixture
async def chat_session() -> ChatSession:
    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Control test", mode="work", session_type="main")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


@pytest.mark.asyncio
async def test_set_permission_mode_persists_a_valid_mode(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "ask")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.permission_mode == "ask"


@pytest.mark.asyncio
async def test_set_permission_mode_rejects_bypass(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "bypass")

    assert result.status == "invalid"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.permission_mode != "bypass"


@pytest.mark.asyncio
async def test_set_permission_mode_rejects_unknown_mode(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "nonsense")

    assert result.status == "invalid"


@pytest.mark.asyncio
async def test_set_permission_mode_not_found_for_unknown_session() -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(UUID(int=0)), "ask")

    assert result.status == "not_found"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.remote.control'`.

- [ ] **Step 3: Implement `control.py` (mode-switching slice)**

```python
# app/remote/control.py
"""Mode/model/lead-agent control for the phone's /settings command.

Each write function replicates the exact persistence sequence its HTTP
route sibling already uses (app/api/routes/team/chat.py's
set_session_permission_mode/update_team_session_lead,
app/api/routes/team/webbridge.py's update_browser_session_model), as a
plain async function app/remote/actions.py can call directly — remote
and desktop must stay behaviorally identical, but app/remote/ never
depends on app/api/routes/* (see module docstring exception below for
the one deliberate departure: the model registry).

bypass is deliberately excluded from ALLOWED_REMOTE_MODES, checked by
name (not by list length or position) before anything else runs — a
phone that could enable bypass could silently disable every approval
prompt an operator relies on (AC-48).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession

__all__ = [
    "ALLOWED_REMOTE_MODES",
    "ControlResult",
    "set_permission_mode",
]

#: Every permission mode this phone may set — bypass excluded on purpose.
ALLOWED_REMOTE_MODES: tuple[str, ...] = ("ask", "accept-edits", "plan", "auto")

ControlStatus = Literal["ok", "invalid", "not_found", "conflict"]


@dataclass(frozen=True)
class ControlResult:
    """A bounded, adapter-neutral outcome for one control write."""

    status: ControlStatus
    detail: str = ""


async def set_permission_mode(
    db: AsyncSession, session_id: str, mode: str
) -> ControlResult:
    if mode not in ALLOWED_REMOTE_MODES:
        return ControlResult(status="invalid", detail=mode)

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        return ControlResult(status="not_found")
    session = await db.get(ChatSession, session_uuid)
    if session is None:
        return ControlResult(status="not_found")

    session.permission_mode = mode
    session_mode = session.mode
    session_workspace = session.workspace
    db.add(session)
    await db.commit()

    from app.services import team_manager

    team_obj = team_manager.current_team_for_session(session_id)
    if team_obj is None and session_mode == "coding" and session_workspace:
        team_obj = team_manager.current_coding_team_for_session(
            session_workspace, session_id
        )
    if team_obj is not None:
        team_obj.permission_mode = mode

    from app.agent.permission import Mode, get_services_for_stream

    for service in get_services_for_stream(session_id):
        service.set_mode(cast(Mode, mode))

    return ControlResult(status="ok")
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py
```

Expected: PASS (4 tests).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/control.py tests/remote/test_control.py
uv run ty check app/remote/control.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/control.py tests/remote/test_control.py
git commit -m "feat(remote): add permission-mode control, bypass excluded"
```

---

### Task 2: `set_lead_agent` and `list_lead_names`

**ACs:** AC-50

**Files:**

- Modify: `app/remote/control.py`
- Modify: `tests/remote/test_control.py`

**Interfaces:**

- Produces: `async def set_lead_agent(db: AsyncSession, session_id: str, lead_name: str) -> ControlResult`, `async def list_lead_names(app_mode: str, *, limit: int = 5) -> list[str]`.
- Consumes: `app.models.chat.normalize_mode`, `app.services.team_manager.resolve_configured_lead`/`configured_lead_rosters`/`find_team_for_session`/`stop_sessions`, `app.services.memory_stream_store.running_session_ids`.

- [ ] **Step 1: Write the failing tests**

This worktree's isolated test config dirs (`pytest.ini`'s `EVOFLUX_CONFIG_DIR`
etc.) have no real agent configs seeded, so `configured_lead_rosters`
returns empty there — verified by running the naive version of these tests
first. Mock it with one controlled, fake roster instead of depending on
whatever happens to exist on disk in this environment; patched at the
module level so both `list_lead_names`'s direct call and
`resolve_configured_lead`'s own internal call see the same fake roster.

```python
# tests/remote/test_control.py (add)
class _FakeLead:
    """Stand-in for the roster's real lead-agent config object — only
    ``.name`` is read by list_lead_names/resolve_configured_lead."""

    def __init__(self, name: str) -> None:
        self.name = name


def _mock_one_lead_roster(monkeypatch: pytest.MonkeyPatch, name: str = "evoflux") -> None:
    monkeypatch.setattr(
        "app.services.team_manager.configured_lead_rosters",
        lambda mode: (name, [(_FakeLead(name), None, [])]),
    )


@pytest.mark.asyncio
async def test_list_lead_names_returns_configured_leads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")

    names = await control.list_lead_names("work")

    assert names == ["evoflux"]


@pytest.mark.asyncio
async def test_list_lead_names_is_bounded_to_five(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rosters = [(_FakeLead(f"lead-{i}"), None, []) for i in range(8)]
    monkeypatch.setattr(
        "app.services.team_manager.configured_lead_rosters",
        lambda mode: ("lead-0", fake_rosters),
    )

    names = await control.list_lead_names("work")

    assert len(names) == 5


@pytest.mark.asyncio
async def test_set_lead_agent_persists_a_valid_lead(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")

    async with db_module.async_session_factory() as db:
        result = await control.set_lead_agent(db, str(chat_session.id), "evoflux")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.agent_name == "evoflux"


@pytest.mark.asyncio
async def test_set_lead_agent_rejects_unknown_name(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")

    async with db_module.async_session_factory() as db:
        result = await control.set_lead_agent(
            db, str(chat_session.id), "not-a-real-configured-lead-name"
        )

    assert result.status == "invalid"


@pytest.mark.asyncio
async def test_set_lead_agent_conflicts_while_session_is_running(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")
    monkeypatch.setattr(
        "app.services.memory_stream_store.running_session_ids",
        lambda: {str(chat_session.id)},
    )

    async with db_module.async_session_factory() as db:
        result = await control.set_lead_agent(db, str(chat_session.id), "evoflux")

    assert result.status == "conflict"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py -k "lead"
```

Expected: FAIL with `AttributeError: module 'app.remote.control' has no attribute 'list_lead_names'`.

- [ ] **Step 3: Implement the lead-switching slice**

```python
# app/remote/control.py — add to __all__: "set_lead_agent", "list_lead_names"
```

```python
# app/remote/control.py — new functions
async def list_lead_names(app_mode: str, *, limit: int = 5) -> list[str]:
    """A short, stable-order list of configured lead-agent names for
    *app_mode* ("work"/"coding") — bounded for a phone's button row, same
    pattern already used for workflow/project menu items in actions.py."""
    from app.services import team_manager

    try:
        _default_lead, rosters = team_manager.configured_lead_rosters(app_mode)
    except ValueError:
        return []
    return [lead.name for lead, _path, _members in rosters][:limit]


async def set_lead_agent(
    db: AsyncSession, session_id: str, lead_name: str
) -> ControlResult:
    from app.models.chat import normalize_mode
    from app.services import memory_stream_store as stream_store
    from app.services import team_manager

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        return ControlResult(status="not_found")
    session = await db.get(ChatSession, session_uuid)
    if session is None:
        return ControlResult(status="not_found")
    if session.parent_session_id is not None:
        return ControlResult(status="not_found")

    live_team = team_manager.find_team_for_session(session_id)
    if session_id in stream_store.running_session_ids() or (
        live_team is not None
        and any(member.state == "working" for member in live_team.all_members)
    ):
        return ControlResult(
            status="conflict",
            detail="Finish or stop the active task before changing lead.",
        )

    app_mode = normalize_mode(session.mode)
    try:
        selected = team_manager.resolve_configured_lead(app_mode, lead_name)
    except ValueError as exc:
        return ControlResult(status="invalid", detail=str(exc))

    if session.agent_name != selected:
        session.agent_name = selected
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await team_manager.stop_sessions({session_id})

    return ControlResult(status="ok")
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py
```

Expected: PASS (9 tests).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/control.py tests/remote/test_control.py
uv run ty check app/remote/control.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/control.py tests/remote/test_control.py
git commit -m "feat(remote): add lead-agent control"
```

---

### Task 3: `set_model` and `list_model_ids`

**ACs:** AC-49

**Files:**

- Modify: `app/remote/control.py`
- Modify: `tests/remote/test_control.py`

**Interfaces:**

- Produces: `async def set_model(db: AsyncSession, session_id: str, model_id: str, *, thinking_level: str | None = None) -> ControlResult`, `async def list_model_ids(app_mode: str | None = None, *, limit: int = 5) -> list[str]`.
- Consumes: `app.api.routes.agents.get_registry` (the one documented exception to the service-layer-only rule — see module docstring), `app.agent.providers.thinking.accepts_thinking_level`.

- [ ] **Step 1: Write the failing tests**

Same lesson as Task 2's lead-agent tests: this environment happens to have
real models available via an ambiently-configured provider, but that isn't
guaranteed on every machine this suite runs on, so mock `get_registry`
with a small, controlled fake instead of depending on it.

```python
# tests/remote/test_control.py (add)
class _FakeModelEntry:
    """Stand-in for the real registry's ModelCatalogEntry — only ``.id``
    is read by list_model_ids/set_model."""

    def __init__(self, id: str) -> None:
        self.id = id


class _FakeRegistry:
    def __init__(self, model_ids: list[str]) -> None:
        self.models = [_FakeModelEntry(mid) for mid in model_ids]


def _mock_registry(monkeypatch: pytest.MonkeyPatch, model_ids: list[str]) -> None:
    async def _fake_get_registry(*args: object, **kwargs: object) -> _FakeRegistry:
        return _FakeRegistry(model_ids)

    monkeypatch.setattr("app.api.routes.agents.get_registry", _fake_get_registry)


@pytest.mark.asyncio
async def test_list_model_ids_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_registry(monkeypatch, [f"provider:model-{i}" for i in range(8)])

    model_ids = await control.list_model_ids(limit=5)

    assert len(model_ids) == 5


@pytest.mark.asyncio
async def test_set_model_persists_a_valid_model(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_registry(monkeypatch, ["provider:model-a", "provider:model-b"])

    async with db_module.async_session_factory() as db:
        result = await control.set_model(db, str(chat_session.id), "provider:model-a")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.model == "provider:model-a"


@pytest.mark.asyncio
async def test_set_model_rejects_unknown_model_id(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_registry(monkeypatch, ["provider:model-a"])

    async with db_module.async_session_factory() as db:
        result = await control.set_model(
            db, str(chat_session.id), "not-a-real-provider:not-a-real-model"
        )

    assert result.status == "invalid"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py -k "model"
```

Expected: FAIL with `AttributeError: module 'app.remote.control' has no attribute 'list_model_ids'`.

- [ ] **Step 3: Implement the model-switching slice**

```python
# app/remote/control.py — add to __all__: "set_model", "list_model_ids"
```

```python
# app/remote/control.py — new functions
async def list_model_ids(app_mode: str | None = None, *, limit: int = 5) -> list[str]:
    """A short, catalog-order list of registered model ids — bounded for a
    phone's button row. There is no curated "recommended models" concept
    in the registry today (every provider-visible model is returned
    unbounded), so this is a simple positional cap, not a ranking.
    Uses the module-level `cast` (imported at the top of the file, next
    to Literal used for ControlStatus) — a local `from typing import
    Literal, cast` here is flagged unused by ruff, since the Literal
    reference below is inside a string forward-ref, not a live name."""
    from app.api.routes.agents import get_registry

    mode_arg = cast("Literal['work', 'coding'] | None", app_mode)
    registry = await get_registry(mode=mode_arg)
    return [entry.id for entry in registry.models][:limit]


async def set_model(
    db: AsyncSession,
    session_id: str,
    model_id: str,
    *,
    thinking_level: str | None = None,
) -> ControlResult:
    from app.api.routes.agents import get_registry
    from app.agent.providers.thinking import accepts_thinking_level

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        return ControlResult(status="not_found")
    session = await db.get(ChatSession, session_uuid)
    if session is None:
        return ControlResult(status="not_found")

    registry = await get_registry()
    selected = next((entry for entry in registry.models if entry.id == model_id), None)
    if selected is None:
        return ControlResult(status="invalid", detail=model_id)
    if thinking_level is not None and not accepts_thinking_level(
        model_id, thinking_level
    ):
        return ControlResult(status="invalid", detail=thinking_level)

    session.model = model_id
    session.thinking_level = thinking_level
    db.add(session)
    await db.commit()

    return ControlResult(status="ok")
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py
```

Expected: PASS (12 tests).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/control.py tests/remote/test_control.py
uv run ty check app/remote/control.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/control.py tests/remote/test_control.py
git commit -m "feat(remote): add model control via the registry"
```

---

### Task 4: Settings-card rendering

**ACs:** AC-48/49/50 (display half)

**Files:**

- Modify: `app/remote/formatting.py`
- Modify: `tests/remote/test_formatting.py`

**Interfaces:**

- Changes `render_settings_card`: adds `mode_tokens: Mapping[str, str]`, `agent_name: str`, `agent_tokens: Mapping[str, str]`, `model_tokens: Mapping[str, str]` (all required — every caller updates); `redaction_policy`, `notify_scope`, `redaction_tokens`, `notify_scope_tokens` become optional (`None`/empty default) since no caller supplies them yet.

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_formatting.py (add)
def test_render_settings_card_shows_mode_model_and_agent_buttons():
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="anthropic:claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        mode_tokens={"ask": "m1", "auto": "m2"},
        agent_tokens={"evoflux": "a1", "explorer": "a2"},
        model_tokens={"anthropic:claude-sonnet-5": "d1"},
    )
    assert "ask" in text
    assert "anthropic:claude-sonnet-5" in text
    assert "evoflux" in text
    button_tokens = {b.token for b in buttons}
    assert {"m1", "m2", "a1", "a2", "d1"} <= button_tokens


def test_render_settings_card_never_offers_a_bypass_button():
    _, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="anthropic:claude-sonnet-5",
        permission_mode="auto",
        agent_name="evoflux",
        mode_tokens={"auto": "m1", "bypass": "should-never-appear"},
        agent_tokens={},
        model_tokens={},
    )
    assert "should-never-appear" not in {b.token for b in buttons}
    assert not any("bypass" in b.text.lower() for b in buttons)


def test_render_settings_card_omits_redaction_section_when_not_supplied():
    text, _ = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="anthropic:claude-sonnet-5",
        permission_mode="auto",
        agent_name="evoflux",
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
    )
    assert "Outbound redaction" not in text
    assert "Notifications" not in text
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py -k settings_card
```

Expected: FAIL — `render_settings_card()` missing required arguments `agent_name`, `mode_tokens`, `agent_tokens`, `model_tokens`.

- [ ] **Step 3: Rewrite `render_settings_card`**

```python
# app/remote/formatting.py — replace render_settings_card in full
def render_settings_card(
    *,
    connection_label: str,
    model: str,
    permission_mode: str,
    agent_name: str,
    mode_tokens: Mapping[str, str],
    agent_tokens: Mapping[str, str],
    model_tokens: Mapping[str, str],
    redaction_policy: str | None = None,
    notify_scope: str | None = None,
    redaction_tokens: Mapping[str, str] = {},
    notify_scope_tokens: Mapping[str, str] = {},
) -> tuple[str, tuple[RemoteButton, ...]]:
    lines = [
        "<b>⚙️ Settings</b>",
        "",
        f"<b>Connection</b>\n{escape(connection_label)}",
        "",
        f"<b>Mode</b>\n<code>{escape(permission_mode)}</code>",
        "",
        f"<b>Model</b>\n<code>{escape(model)}</code>",
        "",
        f"<b>Lead agent</b>\n<code>{escape(agent_name)}</code>",
    ]
    if notify_scope is not None:
        lines += ["", f"<b>Notifications</b>\n<code>{escape(notify_scope)}</code>"]
    if redaction_policy is not None:
        lines += [
            "",
            f"<b>Outbound redaction</b>\n<code>{escape(redaction_policy)}</code>",
        ]
    text = "\n".join(lines)

    buttons: list[RemoteButton] = [
        RemoteButton(text=f"Mode: {escape(name)}", token=token)
        for name, token in mode_tokens.items()
        if name != "bypass"
    ]
    buttons += [
        RemoteButton(text=f"Agent: {escape(name)}", token=token)
        for name, token in agent_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Model: {escape(name)}", token=token)
        for name, token in model_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Redaction: {escape(name)}", token=token)
        for name, token in redaction_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Notify: {escape(name)}", token=token)
        for name, token in notify_scope_tokens.items()
    ]
    return text, tuple(buttons)
```

Note the `if name != "bypass"` filter on the mode-button comprehension: defense in depth alongside `control.ALLOWED_REMOTE_MODES` already excluding it at the source (AC-48's boundary is enforced at both the write path and the render path, so a bug in one is never the only thing standing between a phone and bypass).

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py
```

Expected: PASS (all tests in the file).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/formatting.py tests/remote/test_formatting.py
uv run ty check app/remote/formatting.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/formatting.py tests/remote/test_formatting.py
git commit -m "feat(remote): settings card renders mode/model/agent as buttons, bypass excluded"
```

---

### Task 5: Wire `/settings` into `actions.py`

**ACs:** AC-48, AC-49, AC-50, AC-58 (partial — adds `settings` to the command set)

**Files:**

- Modify: `app/remote/actions.py`
- Modify: `tests/remote/test_actions.py`

**Interfaces:**

- Changes `_SLASH_COMMANDS`: adds `"settings"`.
- Produces (private): `_cmd_settings`, `_exec_set_mode`, `_exec_set_agent`, `_exec_set_model`.
- Consumes: `app.remote.control` (all six public names), `app.remote.formatting.render_settings_card`, `app.models.chat.ChatSession`/`normalize_mode`.

- [ ] **Step 1: Write the failing tests**

This file's established pattern (see `TestStatus`) mocks
`service._pairing_service.authorize` directly rather than persisting a
real `RemotePairing` row — `mock_db = MagicMock()` is enough when the
command never actually touches the DB. `/settings` *does* need a real
`db.get(ChatSession, ...)` round-trip once `active_session_id` is set, so
these three tests use a real DB session (`app.core.db.async_session_factory`,
already used the same way in `tests/remote/test_control.py`) instead of
`MagicMock()`, while still mocking `authorize` for pairing/authorization
exactly like every other command test in this file.

```python
# tests/remote/test_actions.py — add near the top, alongside the existing imports
import app.core.db as db_module
from app.models.chat import ChatSession
```

```python
# tests/remote/test_actions.py (add)
class TestSettings:
    @pytest.mark.asyncio
    async def test_settings_command_shows_current_mode_model_and_agent(
        self, service: RemoteActionService
    ) -> None:
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test",
                mode="work",
                session_type="main",
                permission_mode="ask",
                model="anthropic:claude-sonnet-5",
                agent_name="evoflux",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                action = _make_action(text="/settings")
                result = await service.dispatch_command(db, action)

        assert result.status == "ok"
        assert "ask" in result.text
        assert "anthropic:claude-sonnet-5" in result.text
        assert "evoflux" in result.text

    @pytest.mark.asyncio
    async def test_settings_command_without_active_session_is_friendly(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        mock_pairing = MagicMock()
        mock_pairing.active_session_id = None

        with patch.object(
            service._pairing_service, "authorize", return_value=mock_pairing
        ):
            action = _make_action(text="/settings")
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"
        assert "start" in result.text.lower()

    @pytest.mark.asyncio
    async def test_mode_callback_applies_the_selected_mode(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test",
                mode="work",
                session_type="main",
                permission_mode="auto",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                settings_action = _make_action(text="/settings", connection_id=conn_id)
                await service.dispatch_command(db, settings_action)

            sent_buttons = adapter.sent_messages[-1].buttons
            ask_token = next(b.token for b in sent_buttons if b.text == "Mode: ask")

            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=ask_token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

            assert handled is True
            refreshed = await db.get(ChatSession, session.id)
            assert refreshed is not None
            assert refreshed.permission_mode == "ask"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k Settings
```

Expected: FAIL — `/settings` falls through to `_cmd_help` (unknown command), so none of the mode/model/agent assertions match.

- [ ] **Step 3: Add `/settings` to the known commands and dispatch**

```python
# app/remote/actions.py — _SLASH_COMMANDS
_SLASH_COMMANDS: frozenset[str] = frozenset(
    {"start", "help", "status", "new", "stop", "unpair", "actions", "settings"}
)
```

```python
# app/remote/actions.py — inside dispatch_command, alongside the other elif branches
        elif command == "settings":
            return await self._cmd_settings(db, action)
```

- [ ] **Step 4: Implement `_cmd_settings`**

```python
# app/remote/actions.py — new method, near _cmd_status
    async def _cmd_settings(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        from app.models.chat import ChatSession, normalize_mode
        from app.remote import control
        from app.remote.formatting import render_settings_card

        pairing = await self._pairing_service.authorize(
            db,
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
        )
        if pairing is None:
            return RemoteActionResult(status="unauthorized")

        if pairing.active_session_id is None:
            return RemoteActionResult(
                status="ok",
                text="No active task yet — send a message to start one, then /settings shows its mode/model/agent.",
            )

        session = await db.get(ChatSession, pairing.active_session_id)
        if session is None:
            return RemoteActionResult(
                status="ok",
                text="No active task yet — send a message to start one, then /settings shows its mode/model/agent.",
            )

        app_mode = normalize_mode(session.mode)
        session_id = str(session.id)

        mode_tokens = {
            mode: self._issue_settings_token(action, session_id, "set_mode", mode)
            for mode in control.ALLOWED_REMOTE_MODES
        }
        agent_names = await control.list_lead_names(app_mode)
        agent_tokens = {
            name: self._issue_settings_token(action, session_id, "set_agent", name)
            for name in agent_names
        }
        model_ids = await control.list_model_ids(app_mode)
        model_tokens = {
            model_id: self._issue_settings_token(action, session_id, "set_model", model_id)
            for model_id in model_ids
        }

        text, buttons = render_settings_card(
            connection_label=pairing.label or "This phone",
            model=session.model or "(default)",
            permission_mode=session.permission_mode,
            agent_name=session.agent_name or "(default)",
            mode_tokens=mode_tokens,
            agent_tokens=agent_tokens,
            model_tokens=model_tokens,
        )

        if self._adapter is not None:
            await self._send(action.principal.destination_id, text, buttons=buttons)
        return RemoteActionResult(status="ok", text=text)

    def _issue_settings_token(
        self,
        action: RemoteInboundAction,
        session_id: str,
        action_kind: str,
        action_target: str,
    ) -> str:
        return self._issue_token(
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
            destination_id=action.principal.destination_id,
            session_id=session_id,
            action_kind=action_kind,
            action_target=action_target,
        )
```

`/settings` already sends its own message with buttons (like `/actions` does) — add it to the existing "already sent its own message" guard in `runtime.py`'s `_handle_command` alongside `actions`, so the plain-text result isn't sent a second time:

```python
# app/remote/runtime.py — inside _handle_command
        command = (action.text or "").strip().split(maxsplit=1)[0][1:].lower()
        if command in ("actions", "settings"):
            return
```

- [ ] **Step 5: Run and confirm the settings-display tests pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k "settings_command"
```

Expected: PASS.

- [ ] **Step 6: Write failing tests for the three new capability action kinds, then implement `_execute_action`'s new branches**

```python
# app/remote/actions.py — inside _execute_action
        elif cap.action_kind == "set_mode":
            return await self._exec_set_mode(cap, action)
        elif cap.action_kind == "set_agent":
            return await self._exec_set_agent(cap, action)
        elif cap.action_kind == "set_model":
            return await self._exec_set_model(cap, action)
```

```python
# app/remote/actions.py — new methods, near _exec_workflow_start
    async def _exec_set_mode(
        self, cap: _ActionCapability, action: RemoteInboundAction
    ) -> bool:
        from app.core.db import async_session_factory
        from app.remote import control

        async with async_session_factory() as db:
            result = await control.set_permission_mode(
                db, cap.session_id, cap.action_target
            )
        await self._reply_control_result(action, result, f"Mode set to {cap.action_target}.")
        return True

    async def _exec_set_agent(
        self, cap: _ActionCapability, action: RemoteInboundAction
    ) -> bool:
        from app.core.db import async_session_factory
        from app.remote import control

        async with async_session_factory() as db:
            result = await control.set_lead_agent(db, cap.session_id, cap.action_target)
        await self._reply_control_result(
            action, result, f"Lead agent set to {cap.action_target}."
        )
        return True

    async def _exec_set_model(
        self, cap: _ActionCapability, action: RemoteInboundAction
    ) -> bool:
        from app.core.db import async_session_factory
        from app.remote import control

        async with async_session_factory() as db:
            result = await control.set_model(db, cap.session_id, cap.action_target)
        await self._reply_control_result(action, result, f"Model set to {cap.action_target}.")
        return True

    async def _reply_control_result(
        self, action: RemoteInboundAction, result, success_text: str
    ) -> None:
        if result.status == "ok":
            text = success_text
        elif result.status == "conflict":
            text = result.detail or "That can't be changed right now."
        elif result.status == "not_found":
            text = "That task no longer exists."
        else:
            text = f"That value isn't valid: {result.detail}" if result.detail else "That value isn't valid."
        await self._reply_text(action.principal.destination_id, text)
```

- [ ] **Step 7: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py
```

Expected: PASS (every test in the file, including the new mode-callback one).

- [ ] **Step 8: Full remote suite, lint, type-check**

```powershell
uv run pytest --no-cov -q tests/remote/
uv run ruff check app/remote/actions.py app/remote/runtime.py tests/remote/test_actions.py
uv run ty check app/remote/
```

- [ ] **Step 9: Commit**

```bash
git add app/remote/actions.py app/remote/runtime.py tests/remote/test_actions.py
git commit -m "feat(remote): wire /settings command with mode/model/agent switching"
```

---

## Self-review notes

- **Spec coverage:** AC-48 (Tasks 1, 4 filter, 5's `ALLOWED_REMOTE_MODES` usage), AC-49 (Task 3, 5), AC-50 (Task 2, 5) are each covered. AC-51–58 are explicitly out of scope, next phases.
- **The bypass boundary is enforced twice, independently:** `control.ALLOWED_REMOTE_MODES` (write path, Task 1) and `render_settings_card`'s `if name != "bypass"` filter (render path, Task 4) — a bug in either alone still can't produce a working bypass button, matching the spec's "excluded in the remote layer itself" requirement.
- **Type/name consistency:** `ControlResult.status` values (`ok`/`invalid`/`not_found`/`conflict`) are used identically in `_reply_control_result` (Task 5) and match every test assertion in Tasks 1-3. `render_settings_card`'s parameter names (Task 4) match every call site in `_cmd_settings` (Task 5) exactly.
- **Task 5's tests were verified against the real file, not guessed:** `tests/remote/test_actions.py`'s actual fixtures (`service`, `adapter`, `_make_action`) and established pattern (mock `service._pairing_service.authorize`, matching `TestStatus`'s existing tests) were read directly and matched exactly — `FakeAdapter.sent_messages` (not a guessed `.sent`) is this file's real attribute name for delivered `RemoteOutboundMessage`s, confirmed at `test_actions.py:34`.
