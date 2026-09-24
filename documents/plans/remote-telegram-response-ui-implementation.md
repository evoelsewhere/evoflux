# Remote Telegram Response UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Telegram remote-access channel HTML-formatted, alive-feeling responses; complete its existing "notify me about desktop-started work too" Goal; and add a read-mostly `/settings` view plus a guided project/prompt picker — all within Tasks 7-9 of the in-progress Telegram feature, which this plan extends rather than reopens.

**Architecture:** One new rendering module (`app/remote/formatting.py`) becomes the single place literal HTML is written; `RemoteProjection` (outbound.py) gains a per-turn status-message lifecycle (create-then-edit, using the adapter's existing correlation-id mechanism) plus a cached "active pairing" view so it can route completions for sessions it never explicitly registered; `RemoteActionService` (actions.py) gains new capability-token action kinds for `/settings`, the guided picker, and on-demand drill-down content.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/Alembic, asyncio, httpx, pytest.

**Spec:** [`remote-telegram-response-ui.md`](remote-telegram-response-ui.md) (amends [`remote-channel-telegram.md`](remote-channel-telegram.md))

## Global Constraints

- Every outbound message uses Telegram HTML parse mode; every value not authored as a static string inside `formatting.py` passes through `html.escape` before interpolation, applied after outbound redaction, never before.
- A phone-admitted turn's status message is created once and edited at most once more (to its final done/error form); no other edit, no periodic progress text. The native Telegram typing indicator, not message edits, carries the "still working" feeling.
- Running-state/status text contains only the task title and admission status; never a tool name, file path, or content fragment (preserves AC-20's event allowlist).
- `/settings` may change outbound redaction policy and `notify_scope` only. Model and permission mode render as plain text with no button, ever.
- Drill-down content ("Full diff", "Tool log") is the current turn's own already-persisted output only, fetched on demand and never cached beyond the existing 10-minute capability-token TTL — no new durable store.
- `RemoteProjection.observe` stays synchronous, bounded, and non-blocking; any database read needed for a newly-widened case happens in the async delivery path, never inside `observe()` itself.
- Every task cites its spec ACs, writes a failing test before implementation, and leaves the test suite green at its checkpoint.
- Commit at the end of each task.

---

## File and interface map

New units:

- `app/remote/formatting.py` — HTML escaping helper and one builder per card type.
- `app/remote/turn_activity.py` — queries a turn's persisted tool-call messages; shared by the done-card summary and the drill-down buttons.
- `app/migrations/versions/00000065_add_remote_pairing_notify_scope.py` — adds `remote_pairings.notify_scope`.
- `tests/remote/test_formatting.py`, `tests/remote/test_turn_activity.py` — focused new-module evidence.

Changed units:

- `app/remote/contracts.py` — `RemoteAdapter` Protocol gains `indicate_typing`.
- `app/remote/telegram/client.py` — `send_text`/`edit_text` gain `parse_mode`; new `send_chat_action`.
- `app/remote/telegram/adapter.py` — passes `parse_mode="HTML"`; implements `indicate_typing`.
- `app/models/remote.py` — `RemotePairing.notify_scope`.
- `app/remote/outbound.py` — status-message lifecycle, active-pairing cache, widened `observe()`, formatting.py adoption.
- `app/remote/runtime.py` — wires the active-pairing cache and cross-references `actions`/`projection`.
- `app/remote/actions.py` — `/settings`, guided picker, drill-down capability handling, formatting.py adoption.
- `app/remote/gates.py` — formatting.py adoption.
- `tests/remote/telegram/test_client.py`, `tests/remote/telegram/test_adapter.py`, `tests/remote/test_outbound.py`, `tests/remote/test_actions.py`, `tests/remote/test_gates.py`, `tests/remote/test_runtime.py`, `tests/models/test_remote_models.py` — updated/new focused evidence.

---

### Task 1: HTML rendering layer

**ACs:** AC-24 (revised)

**Files:**

- Create: `app/remote/formatting.py`
- Create: `tests/remote/test_formatting.py`

**Interfaces:**

- Produces `escape(value: str) -> str`, `render_status_card`, `render_done_card`, `render_error_card`, `render_gate_card`, `render_settings_card`, `render_project_picker`, `render_prompt_suggestions` — every builder returns `tuple[str, tuple[RemoteButton, ...]]`.
- Consumes `app.remote.contracts.RemoteButton`.

- [ ] **Step 1: Write escaping and golden-output tests**

```python
# tests/remote/test_formatting.py
import html as html_lib

from app.remote import formatting
from app.remote.contracts import RemoteButton


def test_escape_neutralizes_tag_characters():
    assert formatting.escape("<script>&") == "&lt;script&gt;&amp;"


def test_render_status_card_escapes_title():
    text, buttons = formatting.render_status_card(
        title="Fix <b>tests</b>", status="accepted"
    )
    assert "<b>tests</b>" not in text
    assert html_lib.escape("Fix <b>tests</b>") in text
    assert buttons == ()


def test_render_done_card_escapes_summary_and_adds_buttons():
    text, buttons = formatting.render_done_card(
        title="Fix auth tests",
        elapsed_seconds=72.3,
        summary_lines=["<script>alert(1)</script>", "tests/conftest.py"],
        tool_call_count=4,
        diff_token="diff-tok",
        toollog_token="log-tok",
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
    assert "1m 12s" in text
    assert "4 tool calls" in text
    assert buttons == (
        RemoteButton(text="\U0001f4c4 Full diff", token="diff-tok"),
        RemoteButton(text="\U0001f9fe Tool log", token="log-tok"),
    )


def test_render_done_card_omits_buttons_when_no_tokens():
    _, buttons = formatting.render_done_card(
        title="No-op turn",
        elapsed_seconds=1.0,
        summary_lines=[],
        tool_call_count=0,
        diff_token=None,
        toollog_token=None,
    )
    assert buttons == ()


def test_render_error_card_escapes_message():
    text, buttons = formatting.render_error_card(
        title="Add rate limiter",
        message="ModuleNotFoundError: <redis>",
        toollog_token="log-tok",
    )
    assert "&lt;redis&gt;" in text
    assert len(buttons) == 1


def test_render_settings_card_never_emits_model_or_permission_buttons():
    text, buttons = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask each time",
        redaction_policy="standard",
        notify_scope="all",
        redaction_tokens={"strict": "r1", "off": "r2"},
        notify_scope_tokens={"all": "n1", "remote_only": "n2"},
    )
    button_texts = [b.text for b in buttons]
    assert not any("model" in t.lower() for t in button_texts)
    assert not any("permission" in t.lower() for t in button_texts)
    assert any("strict" in t.lower() for t in button_texts)
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.remote.formatting'`.

- [ ] **Step 3: Implement the escaping helper and card builders**

```python
# app/remote/formatting.py
from __future__ import annotations

import html
from collections.abc import Mapping, Sequence

from app.remote.contracts import RemoteButton

__all__ = [
    "escape",
    "format_elapsed",
    "render_status_card",
    "render_done_card",
    "render_error_card",
    "render_gate_card",
    "render_settings_card",
    "render_project_picker",
    "render_prompt_suggestions",
]

_STATUS_ICON = {"accepted": "\U0001f527", "queued": "⏳", "pending": "⏳"}


def escape(value: str) -> str:
    """The only place raw text becomes safe to place inside an HTML tag."""
    return html.escape(value, quote=False)


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


def render_status_card(*, title: str, status: str) -> tuple[str, tuple[RemoteButton, ...]]:
    icon = _STATUS_ICON.get(status, "\U0001f527")
    text = f"{icon} <b>{escape(title)}</b>\n<i>{escape(status)}</i>"
    return text, ()


def render_done_card(
    *,
    title: str,
    elapsed_seconds: float,
    summary_lines: Sequence[str],
    tool_call_count: int,
    diff_token: str | None,
    toollog_token: str | None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    header = f"✅ <b>{escape(title)}</b> · {format_elapsed(elapsed_seconds)}"
    lines = [escape(line) for line in summary_lines]
    parts = [header]
    if lines:
        parts.append("\n".join(lines))
    parts.append(f"<b>{tool_call_count} tool calls</b>")
    text = "\n\n".join(parts)
    buttons: list[RemoteButton] = []
    if diff_token:
        buttons.append(RemoteButton(text="\U0001f4c4 Full diff", token=diff_token))
    if toollog_token:
        buttons.append(RemoteButton(text="\U0001f9fe Tool log", token=toollog_token))
    return text, tuple(buttons)


def render_error_card(
    *, title: str, message: str, toollog_token: str | None
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = f"❌ <b>{escape(title)}</b>\n\n<b>Error:</b> {escape(message)}"
    buttons = (
        (RemoteButton(text="\U0001f9fe Tool log", token=toollog_token),)
        if toollog_token
        else ()
    )
    return text, buttons


def render_gate_card(
    *, title: str, body: str, actions: Sequence[tuple[str, str]]
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = f"\U0001f510 <b>{escape(title)}</b>\n{escape(body)}"
    buttons = tuple(RemoteButton(text=label, token=token) for token, label in actions)
    return text, buttons


def render_settings_card(
    *,
    connection_label: str,
    model: str,
    permission_mode: str,
    redaction_policy: str,
    notify_scope: str,
    redaction_tokens: Mapping[str, str],
    notify_scope_tokens: Mapping[str, str],
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = (
        "<b>⚙️ Settings</b>\n\n"
        f"<b>Connection</b>\n{escape(connection_label)}\n\n"
        f"<b>Model</b>\n<code>{escape(model)}</code> <i>(desktop only)</i>\n\n"
        f"<b>Permission mode</b>\n<code>{escape(permission_mode)}</code> <i>(desktop only)</i>\n\n"
        f"<b>Notifications</b>\n<code>{escape(notify_scope)}</code>\n\n"
        f"<b>Outbound redaction</b>\n<code>{escape(redaction_policy)}</code>"
    )
    buttons = [
        RemoteButton(text=f"Redaction: {name}", token=token)
        for name, token in redaction_tokens.items()
    ]
    buttons += [
        RemoteButton(text=f"Notify: {name}", token=token)
        for name, token in notify_scope_tokens.items()
    ]
    return text, tuple(buttons)


def render_project_picker(
    *, projects: Sequence[tuple[str, str]]
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = "Which project?"
    buttons = tuple(
        RemoteButton(text=f"\U0001f4c1 {escape(name)}", token=token)
        for token, name in projects
    )
    return text, buttons


def render_prompt_suggestions(
    *,
    project_name: str,
    context_line: str,
    suggestions: Sequence[tuple[str, str]],
    continue_token: str | None,
) -> tuple[str, tuple[RemoteButton, ...]]:
    text = (
        f"<b>\U0001f4c1 {escape(project_name)}</b>\n"
        f"<i>{escape(context_line)}</i>\n\n"
        "Try one, or just type your own:"
    )
    buttons: list[RemoteButton] = []
    if continue_token:
        buttons.append(RemoteButton(text="▶ Continue last session", token=continue_token))
    buttons += [RemoteButton(text=label, token=token) for token, label in suggestions]
    return text, tuple(buttons)
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py
```

Expected: PASS (7 tests).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/formatting.py tests/remote/test_formatting.py
uv run ty check app/remote/formatting.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/formatting.py tests/remote/test_formatting.py
git commit -m "feat(remote): add HTML rendering layer for Telegram cards"
```

---

### Task 2: HTML parse mode and native typing indicator

**ACs:** AC-24 (revised), AC-38 (transport half)

**Files:**

- Modify: `app/remote/contracts.py`
- Modify: `app/remote/telegram/client.py`
- Modify: `app/remote/telegram/adapter.py`
- Modify: `tests/remote/telegram/test_client.py`
- Modify: `tests/remote/telegram/test_adapter.py`

**Interfaces:**

- Produces `TelegramClient.send_chat_action(*, chat_id: str | int, action: str = "typing") -> None`.
- Produces `RemoteAdapter.indicate_typing(destination_id: str) -> None` (Protocol) and `TelegramAdapter.indicate_typing`.
- Changes `TelegramClient.send_text`/`edit_text` to always send `parse_mode="HTML"`.

- [ ] **Step 1: Write failing client tests**

```python
# tests/remote/telegram/test_client.py (add)
@pytest.mark.asyncio
async def test_send_text_sends_html_parse_mode(client, transport):
    await client.send_text(chat_id="1", text="<b>hi</b>")
    request = transport.requests[-1]
    assert request.json()["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_chat_action_calls_send_chat_action_endpoint(client, transport):
    await client.send_chat_action(chat_id="1")
    request = transport.requests[-1]
    assert request.url.path.endswith("/sendChatAction")
    assert request.json() == {"chat_id": "1", "action": "typing"}
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/telegram/test_client.py -k "parse_mode or chat_action"
```

- [ ] **Step 3: Implement in `TelegramClient`**

```python
# app/remote/telegram/client.py — inside send_text/edit_text payload construction,
# add "parse_mode": "HTML" to the request body dict alongside existing chat_id/text/
# reply_markup keys. Then add:

async def send_chat_action(
    self, *, chat_id: str | int, action: str = "typing"
) -> None:
    await self._post("sendChatAction", {"chat_id": chat_id, "action": action})
```

Use whichever existing private request helper `send_text` already calls (e.g. `self._post`/`self._request`) so error handling matches the rest of the class.

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/telegram/test_client.py
```

- [ ] **Step 5: Write failing adapter test for `indicate_typing`**

```python
# tests/remote/telegram/test_adapter.py (add)
@pytest.mark.asyncio
async def test_indicate_typing_calls_client(adapter, fake_client):
    await adapter.indicate_typing("chat-1")
    assert fake_client.chat_actions == [("chat-1", "typing")]
```

- [ ] **Step 6: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/telegram/test_adapter.py -k indicate_typing
```

- [ ] **Step 7: Add `indicate_typing` to the Protocol and implement it**

```python
# app/remote/contracts.py — inside class RemoteAdapter(Protocol):
    async def indicate_typing(self, destination_id: str) -> None: ...
```

```python
# app/remote/telegram/adapter.py — new method on TelegramAdapter
async def indicate_typing(self, destination_id: str) -> None:
    try:
        await self._client.send_chat_action(chat_id=destination_id)
    except TelegramApiError:
        # Best-effort liveliness signal; never fail the turn over it.
        pass
```

- [ ] **Step 8: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/telegram/test_client.py tests/remote/telegram/test_adapter.py
uv run ruff check app/remote/contracts.py app/remote/telegram/client.py app/remote/telegram/adapter.py
uv run ty check app/remote/
```

- [ ] **Step 9: Commit**

```bash
git add app/remote/contracts.py app/remote/telegram/client.py app/remote/telegram/adapter.py tests/remote/telegram/test_client.py tests/remote/telegram/test_adapter.py
git commit -m "feat(remote): send HTML parse mode and native typing indicator"
```

---

### Task 3: `notify_scope` schema and active-pairing cache

**ACs:** AC-42 (schema half)

**Files:**

- Create: `app/migrations/versions/00000065_add_remote_pairing_notify_scope.py`
- Modify: `app/models/remote.py`
- Modify: `app/remote/outbound.py`
- Modify: `app/remote/runtime.py`
- Test: `tests/models/test_remote_models.py` (create if absent)
- Modify: `tests/remote/test_outbound.py`
- Modify: `tests/remote/test_runtime.py`

**Interfaces:**

- Produces `RemotePairing.notify_scope: str` (default `"all"`).
- Produces `RemoteProjection.set_active_pairing(*, connection_id: str, destination_id: str, notify_scope: str, principal_id: str) -> None` and `RemoteProjection.clear_active_pairing() -> None`.
- Consumes `RemotePairing` via direct `select()`, matching the pattern already used in `app/remote/inbound.py`.

- [ ] **Step 1: Write the migration**

```python
# app/migrations/versions/00000065_add_remote_pairing_notify_scope.py
"""Add remote_pairings.notify_scope

Revision ID: 00000065
Revises: 00000064
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "00000065"
down_revision: str | Sequence[str] | None = "00000064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "remote_pairings",
        sa.Column(
            "notify_scope",
            sa.String(20),
            nullable=False,
            server_default="all",
        ),
    )


def downgrade() -> None:
    op.drop_column("remote_pairings", "notify_scope")
```

- [ ] **Step 2: Update the schema-head marker**

Open `app/core/schema_version.py` and update the expected head revision constant to `"00000065"`, matching how `00000064` was registered.

- [ ] **Step 3: Write a failing model/migration test**

```python
# tests/models/test_remote_models.py
import pytest
from sqlmodel import select

from app.models.remote import RemotePairing


@pytest.mark.asyncio
async def test_new_pairing_defaults_notify_scope_to_all(db_session, remote_connection):
    pairing = RemotePairing(
        connection_id=remote_connection.id,
        principal_id="user-1",
        destination_id="chat-1",
        label="My phone",
    )
    db_session.add(pairing)
    await db_session.commit()
    await db_session.refresh(pairing)
    assert pairing.notify_scope == "all"
```

- [ ] **Step 4: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/models/test_remote_models.py
```

Expected: FAIL — `notify_scope` is not a field on `RemotePairing`.

- [ ] **Step 5: Add the column to the model**

```python
# app/models/remote.py — inside class RemotePairing, after `display`:
notify_scope: str = Field(
    default="all",
    sa_column=Column(sa.String(20), nullable=False, server_default="all"),
)
```

- [ ] **Step 6: Run migration head and model test**

```powershell
uv run alembic upgrade head
uv run pytest --no-cov -q tests/models/test_remote_models.py
```

- [ ] **Step 7: Write failing active-pairing cache tests**

```python
# tests/remote/test_outbound.py (add)
def test_set_active_pairing_then_clear(projection):
    projection.set_active_pairing(
        connection_id="conn-1", destination_id="chat-1", notify_scope="all", principal_id="user-1",
    )
    assert projection.active_pairing() == ("conn-1", "chat-1", "all", "user-1")
    projection.clear_active_pairing()
    assert projection.active_pairing() is None
```

- [ ] **Step 8: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_outbound.py -k active_pairing
```

- [ ] **Step 9: Implement the cache on `RemoteProjection`**

```python
# app/remote/outbound.py — new fields on RemoteProjection and two methods.
# principal_id travels alongside connection/destination so completions and
# drill-down tokens for a session the projection never explicitly
# register_session-ed (Task 5) can still be minted with a real, non-empty
# owner instead of "" — v1 has exactly one pairing per connection, so the
# active pairing's principal is the only valid actor for the whole
# connection regardless of which surface (phone or desktop) started the work.
_active_pairing: tuple[str, str, str, str] | None = field(default=None, repr=False)

def set_active_pairing(
    self, *, connection_id: str, destination_id: str, notify_scope: str, principal_id: str,
) -> None:
    """Cache the single v1 pairing's routing info so ``observe`` can reach
    sessions it was never explicitly ``register_session``-ed for."""
    self._active_pairing = (connection_id, destination_id, notify_scope, principal_id)

def clear_active_pairing(self) -> None:
    self._active_pairing = None

def active_pairing(self) -> tuple[str, str, str, str] | None:
    return self._active_pairing
```

- [ ] **Step 10: Wire it from `runtime.py`**

```python
# app/remote/runtime.py — inside _start_locked, after `projection.set_adapter(adapter)`
from app.models.remote import RemotePairing
from sqlmodel import select

async with read_session_factory() as pairing_session:
    pairing = (
        await pairing_session.exec(
            select(RemotePairing).where(RemotePairing.connection_id == connection.id)
        )
    ).first()
if pairing is not None:
    projection.set_active_pairing(
        connection_id=str(pairing.connection_id),
        destination_id=pairing.destination_id,
        notify_scope=pairing.notify_scope,
        principal_id=pairing.principal_id,
    )
```

```python
# app/remote/runtime.py — inside _handle_pairing, in the `if result is not None:`
# branch that already sends "Connected to EvoFlux on {result.label}." —
# `result` is the persisted RemotePairing row itself (consume()'s return type)
if self._projection is not None:
    self._projection.set_active_pairing(
        connection_id=str(action.connection_id),
        destination_id=result.destination_id,
        notify_scope=result.notify_scope,
        principal_id=result.principal_id,
    )
```

```python
# app/remote/runtime.py — inside _stop_locked, before projection is discarded
if self._projection is not None:
    self._projection.clear_active_pairing()
```

- [ ] **Step 11: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_outbound.py tests/remote/test_runtime.py
uv run ruff check app/remote/outbound.py app/remote/runtime.py app/models/remote.py tests/models/test_remote_models.py tests/remote/test_outbound.py tests/remote/test_runtime.py
uv run ty check app/remote/ app/models/remote.py
```

- [ ] **Step 12: Commit**

```bash
git add app/migrations/versions/00000065_add_remote_pairing_notify_scope.py app/core/schema_version.py app/models/remote.py app/remote/outbound.py app/remote/runtime.py tests/models/test_remote_models.py tests/remote/test_outbound.py tests/remote/test_runtime.py
git commit -m "feat(remote): add notify_scope preference and active-pairing cache"
```

---

### Task 4: Turn-activity summary and phone-admitted status lifecycle

**ACs:** AC-38, AC-24 (application half)

**Files:**

- Create: `app/remote/turn_activity.py`
- Create: `tests/remote/test_turn_activity.py`
- Modify: `app/remote/outbound.py`
- Modify: `app/remote/runtime.py`
- Modify: `tests/remote/test_outbound.py`

**Interfaces:**

- Produces `app.remote.turn_activity.load_turn_activity(db: AsyncSession, session_id: str, *, since: datetime) -> TurnActivity` where `TurnActivity` has `tool_call_count: int`, `summary_lines: list[str]`, `tool_log_text: str`, `diff_text: str`.
- Produces `RemoteProjection.begin_phone_turn(session_id: str, *, connection_id: str, destination_id: str, principal_id: str, title: str, status: str) -> None`.
- Consumes `app.remote.formatting.render_status_card/render_done_card/render_error_card`, `app.models.chat.ChatMessage`.

- [ ] **Step 1: Write failing turn-activity tests**

```python
# tests/remote/test_turn_activity.py
import pytest
from datetime import UTC, datetime, timedelta

from app.models.chat import ChatMessage
from app.remote.turn_activity import load_turn_activity


@pytest.mark.asyncio
async def test_load_turn_activity_counts_tool_calls_and_builds_diff(db_session, chat_session):
    since = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add_all(
        [
            ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                tool_calls=[{"name": "write", "arguments": {"path": "a.py"}}],
                created_at=since + timedelta(milliseconds=10),
            ),
            ChatMessage(
                session_id=chat_session.id,
                role="tool",
                tool_call_id="1",
                content="wrote a.py (+5 -1)",
                created_at=since + timedelta(milliseconds=20),
            ),
            ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                tool_calls=[{"name": "read", "arguments": {"path": "b.py"}}],
                created_at=since + timedelta(milliseconds=30),
            ),
        ]
    )
    await db_session.commit()

    activity = await load_turn_activity(db_session, str(chat_session.id), since=since)

    assert activity.tool_call_count == 2
    assert "write" in activity.diff_text
    assert "read" not in activity.diff_text
    assert "read" in activity.tool_log_text
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_turn_activity.py
```

- [ ] **Step 3: Implement `turn_activity.py`**

```python
# app/remote/turn_activity.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatMessage

_DIFF_TOOLS = frozenset({"write", "edit", "patch"})

__all__ = ["TurnActivity", "load_turn_activity"]


@dataclass(frozen=True)
class TurnActivity:
    tool_call_count: int
    summary_lines: list[str] = field(default_factory=list)
    tool_log_text: str = ""
    diff_text: str = ""


async def load_turn_activity(
    db: AsyncSession, session_id: str, *, since: datetime
) -> TurnActivity:
    rows = (
        await db.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .where(ChatMessage.created_at >= since)
            .order_by(ChatMessage.created_at)
        )
    ).all()

    tool_calls: list[tuple[str, str]] = []
    for message in rows:
        for call in message.tool_calls or []:
            name = call.get("name", "unknown")
            args = call.get("arguments", {})
            tool_calls.append((name, str(args)))

    tool_log_lines = [f"{name}: {args}" for name, args in tool_calls]
    diff_lines = [f"{name}: {args}" for name, args in tool_calls if name in _DIFF_TOOLS]
    diff_paths = sorted({args for name, args in tool_calls if name in _DIFF_TOOLS})

    return TurnActivity(
        tool_call_count=len(tool_calls),
        summary_lines=diff_paths[:10],
        tool_log_text="\n".join(tool_log_lines) or "No tool calls.",
        diff_text="\n".join(diff_lines) or "No file changes.",
    )
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_turn_activity.py
```

- [ ] **Step 5: Write failing phone-admitted lifecycle tests**

```python
# tests/remote/test_outbound.py (add)
@pytest.mark.asyncio
async def test_begin_phone_turn_sends_status_card_then_done_edits_it(
    projection, adapter
):
    projection.register_session(
        "sess-1", connection_id="conn-1", destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1", connection_id="conn-1", destination_id="chat-1", principal_id="user-1",
        title="Fix tests", status="accepted",
    )
    await asyncio.sleep(0.05)
    assert adapter.calls[0] == "send"
    first_correlation = adapter.sent[0].correlation_id

    projection.observe("sess-1", _envelope("done", text="Done."))
    await projection.drain_pending()

    assert adapter.calls[1] == "edit"
    assert adapter.edited[0].correlation_id == first_correlation
    assert "Fix tests" in adapter.edited[0].text
    assert projection.typing_task_for("sess-1") is None
