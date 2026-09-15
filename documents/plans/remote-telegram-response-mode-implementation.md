# Remote Telegram: Response Mode Preference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `RemotePairing.response_mode` (`summary` default, `live`) as a
settable preference, surfaced and toggleable from `/settings` — AC-55 of
the control-surface spec, and only AC-55. This phase adds the *preference*
with zero behavior change (default `summary` is exactly today's behavior);
it does not touch turn observation, activity rendering, or edit
throttling — that is AC-56/57, a separate, larger phase, since this
preference must exist and be persistable before anything can read it.

**Architecture:** One migration adds the column, following the exact
two-step precedent `notify_scope` already established (add the column,
bump `SCHEMA_HEAD`). `control.py` gains one write function,
`set_response_mode`, following the exact shape of `set_permission_mode`
but operating on `RemotePairing` (looked up by pairing id, not
`ChatSession` by session id) rather than a chat session — the first
control.py write that isn't chat-session-scoped. `formatting.py`'s
`render_settings_card` gains a `response_mode`/`response_mode_tokens` row,
mirroring the existing `mode`/`mode_tokens` row exactly. `actions.py`
wires it into the existing `/settings` card and adds one new capability
action kind, `set_response_mode`, whose capability's `session_id` field
is repurposed to hold the *pairing* id rather than a chat session id —
documented explicitly, since every other action kind uses that field for
an actual chat session.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, Alembic, asyncio, pytest, pytest-asyncio.

**Spec:** [`remote-telegram-control-surface.md`](remote-telegram-control-surface.md) — this plan implements exactly AC-55. AC-53 (providers read-only), AC-54 (onboarding), AC-56/57 (live activity content and throttled edits — depends on this phase's `response_mode` column existing), and AC-58 (final command-set) are later phases.

## Global Constraints

- This phase changes no observable bot behavior for any pairing that
  never touches the new toggle — `response_mode` defaults to `"summary"`,
  identical to today's only behavior.
- `set_response_mode` follows `set_permission_mode`'s exact validate-then-
  persist shape (an `ALLOWED_RESPONSE_MODES` tuple checked by name, a
  `db.get` + mutate + commit, wrapped in `ControlResult`) for consistency
  with every other control.py write, even though this one operates on
  `RemotePairing` instead of `ChatSession`.
- Every task cites its spec ACs, writes a failing test before implementation,
  and leaves the test suite green at its checkpoint.
- Commit at the end of each task.

---

## File and interface map

New units:

- `app/migrations/versions/00000066_add_remote_pairing_response_mode.py`.

Changed units:

- `app/core/schema_version.py` — `SCHEMA_HEAD` bumped to `"00000066"`.
- `app/models/remote.py` — `RemotePairing.response_mode`.
- `app/remote/control.py` — adds `ALLOWED_RESPONSE_MODES`, `set_response_mode`.
- `app/remote/formatting.py` — `render_settings_card` gains `response_mode`, `response_mode_tokens`.
- `app/remote/actions.py` — `_cmd_settings` renders the new row/buttons;
  new `_exec_set_response_mode`; `_execute_action` gains a
  `set_response_mode` branch.
- `tests/models/test_remote_models.py`, `tests/remote/test_control.py`,
  `tests/remote/test_formatting.py`, `tests/remote/test_actions.py` —
  new focused evidence.

---

### Task 1: Migration and model field

**ACs:** AC-55 (schema half)

**Files:**

- Create: `app/migrations/versions/00000066_add_remote_pairing_response_mode.py`
- Modify: `app/core/schema_version.py`
- Modify: `app/models/remote.py`
- Modify: `tests/models/test_remote_models.py`

**Interfaces:**

- Produces: `RemotePairing.response_mode: str` (default `"summary"`).

- [ ] **Step 1: Write the migration**

```python
# app/migrations/versions/00000066_add_remote_pairing_response_mode.py
"""Add remote_pairings.response_mode

Revision ID: 00000066
Revises: 00000065
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000066"
down_revision: str | Sequence[str] | None = "00000065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remote_pairings",
        sa.Column(
            "response_mode",
            sa.String(20),
            nullable=False,
            server_default="summary",
        ),
    )


def downgrade() -> None:
    op.drop_column("remote_pairings", "response_mode")
```

- [ ] **Step 2: Update the schema-head marker**

```python
# app/core/schema_version.py — line 16
SCHEMA_HEAD = "00000066"
```

- [ ] **Step 3: Write a failing model/migration test**

This file's real fixtures are `session` and `remote_connection` (not
`db_session` — verified directly against the file, which already defines
both, following `tests/remote/test_pairing.py`'s convention since no
shared `db_session` fixture exists in this codebase). Reuse the existing
`remote_connection` fixture already in this file rather than redefining
it, and match the existing `test_notify_scope_round_trips_a_non_default_value`
test's shape for the second test below.

```python
# tests/models/test_remote_models.py (add)
@pytest.mark.asyncio
async def test_new_pairing_defaults_response_mode_to_summary(
    session, remote_connection
):
    pairing = RemotePairing(
        connection_id=remote_connection.id,
        principal_id="user-1",
        destination_id="chat-1",
        label="My phone",
    )
    session.add(pairing)
    await session.commit()
    await session.refresh(pairing)
    assert pairing.response_mode == "summary"


@pytest.mark.asyncio
async def test_response_mode_round_trips_a_non_default_value(
    session, remote_connection
):
    pairing = RemotePairing(
        connection_id=remote_connection.id,
        principal_id="user-1",
        destination_id="chat-1",
        label="My phone",
        response_mode="live",
    )
    session.add(pairing)
    await session.commit()
    await session.refresh(pairing)

    from sqlmodel import select

    reloaded = (
        await session.exec(select(RemotePairing).where(RemotePairing.id == pairing.id))
    ).one()
    assert reloaded.response_mode == "live"
```

- [ ] **Step 4: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/models/test_remote_models.py -k response_mode
```

Expected: FAIL — `response_mode` is not a field on `RemotePairing`.

- [ ] **Step 5: Add the column to the model**

```python
# app/models/remote.py — inside class RemotePairing, after notify_scope
    response_mode: str = Field(
        default="summary",
        sa_column=Column(sa.String(20), nullable=False, server_default="summary"),
    )
```

- [ ] **Step 6: Run migration head and the model test**

```powershell
uv run alembic -c app/alembic.ini upgrade head
uv run pytest --no-cov -q tests/models/test_remote_models.py
```

- [ ] **Step 7: Lint**

```powershell
uv run ruff check app/models/remote.py tests/models/test_remote_models.py app/migrations/versions/00000066_add_remote_pairing_response_mode.py
uv run ty check app/models/remote.py
```

- [ ] **Step 8: Commit**

```bash
git add app/migrations/versions/00000066_add_remote_pairing_response_mode.py app/core/schema_version.py app/models/remote.py tests/models/test_remote_models.py
git commit -m "feat(remote): add remote_pairings.response_mode column"
```

---

### Task 2: `set_response_mode`

**ACs:** AC-55 (write half)

**Files:**

- Modify: `app/remote/control.py`
- Modify: `tests/remote/test_control.py`

**Interfaces:**

- Produces: `ALLOWED_RESPONSE_MODES: tuple[str, ...]` (`"summary"`, `"live"`),
  `async def set_response_mode(db: AsyncSession, pairing_id: str, mode: str) -> ControlResult`.
- Consumes: `app.models.remote.RemotePairing`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_control.py (add)
from app.models.remote import RemotePairing


@pytest_asyncio.fixture
async def remote_pairing() -> RemotePairing:
    """A minimal, standalone pairing row — this fixture creates its own
    RemoteConnection first since RemotePairing.connection_id is a
    non-nullable foreign key. Required fields verified directly against
    tests/models/test_remote_models.py's own remote_connection fixture."""
    async with db_module.async_session_factory() as db:
        from app.models.remote import RemoteConnection

        connection = RemoteConnection(
            adapter="telegram",
            label="My phone",
            enabled=True,
            adapter_principal_id="bot-1",
            adapter_username="my_evoflux_bot",
        )
        db.add(connection)
        await db.commit()
        await db.refresh(connection)

        pairing = RemotePairing(
            connection_id=connection.id,
            principal_id="user-1",
            destination_id="chat-1",
            label="My phone",
        )
        db.add(pairing)
        await db.commit()
        await db.refresh(pairing)
        return pairing


@pytest.mark.asyncio
async def test_set_response_mode_persists_a_valid_mode(
    remote_pairing: RemotePairing,
) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_response_mode(db, str(remote_pairing.id), "live")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(RemotePairing, remote_pairing.id)
        assert refreshed is not None
        assert refreshed.response_mode == "live"


@pytest.mark.asyncio
async def test_set_response_mode_rejects_unknown_mode(
    remote_pairing: RemotePairing,
) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_response_mode(
            db, str(remote_pairing.id), "verbose"
        )

    assert result.status == "invalid"


@pytest.mark.asyncio
async def test_set_response_mode_not_found_for_unknown_pairing() -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_response_mode(db, str(UUID(int=0)), "live")

    assert result.status == "not_found"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py -k response_mode
```

Expected: FAIL with `AttributeError: module 'app.remote.control' has no attribute 'set_response_mode'`.

- [ ] **Step 3: Implement `set_response_mode`**

```python
# app/remote/control.py — add to __all__: "ALLOWED_RESPONSE_MODES", "set_response_mode"
```

```python
# app/remote/control.py — new constant and function
#: The two response modes a phone may choose between (AC-55). Unlike
#: ALLOWED_REMOTE_MODES (permission modes, chat-session-scoped), this
#: preference lives on RemotePairing — one phone, one pairing, one
#: notion of how chatty its own turns should be.
ALLOWED_RESPONSE_MODES: tuple[str, ...] = ("summary", "live")


async def set_response_mode(
    db: AsyncSession, pairing_id: str, mode: str
) -> ControlResult:
    if mode not in ALLOWED_RESPONSE_MODES:
        return ControlResult(status="invalid", detail=mode)

    from app.models.remote import RemotePairing

    try:
        pairing_uuid = UUID(pairing_id)
    except ValueError:
        return ControlResult(status="not_found")
    pairing = await db.get(RemotePairing, pairing_uuid)
    if pairing is None:
        return ControlResult(status="not_found")

    pairing.response_mode = mode
    db.add(pairing)
    await db.commit()

    return ControlResult(status="ok")
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py
```

Expected: PASS (17 tests).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/control.py tests/remote/test_control.py
uv run ty check app/remote/control.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/control.py tests/remote/test_control.py
git commit -m "feat(remote): add response-mode control"
```

---

### Task 3: Settings-card display and toggle

**ACs:** AC-55 (display half)

**Files:**

- Modify: `app/remote/formatting.py`
- Modify: `tests/remote/test_formatting.py`

**Interfaces:**

- Changes `render_settings_card`: adds required `response_mode: str` and
  `response_mode_tokens: Mapping[str, str]` parameters, rendered as a
  `Responses` row with buttons, in the same position as the existing
  `Mode` row.

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_formatting.py (add)
def test_render_settings_card_shows_response_mode_and_its_toggle():
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
        response_mode_tokens={"summary": "r1", "live": "r2"},
    )
    assert "summary" in text
    button_tokens = {b.token for b in buttons}
    assert {"r1", "r2"} <= button_tokens
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py -k response_mode_and_its_toggle
```

Expected: FAIL — `render_settings_card()` missing required argument `response_mode`.

- [ ] **Step 3: Add the new row and buttons**

```python
# app/remote/formatting.py — render_settings_card's signature gains,
# right after agent_name:
    response_mode: str,
    response_mode_tokens: Mapping[str, str],
```

```python
# app/remote/formatting.py — inside render_settings_card, in the `lines`
# list, right after the "Lead agent" entry:
        "",
        f"<b>Responses</b>\n<code>{escape(response_mode)}</code>",
```

```python
# app/remote/formatting.py — inside render_settings_card, in the buttons
# list, right after the mode_tokens comprehension:
    buttons += [
        RemoteButton(text=f"Responses: {escape(name)}", token=token)
        for name, token in response_mode_tokens.items()
    ]
```

Every other existing test that calls `render_settings_card` (from Task 4
of the previous plan) now breaks — it's missing the two new required
arguments. Update each existing call site in
`tests/remote/test_formatting.py` to add
`response_mode="ask"` (or any placeholder string) and
`response_mode_tokens={}`, matching how those same tests already supply
empty dicts for `agent_tokens`/`model_tokens` when a test isn't about
those buttons specifically.

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
git commit -m "feat(remote): settings card shows and toggles response mode"
```

---

### Task 4: Wire the toggle into `/settings`

**ACs:** AC-55 (final wiring)

**Files:**

- Modify: `app/remote/actions.py`
- Modify: `tests/remote/test_actions.py`

**Interfaces:**

- Changes `_cmd_settings`: also renders the response-mode row/buttons.
- Produces (private): `_exec_set_response_mode`.
- Changes `_execute_action`: gains a `set_response_mode` branch.

`_ActionCapability.session_id` is repurposed for this one action kind to
hold the **pairing id**, not a chat session id — every other action kind
uses it for a real `ChatSession`. This is documented at both the issuing
and consuming ends so a future reader isn't confused by the field name.

- [ ] **Step 1: Write the failing test**

`mock_pairing` stands in for the return of `authorize()`, so its
`active_session_id`/`label`/`response_mode` can be anything controllable —
but its `.id` must resolve against a REAL `RemotePairing` row at callback
time (`control.set_response_mode` does a real `db.get(RemotePairing,
pairing_uuid)`), so this test creates a real pairing first (same shape as
Task 2's `remote_pairing` fixture, inlined here since it needs the same
`db` session the rest of the test already uses) and points the mock's
`.id` at that real row's id rather than a bare `uuid4()`.

```python
# tests/remote/test_actions.py — add to class TestSettings
    @pytest.mark.asyncio
    async def test_response_mode_callback_applies_the_selected_mode(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        from app.models.remote import RemoteConnection, RemotePairing

        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test", mode="work", session_type="main",
                permission_mode="auto",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            connection = RemoteConnection(
                adapter="telegram",
                label="My phone",
                enabled=True,
                adapter_principal_id="bot-1",
                adapter_username="my_evoflux_bot",
            )
            db.add(connection)
            await db.commit()
            await db.refresh(connection)

            real_pairing = RemotePairing(
                connection_id=connection.id,
                principal_id="user-1",
                destination_id="chat-1",
                label="My Phone",
            )
            db.add(real_pairing)
            await db.commit()
            await db.refresh(real_pairing)

            mock_pairing = MagicMock()
            mock_pairing.id = real_pairing.id
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"
            mock_pairing.response_mode = "summary"

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                settings_action = _make_action(text="/settings", connection_id=conn_id)
                await service.dispatch_command(db, settings_action)

            sent_buttons = adapter.sent_messages[-1].buttons
            live_token = next(
                b.token for b in sent_buttons if b.text == "Responses: live"
            )

            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=live_token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

            assert handled is True
            refreshed = await db.get(RemotePairing, real_pairing.id)
            assert refreshed is not None
            assert refreshed.response_mode == "live"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k response_mode_callback
```

Expected: FAIL — no `"Responses: live"` button exists yet in the sent card.

- [ ] **Step 3: Extend `_cmd_settings`**

```python
# app/remote/actions.py — inside _cmd_settings, alongside the existing
# mode_tokens/agent_tokens/model_tokens construction. pairing.id is the
# PAIRING's own id — repurposing the capability's session_id field to
# carry it (documented in _exec_set_response_mode below) since this
# preference lives on RemotePairing, not the chat session.
        response_mode_tokens = {
            mode: self._issue_settings_token(
                action, str(pairing.id), "set_response_mode", mode
            )
            for mode in control.ALLOWED_RESPONSE_MODES
        }
```

```python
# app/remote/actions.py — inside _cmd_settings, the render_settings_card
# call gains:
            response_mode=pairing.response_mode,
            response_mode_tokens=response_mode_tokens,
```

- [ ] **Step 4: Implement `_exec_set_response_mode` and wire the branch**

```python
# app/remote/actions.py — inside _execute_action, alongside the other
# set_* branches
        elif cap.action_kind == "set_response_mode":
            return await self._exec_set_response_mode(cap, action, db)
```

```python
# app/remote/actions.py — new method, near _exec_set_model
    async def _exec_set_response_mode(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        """cap.session_id here holds a PAIRING id, not a chat session id —
        this preference lives on RemotePairing, the one action kind in
        this module that isn't chat-session-scoped."""
        from app.remote import control

        result = await control.set_response_mode(db, cap.session_id, cap.action_target)
        await self._reply_control_result(
            action, result, f"Responses set to {cap.action_target}."
        )
        return True
```

- [ ] **Step 5: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py
```

Expected: PASS (every test in the file, including the new response-mode-callback one).

- [ ] **Step 6: Full remote suite, lint, type-check**

```powershell
uv run pytest --no-cov -q tests/remote/
uv run ruff check app/remote/ tests/remote/
uv run ty check app/remote/
```

- [ ] **Step 7: Commit**

```bash
git add app/remote/actions.py tests/remote/test_actions.py
git commit -m "feat(remote): wire response-mode toggle into /settings"
```

---

## Self-review notes

- **Spec coverage:** AC-55 is fully covered across all 4 tasks (schema →
  write → display → wiring). AC-56/57 (the actual live-content rendering
  this preference will eventually gate) are explicitly out of scope — this
  phase only adds a switch that, today, nothing reads.
- **Zero behavior change confirmed:** no code in `outbound.py`'s
  `observe()` or turn lifecycle is touched by this plan at all — the
  column exists and is settable, but nothing consumes it yet. A pairing
  that flips to `"live"` today gets no different behavior until AC-56/57
  ships and starts reading `RemotePairing.response_mode`.
- **The `session_id`-holds-a-pairing-id repurposing is flagged in three
  places** (module-level capability field, the issuing call site in
  `_cmd_settings`, and the consuming method's docstring) rather than
  once, since it's the one place this plan bends an existing field's
  meaning and a future reader debugging a capability token needs to find
  that explanation from any of the three places they'd naturally look.
- **Both fixture uncertainties flagged during drafting were resolved
  before finalizing this plan, not left for the executor:**
  `tests/models/test_remote_models.py`'s real fixtures are `session` and
  `remote_connection` (not `db_session`), and `RemoteConnection`'s real
  required constructor fields are `adapter`, `label`, `enabled`,
  `adapter_principal_id`, `adapter_username` — both confirmed by reading
  the file directly, and both plan code blocks above already reflect the
  verified versions.