```

- [ ] **Step 6: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_outbound.py -k begin_phone_turn
```

- [ ] **Step 7: Implement the lifecycle on `RemoteProjection`**

```python
# app/remote/outbound.py — extend _TurnDeliveryState
@dataclass
class _TurnDeliveryState:
    session_id: str
    connection_id: str
    destination_id: str
    lifecycle_correlation_id: str | None = None
    completion_sent: bool = False
    phone_admitted: bool = False
    started_at: float = field(default_factory=time.monotonic)
    turn_started_wall_clock: datetime = field(default_factory=lambda: datetime.now(UTC))
    typing_task: "asyncio.Task[None] | None" = field(default=None, repr=False)
    title: str = ""
    principal_id: str = ""
```

```python
# app/remote/outbound.py — new public method
def begin_phone_turn(
    self,
    session_id: str,
    *,
    connection_id: str,
    destination_id: str,
    principal_id: str,
    title: str,
    status: str,
) -> None:
    """Create the one status message a phone-admitted turn owns, and start
    the native typing indicator alongside it. Called by runtime.py right
    after register_session for a text-triggered admission."""
    correlation_id = f"status:{session_id}:{uuid.uuid4().hex[:8]}"
    turn = _TurnDeliveryState(
        session_id=session_id,
        connection_id=connection_id,
        destination_id=destination_id,
        principal_id=principal_id,
        lifecycle_correlation_id=correlation_id,
        phone_admitted=True,
        title=title,
    )
    self._turns[session_id] = turn
    text, buttons = render_status_card(title=title, status=status)
    self._enqueue_send(
        destination_id=destination_id,
        text=text,
        buttons=buttons,
        priority=RemoteOutboundPriority.HIGH,
        correlation_id=correlation_id,
    )
    if self._adapter is not None:
        turn.typing_task = asyncio.create_task(self._run_typing_loop(turn))


async def _run_typing_loop(self, turn: _TurnDeliveryState) -> None:
    adapter = self._adapter
    if adapter is None:
        return
    try:
        while True:
            await adapter.indicate_typing(turn.destination_id)
            await asyncio.sleep(4.0)
    except asyncio.CancelledError:
        pass


def typing_task_for(self, session_id: str) -> "asyncio.Task[None] | None":
    turn = self._turns.get(session_id)
    return turn.typing_task if turn is not None else None


def _stop_typing(self, turn: _TurnDeliveryState) -> None:
    if turn.typing_task is not None and not turn.typing_task.done():
        turn.typing_task.cancel()
    turn.typing_task = None
```

Replace `_handle_done`/`_handle_error` to branch on `turn.phone_admitted`, using `formatting.py` builders and `turn_activity.load_turn_activity`:

```python
async def _finalize_turn(
    self, turn: _TurnDeliveryState, *, error_message: str | None
) -> None:
    from app.core.db import async_session_factory

    self._stop_typing(turn)
    elapsed = time.monotonic() - turn.started_at
    async with async_session_factory() as db:
        activity = await load_turn_activity(
            db, turn.session_id, since=turn.turn_started_wall_clock
        )
    diff_token = toollog_token = None
    if self._actions is not None:
        if activity.diff_text.strip() and activity.diff_text != "No file changes.":
            diff_token = self._actions.register_capability(
                connection_id=turn.connection_id,
                principal_id=turn.principal_id,
                destination_id=turn.destination_id,
                session_id=turn.session_id,
                action_kind="diff",
                action_target=activity.diff_text,
            )
        toollog_token = self._actions.register_capability(
            connection_id=turn.connection_id,
            principal_id=turn.principal_id,
            destination_id=turn.destination_id,
            session_id=turn.session_id,
            action_kind="toollog",
            action_target=activity.tool_log_text,
        )
    if error_message is not None:
        text, buttons = render_error_card(
            title=turn.title, message=_redact_text(error_message), toollog_token=toollog_token
        )
    else:
        text, buttons = render_done_card(
            title=turn.title,
            elapsed_seconds=elapsed,
            summary_lines=[_redact_text(line) for line in activity.summary_lines],
            tool_call_count=activity.tool_call_count,
            diff_token=diff_token,
            toollog_token=toollog_token,
        )
    if turn.phone_admitted and turn.lifecycle_correlation_id is not None:
        self._enqueue_edit(
            destination_id=turn.destination_id,
            text=text,
            buttons=buttons,
            correlation_id=turn.lifecycle_correlation_id,
        )
    else:
        self._enqueue_send(
            destination_id=turn.destination_id,
            text=text,
            buttons=buttons,
            priority=RemoteOutboundPriority.HIGH,
        )
```

`_handle_done`/`_handle_error` become thin wrappers: guard on `turn.completion_sent`, set it, then `await self._finalize_turn(turn, error_message=None)` / `await self._finalize_turn(turn, error_message=message)`.

The real current `_enqueue_send` (`app/remote/outbound.py`) already accepts `buttons` but not `correlation_id`, builds one `RemoteOutboundMessage` per chunk, appends each to `self._pending: list[RemoteOutboundMessage]`, and calls `self._schedule_drain()` — a fire-and-forget `asyncio.create_task(self.drain_pending())` when a loop is running, there is no persistent background worker. `drain_pending()` pops everything off `self._pending` and calls `await adapter.send(msg)` for each; there is currently no edit path at all. Extend it exactly like this:

```python
# app/remote/outbound.py — add a correlation_id parameter to the existing
# _enqueue_send, and a new _enqueue_edit + a second pending list
def _enqueue_send(
    self,
    *,
    destination_id: str,
    text: str,
    buttons: tuple[RemoteButton, ...] = (),
    priority: RemoteOutboundPriority = RemoteOutboundPriority.INFORMATIONAL,
    correlation_id: str | None = None,
) -> None:
    adapter = self._adapter
    if adapter is None:
        logger.debug("remote_outbound_no_adapter destination_id={}", destination_id)
        return
    connection_id = ""
    for cid in self._session_connection_ids.values():
        connection_id = cid
        break
    chunks = _split_text(text)
    for i, chunk in enumerate(chunks):
        msg = RemoteOutboundMessage(
            connection_id=UUID(connection_id) if connection_id else UUID(int=0),
            destination_id=destination_id,
            text=chunk,
            buttons=buttons if i == len(chunks) - 1 else (),
            priority=priority,
            correlation_id=correlation_id if i == len(chunks) - 1 else None,
        )
        self._pending.append(msg)
    self._schedule_drain()


def _enqueue_edit(
    self, *, destination_id: str, text: str, buttons: tuple[RemoteButton, ...], correlation_id: str,
) -> None:
    """Edit-flagged delivery — a status card's final transition. Unlike
    _enqueue_send, never splits (a status/done card is always short and
    already bounded by formatting.py's builders), so it is always exactly
    one queued item."""
    adapter = self._adapter
    if adapter is None:
        return
    connection_id = ""
    for cid in self._session_connection_ids.values():
        connection_id = cid
        break
    msg = RemoteOutboundMessage(
        connection_id=UUID(connection_id) if connection_id else UUID(int=0),
        destination_id=destination_id,
        text=text,
        buttons=buttons,
        correlation_id=correlation_id,
    )
    self._pending_edits.append(msg)
    self._schedule_drain()
```

```python
# app/remote/outbound.py — extend drain_pending to also drain edits, and
# add the new field next to the existing _pending: list[RemoteOutboundMessage]
_pending_edits: list[RemoteOutboundMessage] = field(default_factory=list, repr=False)

async def drain_pending(self) -> None:
    """Send/edit all pending messages through the adapter."""
    adapter = self._adapter
    if adapter is None:
        self._pending.clear()
        self._pending_edits.clear()
        self._unaddressed_pending.clear()
        return
    while self._pending:
        msg = self._pending.pop(0)
        try:
            await adapter.send(msg)
        except Exception as exc:
            logger.warning("remote_outbound_send_failed destination_id={} error={}", msg.destination_id, exc)
    while self._pending_edits:
        msg = self._pending_edits.pop(0)
        try:
            await adapter.edit(msg)
        except Exception as exc:
            logger.warning("remote_outbound_edit_failed destination_id={} error={}", msg.destination_id, exc)
    await self._drain_unaddressed()
```

`register_capability`'s real signature is defined in Task 6 — until that task lands, treat `self._actions` as an optional `"RemoteActionService | None" = None` attribute set by the `set_actions` setter Task 6 also adds, and treat a `None` diff/toollog token as "no button" (Task 1's builders already handle that). `_drain_unaddressed` (Task 5) is a no-op empty method until Task 5 implements it — add it as a stub (`async def _drain_unaddressed(self) -> None: return`) in this task so `drain_pending` has something to call, and Task 5 replaces the stub body.

- [ ] **Step 8: Wire `begin_phone_turn` from `runtime.py`**

```python
# app/remote/runtime.py — inside _handle_text, right after the existing
# register_session(...) call
if result.session_id is not None and self._projection is not None:
    from app.core.db import async_session_factory as _sf

    async with _sf() as title_session:
        session_row = await title_session.get(ChatSession, result.session_id)
    self._projection.begin_phone_turn(
        str(result.session_id),
        connection_id=str(action.connection_id),
        destination_id=action.principal.destination_id,
        principal_id=action.principal.principal_id,
        title=(session_row.title if session_row and session_row.title else "New task"),
        status=result.status,
    )
```

- [ ] **Step 9: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_outbound.py tests/remote/test_runtime.py tests/remote/test_turn_activity.py
uv run ruff check app/remote/outbound.py app/remote/runtime.py app/remote/turn_activity.py tests/remote/test_outbound.py tests/remote/test_turn_activity.py
uv run ty check app/remote/
```

- [ ] **Step 10: Commit**

```bash
git add app/remote/turn_activity.py app/remote/outbound.py app/remote/runtime.py tests/remote/test_turn_activity.py tests/remote/test_outbound.py
git commit -m "feat(remote): live status card, typing indicator, and done/error cards"
```

---

### Task 5: Cross-origin and workflow/scheduler completion delivery

**ACs:** AC-42, AC-43

**Files:**

- Modify: `app/remote/outbound.py`
- Modify: `tests/remote/test_outbound.py`

**Interfaces:**

- Changes `RemoteProjection.observe` session-resolution: falls back to `active_pairing()` when the session was never `register_session`-ed and the cached `notify_scope == "all"`, carrying the cached `principal_id` through so completion/drill-down capability tokens for these sessions are minted with a real owner instead of an empty string.
- Consumes `app.remote.inbound._is_addressable_session` (import it into `outbound.py` rather than duplicating the predicate) and `app.models.chat.ChatSession`.

- [ ] **Step 1: Write failing cross-origin tests**

```python
# tests/remote/test_outbound.py (add)
@pytest.mark.asyncio
async def test_unregistered_addressable_session_notifies_when_scope_is_all(
    projection, adapter, db_session_factory, addressable_session
):
    projection.set_active_pairing(
        connection_id="conn-1", destination_id="chat-1", notify_scope="all", principal_id="user-1",
    )
    projection.observe(str(addressable_session.id), _envelope("done", text="Done."))
    await projection.drain_pending()
    assert adapter.calls == ["send"]
    assert adapter.sent[0].destination_id == "chat-1"


@pytest.mark.asyncio
async def test_unregistered_session_silent_when_scope_is_remote_only(
    projection, adapter, addressable_session
):
    projection.set_active_pairing(
        connection_id="conn-1", destination_id="chat-1", notify_scope="remote_only", principal_id="user-1",
    )
    projection.observe(str(addressable_session.id), _envelope("done", text="Done."))
    await projection.drain_pending()
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_non_addressable_session_never_notifies_even_with_scope_all(
    projection, adapter, side_chat_session
):
    projection.set_active_pairing(
        connection_id="conn-1", destination_id="chat-1", notify_scope="all", principal_id="user-1",
    )
    projection.observe(str(side_chat_session.id), _envelope("done", text="Done."))
    await projection.drain_pending()
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_unregistered_session_gets_no_status_card_or_typing(
    projection, adapter, addressable_session
):
    projection.set_active_pairing(
        connection_id="conn-1", destination_id="chat-1", notify_scope="all", principal_id="user-1",
    )
    projection.observe(str(addressable_session.id), _envelope("done", text="Done."))
    await projection.drain_pending()
    assert projection.typing_task_for(str(addressable_session.id)) is None
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_outbound.py -k "cross_origin or unregistered or non_addressable"
```

- [ ] **Step 3: Implement the widened resolution in `observe`**

```python
# app/remote/outbound.py — replace the early-return session resolution at
# the top of observe() with:
def observe(self, session_id: str, envelope) -> None:
    event_type = envelope.event
    if event_type not in _OBSERVED_EVENT_TYPES:
        return

    tags = self._session_tags.get(session_id)
    if tags is not None:
        connection_id = self._session_connection_ids.get(session_id, "")
        destination_id = self._session_destination_ids.get(session_id, "")
        if not connection_id or not destination_id:
            return
    else:
        active = self._active_pairing
        if active is None or active[2] != "all":
            return
        # Addressability for a session we never registered can only be
        # confirmed with a database read, which observe() must never do
        # (AC-19). Defer that check to the async delivery path by enqueuing
        # a guarded lookup instead of calling send/edit directly.
        if event_type not in ("done", "error"):
            return
        connection_id, destination_id, _, principal_id = active
        self._enqueue_unregistered_completion(
            session_id=session_id,
            connection_id=connection_id,
            destination_id=destination_id,
            principal_id=principal_id,
            event_type=event_type,
            envelope_data=dict(envelope.data),
        )
        return

    turn = self._turns.get(session_id)
    if turn is None:
        turn = _TurnDeliveryState(
            session_id=session_id, connection_id=connection_id, destination_id=destination_id,
        )
        self._turns[session_id] = turn

    if event_type == "done":
        self._handle_done(turn, envelope)
    elif event_type == "error":
        self._handle_error(turn, envelope)
```

```python
# app/remote/outbound.py — new queue item; _schedule_drain is the existing
# fire-and-forget wake used by _enqueue_send (there is no persistent
# background worker task to notify)
def _enqueue_unregistered_completion(
    self, *, session_id: str, connection_id: str, destination_id: str,
    principal_id: str, event_type: str, envelope_data: dict,
) -> None:
    self._unaddressed_pending.append(
        (session_id, connection_id, destination_id, principal_id, event_type, envelope_data)
    )
    self._schedule_drain()
```

```python
# app/remote/outbound.py — inside the existing async delivery-worker loop,
# before/after the regular queue drain, drain _unaddressed_pending too:
async def _drain_unaddressed(self) -> None:
    from app.core.db import async_session_factory
    from app.models.chat import ChatSession
    from app.remote.inbound import _is_addressable_session

    pending, self._unaddressed_pending = self._unaddressed_pending, []
    for session_id, connection_id, destination_id, principal_id, event_type, data in pending:
        async with async_session_factory() as db:
            session_row = await db.get(ChatSession, session_id)
        if not _is_addressable_session(session_row):
            continue
        turn = self._turns.get(session_id)
        if turn is None:
            turn = _TurnDeliveryState(
                session_id=session_id, connection_id=connection_id,
                destination_id=destination_id, principal_id=principal_id,
                title=session_row.title or "Task",
            )
            self._turns[session_id] = turn
        if event_type == "done":
            if turn.completion_sent:
                continue
            turn.completion_sent = True
            await self._finalize_turn(turn, error_message=None)
        else:
            await self._finalize_turn(turn, error_message=data.get("message", "An error occurred."))
```

This replaces the empty `_drain_unaddressed` stub Task 4 added (that task's extended `drain_pending` already calls `await self._drain_unaddressed()` at the end, so existing tests that call `await projection.drain_pending()` exercise this path with no further wiring needed). Add `_unaddressed_pending: list[tuple] = field(default_factory=list, repr=False)` to `RemoteProjection`'s dataclass fields.

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_outbound.py
uv run ruff check app/remote/outbound.py tests/remote/test_outbound.py
uv run ty check app/remote/outbound.py
```

- [ ] **Step 5: Commit**

```bash
git add app/remote/outbound.py tests/remote/test_outbound.py
git commit -m "feat(remote): deliver completions for desktop-started and workflow sessions"
```

---

### Task 6: On-demand drill-down (Full diff, Tool log)

**ACs:** AC-39

**Files:**

- Modify: `app/remote/actions.py`
- Modify: `app/remote/outbound.py`
- Modify: `app/remote/runtime.py`
- Modify: `tests/remote/test_actions.py`
- Modify: `tests/remote/test_outbound.py`

**Interfaces:**

- Produces `RemoteActionService.register_capability(*, connection_id: UUID | str, principal_id: str, destination_id: str, session_id: str, action_kind: str, action_target: str) -> str`.
- Changes `RemoteActionService.handle_action_callback(self, action: RemoteInboundAction, db: AsyncSession) -> bool` — adds a required `db` parameter (needed by later tasks' branches, e.g. Task 7's settings writes and Task 8's session creation) and `"diff"`/`"toollog"` branches. Every existing caller and test call site for this method is updated in this task, not deferred.
- Produces `RemoteProjection.set_actions(actions: "RemoteActionService | None") -> None` and `RemoteActionService.set_projection(projection: "RemoteProjection | None") -> None` (the two services need each other: outbound needs actions to mint drill-down tokens; actions needs outbound to update the active-pairing cache and to give guided-flow-started tasks a live status card).

- [ ] **Step 1: Write failing capability-registration and dispatch tests**

```python
# tests/remote/test_actions.py (add)
def test_register_capability_returns_usable_token(service):
    token = service.register_capability(
        connection_id=uuid4(), principal_id="", destination_id="chat-1",
        session_id="sess-1", action_kind="toollog", action_target="log text",
    )
    assert isinstance(token, str) and len(token) > 0


@pytest.mark.asyncio
async def test_toollog_callback_sends_stored_content(service, adapter, db_session):
    token = service.register_capability(
        connection_id=uuid4(), principal_id="", destination_id="chat-1",
        session_id="sess-1", action_kind="toollog", action_target="write: {'path': 'a.py'}",
    )
    action = _make_action(callback_token=token)
    handled = await service.handle_action_callback(action, db_session)
    assert handled is True
    assert any("write" in msg.text for msg in adapter.sent)


@pytest.mark.asyncio
async def test_expired_capability_replies_friendly_message(service, adapter, db_session, monkeypatch):
    token = service.register_capability(
        connection_id=uuid4(), principal_id="", destination_id="chat-1",
        session_id="sess-1", action_kind="diff", action_target="diff text",
    )
    monkeypatch.setattr(time, "monotonic", lambda: time.monotonic() + 700)
    action = _make_action(callback_token=token)
    handled = await service.handle_action_callback(action, db_session)
    assert handled is True
    assert "expired" in adapter.sent[0].text.lower()
```

- [ ] **Step 1b: Update the method signature and every existing call site**

Add `db: AsyncSession` as `handle_action_callback`'s second positional parameter. Update its four existing internal branches (workflow/coding-project/EASD/schedule dispatch) — they currently open their own `async with async_session_factory() as session:` block per branch; replace each with the passed-in `db` so the whole method shares one session, matching how `dispatch_command` already receives `db` from its caller. Update every existing test in `tests/remote/test_actions.py` that calls `service.handle_action_callback(action)` to `service.handle_action_callback(action, db_session)`.

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k "capability or toollog or expired"
```

- [ ] **Step 3: Implement `register_capability` and dispatch branches**

```python
# app/remote/actions.py — new public method on RemoteActionService
def register_capability(
    self,
    *,
    connection_id: UUID | str,
    principal_id: str,
    destination_id: str,
    session_id: str,
    action_kind: str,
    action_target: str,
) -> str:
    token = secrets.token_urlsafe(16)[:_MAX_CALLBACK_TOKEN_BYTES]
    self._capabilities[token] = _ActionCapability(
        token=token,
        connection_id=UUID(str(connection_id)),
        principal_id=principal_id,
        destination_id=destination_id,
        session_id=session_id,
        action_kind=action_kind,
        action_target=action_target,
    )
    return token
```

```python
# app/remote/actions.py — inside handle_action_callback, add before the
# existing menu-token handling falls through:
capability = self._capabilities.get(action.callback_token)
if capability is not None and capability.action_kind in ("diff", "toollog"):
    del self._capabilities[action.callback_token]
    if time.monotonic() - capability.created_at > _CAPABILITY_TTL_SECONDS:
        text = "This expired. Ask me again and I'll fetch it fresh."
    else:
        label = "Full diff" if capability.action_kind == "diff" else "Tool log"
        redacted = _redact_text(capability.action_target)
        text = f"<b>{label}</b>\n\n<pre>{formatting.escape(redacted)}</pre>"
    for chunk in _split_text(text):
        if self._adapter is not None:
            await self._adapter.send(
                RemoteOutboundMessage(
                    connection_id=capability.connection_id,
                    destination_id=capability.destination_id,
                    text=chunk,
                    priority=RemoteOutboundPriority.HIGH,
                )
            )
    return True
```

Import `formatting` and the existing `_split_text` helper (move it to a small shared location if it is not already importable from `actions.py` — `outbound.py`'s `__all__` already exports it, so `from app.remote.outbound import _split_text` is sufficient).

- [ ] **Step 4: Wire `RemoteProjection.set_actions` and call it from `runtime.py`**

```python
# app/remote/outbound.py — mirrors set_adapter/set_bridge
def set_actions(self, actions: "RemoteActionService | None") -> None:
    self._actions = actions
```

```python
# app/remote/actions.py — new setter on RemoteActionService, mirroring the
# existing pattern; store as self._projection: "RemoteProjection | None" = None
def set_projection(self, projection: "RemoteProjection | None") -> None:
    self._projection = projection
```

```python
# app/remote/runtime.py — inside _start_locked, after self._actions is built
projection.set_actions(self._actions)
self._actions.set_projection(projection)
```

```python
# app/remote/runtime.py — inside _stop_locked, alongside the other projection resets
if self._projection is not None:
    self._projection.set_actions(None)
if self._actions is not None:
    self._actions.set_projection(None)
```

```python
# app/remote/runtime.py — inside _handle_action's CALLBACK branch, thread a
# session through to the now-required db parameter
if self._actions is not None and action.callback_token is not None:
    from app.core.db import async_session_factory

    async with async_session_factory() as callback_session:
        handled = await self._actions.handle_action_callback(action, callback_session)
```

- [ ] **Step 5: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py tests/remote/test_outbound.py tests/remote/test_runtime.py
uv run ruff check app/remote/actions.py app/remote/outbound.py app/remote/runtime.py tests/remote/test_actions.py
uv run ty check app/remote/
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/actions.py app/remote/outbound.py app/remote/runtime.py tests/remote/test_actions.py
git commit -m "feat(remote): on-demand Full diff / Tool log drill-down buttons"
```

---

### Task 7: `/settings` command

**ACs:** AC-41, AC-32 (revised), AC-44

**Files:**

- Modify: `app/remote/actions.py`
- Modify: `tests/remote/test_actions.py`

**Interfaces:**

- Adds `"settings"` to `_SLASH_COMMANDS`.
- Produces `RemoteActionService._cmd_settings(db, action) -> RemoteActionResult`.
- Adds `handle_action_callback` branches for `action_kind in ("redaction", "notify_scope")`.
- Consumes `app.core.runtime_settings.RemoteSettings/load_runtime_settings/save_runtime_settings` (the same file-backed config the `PUT /api/settings/remote` route already reads/writes — no database round trip) and `RemotePairing.notify_scope`.

- [ ] **Step 1: Write failing command and toggle tests**

```python
# tests/remote/test_actions.py (add)
def test_settings_is_a_known_slash_command():
    assert "settings" in _SLASH_COMMANDS


@pytest.mark.asyncio
async def test_cmd_settings_shows_model_and_permission_as_text_only(
    service, db_session, paired_session_with_model
):
    action = _make_action(text="/settings")
    result = await service.dispatch_command(db_session, action)
    assert "claude-sonnet-5" in result.text
    assert "ask each time" in result.text.lower() or "auto" in result.text.lower()


@pytest.mark.asyncio
async def test_settings_redaction_callback_updates_policy(
    service, db_session, adapter, monkeypatch
):
    saved = {}

    def fake_save(cfg):
        saved["policy"] = cfg.remote.outbound_data_policy

    monkeypatch.setattr("app.remote.actions.save_runtime_settings", fake_save)
    token = service.register_capability(
        connection_id=uuid4(), principal_id="", destination_id="chat-1",
        session_id="sess-1", action_kind="redaction", action_target="strict",
    )
    action = _make_action(callback_token=token)
    handled = await service.handle_action_callback(action, db_session)
    assert handled is True
    assert saved["policy"] == "strict"


@pytest.mark.asyncio
async def test_settings_never_offers_a_model_or_permission_button(
    service, db_session, paired_session_with_model
):
    action = _make_action(text="/settings")
    result = await service.dispatch_command(db_session, action)
    # dispatch_command sends via the adapter for settings (card + buttons),
    # not just plain text, so assert on what was actually sent.
    sent_buttons = [b.text.lower() for msg in adapter.sent for b in msg.buttons]
    assert not any("model" in t or "permission" in t for t in sent_buttons)
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k settings
```

- [ ] **Step 3: Add the command and its dispatch**

```python
# app/remote/actions.py
_SLASH_COMMANDS: frozenset[str] = frozenset(
    {"start", "help", "status", "new", "stop", "unpair", "actions", "settings"}
)
```

```python
async def _cmd_settings(
    self, db: AsyncSession, action: RemoteInboundAction
) -> RemoteActionResult:
    pairing = await self._pairing_service.get_pairing(db, action.connection_id)
    if pairing is None:
        return RemoteActionResult(status="refused", text="")
    session_row = None
    if pairing.active_session_id is not None:
        session_row = await db.get(ChatSession, pairing.active_session_id)
    model = (session_row.model if session_row and session_row.model else "default")
    permission_mode = session_row.permission_mode if session_row else "auto"
    cfg = load_runtime_settings()

    redaction_targets = [n for n in ("strict", "standard", "off") if n != cfg.remote.outbound_data_policy]
    redaction_tokens = {
        name: self.register_capability(
            connection_id=action.connection_id, principal_id=action.principal.principal_id,
            destination_id=action.principal.destination_id, session_id=str(pairing.active_session_id or ""),
            action_kind="redaction", action_target=name,
        )
        for name in redaction_targets
    }
    scope_targets = [s for s in ("all", "remote_only") if s != pairing.notify_scope]
    notify_scope_tokens = {
        name: self.register_capability(
            connection_id=action.connection_id, principal_id=action.principal.principal_id,
            destination_id=action.principal.destination_id, session_id=str(pairing.active_session_id or ""),
            action_kind="notify_scope", action_target=name,
        )
        for name in scope_targets
    }

    text, buttons = render_settings_card(
        connection_label=pairing.label,
        model=model,
        permission_mode=permission_mode,
        redaction_policy=cfg.remote.outbound_data_policy,
        notify_scope=pairing.notify_scope,
        redaction_tokens=redaction_tokens,
        notify_scope_tokens=notify_scope_tokens,
    )
    if self._adapter is not None:
        await self._adapter.send(
            RemoteOutboundMessage(
                connection_id=action.connection_id,
                destination_id=action.principal.destination_id,
                text=text,
                buttons=buttons,
                priority=RemoteOutboundPriority.INFORMATIONAL,
            )
        )
    return RemoteActionResult(status="sent", text=text)
```

Settings are file-backed config, not database rows: `app/api/routes/settings.py`'s own `/remote` route handlers read/write them via `cfg = load_runtime_settings(); cfg.remote.outbound_data_policy` / `cfg.remote = RemoteSettings(outbound_data_policy=..., outbound_pii_policy=cfg.remote.outbound_pii_policy); save_runtime_settings(cfg)` — both synchronous, both imported `from app.core.runtime_settings import RemoteSettings, load_runtime_settings, save_runtime_settings`. `_cmd_settings` above must use `load_runtime_settings()` exactly this way (already reflected in the code block). `PairingService` has no existing "fetch this connection's single pairing" accessor — add one:

```python
# app/remote/pairing.py — new method on PairingService
async def get_pairing(
    self, db: AsyncSession, connection_id: UUID
) -> RemotePairing | None:
    return (
        await db.exec(
            select(RemotePairing).where(RemotePairing.connection_id == connection_id)
        )
    ).first()
```

Add a matching unit test in `tests/remote/test_pairing.py` (create-then-fetch, and `None` for an unpaired connection) as part of this task's Step 3, following the existing test file's fixture conventions.

- [ ] **Step 4: Add `redaction`/`notify_scope` callback branches**

```python
# app/remote/actions.py — inside handle_action_callback, alongside the
# diff/toollog branch added in Task 6
if capability is not None and capability.action_kind == "redaction":
    del self._capabilities[action.callback_token]
    cfg = load_runtime_settings()
    cfg.remote = RemoteSettings(
        outbound_data_policy=capability.action_target,
        outbound_pii_policy=cfg.remote.outbound_pii_policy,
    )
    save_runtime_settings(cfg)
    return True
if capability is not None and capability.action_kind == "notify_scope":
    del self._capabilities[action.callback_token]
    pairing = await self._pairing_service.get_pairing(db, capability.connection_id)
    if pairing is not None:
        pairing.notify_scope = capability.action_target
        db.add(pairing)
        await db.commit()
        if self._projection is not None:
            self._projection.set_active_pairing(
                connection_id=str(capability.connection_id),
                destination_id=pairing.destination_id,
                notify_scope=pairing.notify_scope,
                principal_id=pairing.principal_id,
            )
    return True
```

`db` is already available here as the parameter Task 6 added to `handle_action_callback`. `self._projection` is already available as the attribute Task 6's `set_projection` step added.

- [ ] **Step 5: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py tests/remote/test_runtime.py
uv run ruff check app/remote/actions.py tests/remote/test_actions.py
uv run ty check app/remote/actions.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/actions.py tests/remote/test_actions.py
git commit -m "feat(remote): add /settings with redaction and notify-scope toggles"
```

---

### Task 8: Guided project picker and prompt suggestions

**ACs:** AC-40

**Files:**

- Modify: `app/remote/actions.py`
- Modify: `tests/remote/test_actions.py`

**Interfaces:**

- Changes `_cmd_new` to send a project picker instead of clearing the pointer silently, when more than zero authorized Coding projects exist.
- Adds `handle_action_callback` branches for `action_kind in ("project_pick", "prompt_pick")`.
- Consumes `app.services.coding_project_service.list_visible_projects(db, *, kind="coding")` and `app.remote.inbound.RemoteInboundService.new_task`.

- [ ] **Step 1: Write failing picker-flow tests**

```python
# tests/remote/test_actions.py (add)
@pytest.mark.asyncio
async def test_cmd_new_with_projects_shows_picker_not_bare_ack(
    service, db_session, adapter, one_coding_project
):
    action = _make_action(text="/new")
    await service.dispatch_command(db_session, action)
    assert any("Which project" in m.text for m in adapter.sent)


@pytest.mark.asyncio
async def test_project_pick_then_shows_prompt_suggestions(
    service, db_session, adapter, one_coding_project
):
    token = service.register_capability(
        connection_id=uuid4(), principal_id="p", destination_id="chat-1",
        session_id="", action_kind="project_pick", action_target=str(one_coding_project.id),
    )
    action = _make_action(callback_token=token)
    handled = await service.handle_action_callback(action, db_session)
    assert handled is True
    assert any("Fix failing tests" in m.text or "Review my changes" in m.text for m in adapter.sent)


@pytest.mark.asyncio
async def test_free_form_text_still_works_after_picker_shown(
    service, db_session, inbound_service, one_coding_project
):
    action = _make_action(text="Refactor the login flow")
    result = await inbound_service.handle_text(db_session, action)
    assert result.status in ("accepted", "queued", "pending")
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k "picker or project_pick"
```

- [ ] **Step 3: Extend `_cmd_new` and add the picker/suggestion callbacks**

```python
# app/remote/actions.py — replace the body of _cmd_new with:
async def _cmd_new(
    self, db: AsyncSession, action: RemoteInboundAction
) -> RemoteActionResult:
    from app.remote.inbound import RemoteInboundService

    inbound_service = RemoteInboundService(pairing_service=self._pairing_service)
    await inbound_service.new_task(db, action)

    projects = await list_visible_projects(db, kind="coding")
    if not projects:
        return RemoteActionResult(status="cleared", text="Started a new task. What would you like to work on?")

    tokens = [
        (
            self.register_capability(
                connection_id=action.connection_id, principal_id=action.principal.principal_id,
                destination_id=action.principal.destination_id, session_id="",
                action_kind="project_pick", action_target=str(project.id),
            ),
            project.name,
        )
        for project in projects[:5]
    ]
    text, buttons = render_project_picker(projects=tokens)
    if self._adapter is not None:
        await self._adapter.send(
            RemoteOutboundMessage(
                connection_id=action.connection_id, destination_id=action.principal.destination_id,
                text=text, buttons=buttons, priority=RemoteOutboundPriority.INFORMATIONAL,
            )
        )
    return RemoteActionResult(status="cleared", text=text)
```

```python
# app/remote/actions.py — new callback branches inside handle_action_callback
_CURATED_PROMPTS = (
    ("Fix failing tests", "Fix failing tests"),
    ("Review my changes", "Review my changes"),
    ("Add a feature…", "I'd like to add a feature. Ask me what before starting."),
)

if capability is not None and capability.action_kind == "project_pick":
    del self._capabilities[action.callback_token]
    project = await get_project(db, UUID(capability.action_target))
    if project is None:
        return True
    last_session = await self._find_last_session_for_project(db, project.id)
    suggestion_tokens = [
        (
            self.register_capability(
                connection_id=capability.connection_id, principal_id=capability.principal_id,
                destination_id=capability.destination_id, session_id="",
                action_kind="prompt_pick", action_target=f"{project.id}:{prompt_text}",
            ),
            label,
        )
        for label, prompt_text in _CURATED_PROMPTS
    ]
    continue_token = None
    if last_session is not None:
        continue_token = self.register_capability(
            connection_id=capability.connection_id, principal_id=capability.principal_id,
            destination_id=capability.destination_id, session_id="",
            action_kind="prompt_pick", action_target=f"{project.id}:__continue__:{last_session.id}",
        )
    text, buttons = render_prompt_suggestions(
        project_name=project.name,
        context_line=f"Last session {self._relative_time(last_session)}" if last_session else "No prior sessions",
        suggestions=suggestion_tokens,
        continue_token=continue_token,
    )
    if self._adapter is not None:
        await self._adapter.send(
            RemoteOutboundMessage(
                connection_id=capability.connection_id, destination_id=capability.destination_id,
                text=text, buttons=buttons, priority=RemoteOutboundPriority.INFORMATIONAL,
            )
        )
    return True

if capability is not None and capability.action_kind == "prompt_pick":
    del self._capabilities[action.callback_token]
    from app.remote.inbound import RemoteInboundService

    project_id_str, _, remainder = capability.action_target.partition(":")
    inbound_service = RemoteInboundService(pairing_service=self._pairing_service)
    if remainder.startswith("__continue__:"):
        session_id = UUID(remainder.removeprefix("__continue__:"))
        await inbound_service.continue_task(db, action, session_id)
    else:
        await self._start_coding_task(db, action, UUID(project_id_str), remainder)
    return True
```

`_find_last_session_for_project` and `_relative_time` are small private helpers: the first queries the most recent top-level `ChatSession` with `project_id == project.id`, ordered by `created_at` descending; the second formats a `datetime` as `"2h ago"`. The existing `_exec_coding_task` (used by the `/actions` menu's "Coding projects" entry) only creates an empty session and tells the user to "Send your first message" — it does not accept or submit a prompt, so it cannot be reused as-is here. `_start_coding_task` is new, and unlike `_exec_coding_task` it also registers the session with the projection so the resulting turn gets the same live status card and typing indicator a free-typed message would:

```python
# app/remote/actions.py — new private helper on RemoteActionService
async def _start_coding_task(
    self,
    db: AsyncSession,
    action: RemoteInboundAction,
    project_id: UUID,
    prompt_text: str,
) -> None:
    from app.services.chat_service import create_chat_session
    from app.services.coding_project_service import get_project
    from app.remote.inbound import RemoteInboundService

    project = await get_project(db, project_id)
    if project is None:
        await self._reply_text(action.principal.destination_id, "Project not found.")
        return

    chat = await create_chat_session(db)
    chat.mode = "coding"
    chat.project_id = project.id
    chat.tags = ["remote_origin", f"remote_connection:{action.connection_id}"]
    db.add(chat)
    await db.commit()

    pairing = await self._pairing_service.authorize(
        db, connection_id=action.connection_id, principal_id=action.principal.principal_id,
    )
    if pairing is not None:
        pairing.active_session_id = chat.id
        db.add(pairing)
        await db.commit()

    if self._projection is not None:
        self._projection.register_session(
            str(chat.id),
            connection_id=str(action.connection_id),
            destination_id=action.principal.destination_id,
            tags=frozenset({"remote_origin", f"remote_connection:{action.connection_id}"}),
        )

    prompt_action = replace(action, text=prompt_text)
    inbound_service = RemoteInboundService(pairing_service=self._pairing_service)
    result = await inbound_service.handle_text(db, prompt_action)

    if self._projection is not None:
        self._projection.begin_phone_turn(
            str(chat.id),
            connection_id=str(action.connection_id),
            destination_id=action.principal.destination_id,
            principal_id=action.principal.principal_id,
            title=project.name,
            status=result.status,
        )
```

`replace` is `dataclasses.replace` — `RemoteInboundAction` is frozen, so build a copy with `text` overridden rather than mutating it. Import it at the top of `actions.py` alongside the module's other `dataclasses` imports.

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py
uv run ruff check app/remote/actions.py tests/remote/test_actions.py
uv run ty check app/remote/actions.py
```

- [ ] **Step 5: Commit**

```bash
git add app/remote/actions.py tests/remote/test_actions.py
git commit -m "feat(remote): guided project picker and prompt suggestions for /new"
```

---

### Task 9: Gate cards adopt the shared renderer

**ACs:** AC-24 (revised, applied to gates)

**Files:**

- Modify: `app/remote/gates.py`
- Modify: `tests/remote/test_gates.py`

**Interfaces:**

- `RemoteGateBridge.on_gate` builds its text/buttons via `formatting.render_gate_card` instead of inline f-strings.

- [ ] **Step 1: Write a failing escaping test for gate cards**

```python
# tests/remote/test_gates.py (add)
def test_permission_card_escapes_tool_name(bridge):
    bridge.on_gate(
        "sess-1", "permission_asked", {"tool": "<script>rm -rf /</script>"},
        connection_id=uuid4(), destination_id="chat-1",
    )
    sent_text = bridge._adapter.sent[0].text  # type: ignore[attr-defined]
    assert "<script>" not in sent_text
    assert "&lt;script&gt;" in sent_text
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py -k escapes_tool_name
```

- [ ] **Step 3: Replace inline card text with `formatting.render_gate_card`**

```python
# app/remote/gates.py — inside on_gate, replace each `text = f"..."` /
# `actions = [...]` block with a call into the shared renderer, e.g. for
# the permission branch:
if event_type == "permission_asked":
    gate_kind = "permission"
    tool = data.get("tool", "unknown")
    text, buttons_unused = render_gate_card(
        title="Permission needed", body=f"Run: {tool}",
        actions=[("once", "Allow once"), ("reject", "Reject")],
    )
```

Apply the same substitution to the `question_asked` and `plan_approval_requested` branches, keeping each branch's existing `gate_kind`/`actions`-derived token-minting logic unchanged — only the text/button *construction* moves into `formatting.py`; token minting, storage, and the `_redact_text` call around any interpolated content stay exactly where they are today (redact, then hand the already-redacted string to the renderer, matching the redact-then-escape order established in Task 1).

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py
uv run ruff check app/remote/gates.py tests/remote/test_gates.py
uv run ty check app/remote/gates.py
```

- [ ] **Step 5: Commit**

```bash
git add app/remote/gates.py tests/remote/test_gates.py
git commit -m "refactor(remote): gate cards use the shared HTML rendering layer"
```

---

## Full-suite regression

After Task 9, run the complete focused suite once before considering the plan done:

```powershell
uv run pytest --no-cov -q tests/remote tests/models/test_remote_models.py tests/services/test_memory_stream_observers.py
uv run ruff check app/remote app/models/remote.py tests/remote tests/models/test_remote_models.py
uv run ruff format --check app/remote app/models/remote.py tests/remote
uv run ty check app/
uv run alembic upgrade head
```

## Rollback

Each task is independently revertible by reverting its commit; there is no
cross-task migration dependency beyond `00000065`, which downgrades cleanly
(drops only the `notify_scope` column, per its `downgrade()`). Disabling the
remote connection from Settings stops all delivery immediately regardless of
which tasks have landed — none of this plan changes that kill switch.
