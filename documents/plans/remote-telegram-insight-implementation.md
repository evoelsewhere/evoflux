# Remote Telegram: Health and Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two read-only commands — `/health` (system diagnostics) and
`/changes` (the active session's changed files, with per-file diff
drill-down) — Phase 3 of the control-surface spec, covering AC-51 and
AC-52.

**Architecture:** `app/remote/control.py` gains two read functions.
`get_health_diagnostics` calls `app.api.routes.health.health_diagnostics`
directly — a second, documented exception to the "service layer only"
rule (like `get_registry` before it): all check logic lives inline in
that route with no service-layer equivalent, and duplicating ~250 lines
of db/provider/team/MCP/disk checks would be far worse than calling the
one already-correct function with an explicit session. `get_file_diff`
calls `app.api.routes.team.git.get_diff_view` directly for the same
reason — it already carries the security-sensitive path-traversal and
staged/unstaged/untracked detection logic; reimplementing that in
`app/remote/` risks subtly reintroducing a path-traversal bug. The
file-list side of `/changes` needs no such exception:
`app.services.turn_changes.get_latest` is a genuine, already-correct
service-layer function. `formatting.py` gains two card builders.
`actions.py` gains `/health` and `/changes`, plus a new `changes_diff`
capability action kind — the *first* drill-down capability in this
codebase that fetches its content fresh at tap time rather than reading
a pre-stored string, since a git diff must reflect the file's state now,
not its state when the turn finished.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, asyncio, pytest, pytest-asyncio.

**Spec:** [`remote-telegram-control-surface.md`](remote-telegram-control-surface.md) — this plan implements exactly AC-51 and AC-52. AC-53 (providers read-only), AC-54 (onboarding), AC-55–57 (live activity mode), and AC-58 (final command-set) are later phases.

## Global Constraints

- Every check/diff value rendered passes through the same redact-then-escape
  pipeline as every other outbound card (`_redact_text` then HTML escaping)
  — a diff can contain arbitrary file content, the least bounded text this
  feature has rendered yet.
- The two route-module imports (`health_diagnostics`, `get_diff_view`) are
  called with explicit arguments, never relying on their `Depends(...)`
  defaults — those defaults are FastAPI dependency-injection sentinels,
  not usable values, when called outside a request.
- `/changes`'s file-list button cap and drill-down TTL match existing
  precedent elsewhere in this module (5-8 item menu caps,
  `_CAPABILITY_TTL_SECONDS` for token expiry) — no new constants invented
  where an existing one already fits.
- Every task cites its spec ACs, writes a failing test before implementation,
  and leaves the test suite green at its checkpoint.
- Commit at the end of each task.

---

## File and interface map

Changed units:

- `app/remote/control.py` — adds `get_health_diagnostics`, `get_file_diff`.
- `app/remote/formatting.py` — adds `render_health_card`, `render_changes_card`.
- `app/remote/actions.py` — `_SLASH_COMMANDS` gains `"health"`, `"changes"`;
  new `_cmd_health`, `_cmd_changes`, `_exec_changes_diff`; `_execute_action`
  gains a `changes_diff` branch.
- `tests/remote/test_control.py`, `tests/remote/test_formatting.py`,
  `tests/remote/test_actions.py` — new focused evidence.

---

### Task 1: `get_health_diagnostics` and `get_file_diff`

**ACs:** AC-51, AC-52 (data half)

**Files:**

- Modify: `app/remote/control.py`
- Modify: `tests/remote/test_control.py`

**Interfaces:**

- Produces: `async def get_health_diagnostics() -> dict`,
  `async def get_file_diff(workspace: str, path: str) -> str`.
- Consumes: `app.api.routes.health.health_diagnostics`,
  `app.api.routes.team.git.get_diff_view`, `app.core.db.async_session_factory`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_control.py (add)
@pytest.mark.asyncio
async def test_get_health_diagnostics_returns_checks_and_summary() -> None:
    result = await control.get_health_diagnostics()

    assert "checks" in result
    assert "summary" in result
    assert result["summary"] in ("ok", "warn", "fail")
    assert isinstance(result["checks"], list)
    if result["checks"]:
        first = result["checks"][0]
        assert set(first.keys()) >= {"id", "label", "status", "detail"}


@pytest.mark.asyncio
async def test_get_file_diff_returns_empty_for_a_non_git_workspace(
    tmp_path: "Path",
) -> None:
    diff = await control.get_file_diff(str(tmp_path), "nonexistent.py")

    assert diff == ""
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py -k "health_diagnostics or file_diff"
```

Expected: FAIL with `AttributeError: module 'app.remote.control' has no attribute 'get_health_diagnostics'`.

- [ ] **Step 3: Implement both functions**

```python
# app/remote/control.py — add to __all__: "get_health_diagnostics", "get_file_diff"
```

```python
# app/remote/control.py — new functions
async def get_health_diagnostics() -> dict:
    """The same active health check the desktop UI's Diagnostics screen
    uses, called directly rather than duplicated — see this module's
    docstring for why app/remote/ makes an exception to "service layer
    only" for this one function. Uses read_session_factory (not
    async_session_factory) since this mirrors a GET route — app.core.db's
    own get_session dependency picks the same read lane for GET requests."""
    from app.api.routes.health import health_diagnostics
    from app.core.db import read_session_factory

    async with read_session_factory() as db:
        return await health_diagnostics(session=db)


async def get_file_diff(workspace: str, path: str) -> str:
    """One file's unified diff (staged, unstaged, or untracked-as-additions)
    — delegates to the same route function the desktop UI's diff viewer
    uses, which already carries the path-traversal and staged/unstaged/
    untracked detection logic; reimplementing that here would risk
    subtly reintroducing a path-traversal bug."""
    from app.api.routes.team.git import get_diff_view

    result = await get_diff_view(workspace=workspace, path=path)
    return result.get("diff", "")
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_control.py
```

Expected: PASS (14 tests).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/control.py tests/remote/test_control.py
uv run ty check app/remote/control.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/control.py tests/remote/test_control.py
git commit -m "feat(remote): add health diagnostics and file-diff reads"
```

---

### Task 2: Health and changes card rendering

**ACs:** AC-51, AC-52 (display half)

**Files:**

- Modify: `app/remote/formatting.py`
- Modify: `tests/remote/test_formatting.py`

**Interfaces:**

- Produces: `render_health_card(checks: Sequence[Mapping[str, object]]) -> str`,
  `render_changes_card(*, title: str, files: Sequence[tuple[str, str, int | None, int | None]], additions: int, deletions: int, file_tokens: Mapping[str, str]) -> tuple[str, tuple[RemoteButton, ...]]`.

`render_health_card` returns a bare `str` (no buttons — health is purely
informational, nothing on it is tappable). `files` entries are
`(path, status, additions, deletions)` tuples, matching
`turn_changes.ChangedFile`'s fields in call order without importing that
dataclass into `formatting.py` (this module renders plain values, never
domain objects, matching every other builder here).

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_formatting.py (add)
_HEALTH_ICON = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


def test_render_health_card_shows_each_check_with_its_status_icon():
    text = formatting.render_health_card(
        [
            {"id": "db", "label": "Database", "status": "ok", "detail": "connected"},
            {
                "id": "disk",
                "label": "Disk space",
                "status": "fail",
                "detail": "2.1 GB free",
            },
        ]
    )
    assert "Database" in text
    assert "Disk space" in text
    assert "✅" in text  # ok icon
    assert "❌" in text  # fail icon


def test_render_health_card_escapes_detail_text():
    text = formatting.render_health_card(
        [
            {
                "id": "x",
                "label": "X",
                "status": "warn",
                "detail": "<script>alert(1)</script>",
            }
        ]
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_changes_card_lists_files_with_line_counts_and_buttons():
    text, buttons = formatting.render_changes_card(
        title="Fix auth tests",
        files=[
            ("app/auth.py", "modified", 10, 2),
            ("tests/test_auth.py", "added", 5, 0),
        ],
        additions=15,
        deletions=2,
        file_tokens={"app/auth.py": "tok-1", "tests/test_auth.py": "tok-2"},
    )
    assert "app/auth.py" in text
    assert "+15" in text
    assert "-2" in text
    assert {b.token for b in buttons} == {"tok-1", "tok-2"}


def test_render_changes_card_escapes_file_paths():
    text, _ = formatting.render_changes_card(
        title="Task",
        files=[("<script>.py", "modified", 1, 0)],
        additions=1,
        deletions=0,
        file_tokens={},
    )
    assert "<script>.py" not in text
    assert "&lt;script&gt;.py" in text
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py -k "health_card or changes_card"
```

Expected: FAIL with `AttributeError: module 'app.remote.formatting' has no attribute 'render_health_card'`.

- [ ] **Step 3: Implement both builders**

```python
# app/remote/formatting.py — add to __all__: "render_health_card", "render_changes_card"
```

```python
# app/remote/formatting.py — new module-level constant, near _SEVERITY_ICON
_HEALTH_ICON = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
```

```python
# app/remote/formatting.py — new functions
def render_health_card(checks: Sequence[Mapping[str, object]]) -> str:
    lines = ["<b>\U0001fa7a Health</b>", ""]
    for check in checks:
        icon = _HEALTH_ICON.get(str(check.get("status", "")), "❓")
        label = escape(str(check.get("label", "")))
        detail = escape(str(check.get("detail", "")))
        lines.append(f"{icon} <b>{label}</b>\n{detail}")
    return "\n\n".join(lines)


def render_changes_card(
    *,
    title: str,
    files: Sequence[tuple[str, str, int | None, int | None]],
    additions: int,
    deletions: int,
    file_tokens: Mapping[str, str],
) -> tuple[str, tuple[RemoteButton, ...]]:
    lines = [
        f"<b>\U0001f4dd Changes</b> — {escape(title)}",
        "",
        f"+{additions} -{deletions} across {len(files)} file(s)",
        "",
    ]
    for path, status, file_additions, file_deletions in files:
        counts = ""
        if file_additions is not None or file_deletions is not None:
            counts = f" (+{file_additions or 0} -{file_deletions or 0})"
        lines.append(f"\U0001f4c4 {escape(path)}{counts} — {escape(status)}")
    text = "\n".join(lines)

    buttons = tuple(
        RemoteButton(text=f"View: {escape(path)}", token=token)
        for path, token in file_tokens.items()
    )
    return text, buttons
```

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
git commit -m "feat(remote): render health and changes cards"
```

---

### Task 3: Wire `/health`

**ACs:** AC-51, AC-58 (partial — adds `health` to the command set)

**Files:**

- Modify: `app/remote/actions.py`
- Modify: `tests/remote/test_actions.py`

**Interfaces:**

- Changes `_SLASH_COMMANDS`: adds `"health"`.
- Produces (private): `_cmd_health`.

- [ ] **Step 1: Write the failing test**

```python
# tests/remote/test_actions.py (add to class TestSlashCommands, or a new
# class TestHealthAndChanges alongside TestSettings)
@pytest.mark.asyncio
async def test_health_command_shows_checks(service: RemoteActionService) -> None:
    mock_db = MagicMock()
    action = _make_action(text="/health")

    fake_diagnostics = {
        "checks": [
            {"id": "db", "label": "Database", "status": "ok", "detail": "connected"},
        ],
        "summary": "ok",
    }

    async def _fake_get_health_diagnostics():
        return fake_diagnostics

    with patch(
        "app.remote.control.get_health_diagnostics",
        _fake_get_health_diagnostics,
    ):
        result = await service.dispatch_command(mock_db, action)

    assert result.status == "ok"
    assert "Database" in result.text
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k health_command
```

Expected: FAIL — `/health` falls through to `_cmd_help` (unknown command).

- [ ] **Step 3: Add `/health` to the known commands and dispatch**

```python
# app/remote/actions.py — _SLASH_COMMANDS
_SLASH_COMMANDS: frozenset[str] = frozenset(
    {"start", "help", "status", "new", "stop", "unpair", "actions", "settings", "health"}
)
```

```python
# app/remote/actions.py — inside dispatch_command, alongside the other elif branches
        elif command == "health":
            return await self._cmd_health(db, action)
```

- [ ] **Step 4: Implement `_cmd_health`**

`/health` needs no pairing/session lookup beyond authorization — it is
system-wide, not per-session, unlike `/settings`/`/changes`.

```python
# app/remote/actions.py — new method, near _cmd_settings
    async def _cmd_health(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        from app.remote import control
        from app.remote.formatting import render_health_card

        pairing = await self._pairing_service.authorize(
            db,
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
        )
        if pairing is None:
            return RemoteActionResult(status="unauthorized")

        diagnostics = await control.get_health_diagnostics()
        text = render_health_card(diagnostics.get("checks", []))
        return RemoteActionResult(status="ok", text=text)
```

`/health` returns plain text with no buttons, so — unlike `/settings` and
`/actions` — it does **not** need adding to `runtime.py`'s
already-sent-its-own-message guard; it relies entirely on the normal
fallback send there, exactly like `/status`.

- [ ] **Step 5: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k health_command
```

Expected: PASS.

- [ ] **Step 6: Lint and full remote suite**

```powershell
uv run pytest --no-cov -q tests/remote/
uv run ruff check app/remote/actions.py tests/remote/test_actions.py
uv run ty check app/remote/
```

- [ ] **Step 7: Commit**

```bash
git add app/remote/actions.py tests/remote/test_actions.py
git commit -m "feat(remote): wire /health command"
```

---

### Task 4: Wire `/changes` and its diff drill-down

**ACs:** AC-52, AC-58 (partial — adds `changes` to the command set)

**Files:**

- Modify: `app/remote/actions.py`
- Modify: `tests/remote/test_actions.py`

**Interfaces:**

- Changes `_SLASH_COMMANDS`: adds `"changes"`.
- Produces (private): `_cmd_changes`, `_exec_changes_diff`.
- Changes `_execute_action`: gains a `changes_diff` branch.

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_actions.py (add, e.g. to a new class TestChanges)
class TestChanges:
    @pytest.mark.asyncio
    async def test_changes_command_lists_files_with_counts(
        self, service: RemoteActionService
    ) -> None:
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Fix auth tests", mode="work", session_type="main",
                workspace="/tmp/fake-workspace",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            from app.services.turn_changes import ChangedFile, TurnChangesSnapshot

            fake_snapshot = TurnChangesSnapshot(
                session_id=str(session.id),
                files=[ChangedFile(path="app/auth.py", status="modified", additions=10, deletions=2)],
                additions=10,
                deletions=2,
            )

            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.services.turn_changes.get_latest",
                    return_value=fake_snapshot,
                ),
            ):
                action = _make_action(text="/changes")
                result = await service.dispatch_command(db, action)

        assert result.status == "ok"
        assert "app/auth.py" in result.text
        assert "+10" in result.text

    @pytest.mark.asyncio
    async def test_changes_command_without_active_session_is_friendly(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        mock_pairing = MagicMock()
        mock_pairing.active_session_id = None

        with patch.object(
            service._pairing_service, "authorize", return_value=mock_pairing
        ):
            action = _make_action(text="/changes")
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"
        assert "no active task yet" in result.text.lower()

    @pytest.mark.asyncio
    async def test_changes_diff_callback_fetches_and_sends_the_diff(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Fix auth tests", mode="work", session_type="main",
                workspace="/tmp/fake-workspace",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            from app.services.turn_changes import ChangedFile, TurnChangesSnapshot

            fake_snapshot = TurnChangesSnapshot(
                session_id=str(session.id),
                files=[ChangedFile(path="app/auth.py", status="modified", additions=10, deletions=2)],
                additions=10,
                deletions=2,
            )

            async def _fake_get_file_diff(workspace: str, path: str) -> str:
                return "--- a/app/auth.py\n+++ b/app/auth.py\n+fixed"

            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.services.turn_changes.get_latest",
                    return_value=fake_snapshot,
                ),
            ):
                settings_action = _make_action(text="/changes", connection_id=conn_id)
                await service.dispatch_command(db, settings_action)

            sent_buttons = adapter.sent_messages[-1].buttons
            file_token = next(
                b.token for b in sent_buttons if "app/auth.py" in b.text
            )

            with patch(
                "app.remote.control.get_file_diff", _fake_get_file_diff
            ):
                callback_action = _make_action(
                    kind=RemoteInboundActionKind.CALLBACK,
                    callback_token=file_token,
                    connection_id=conn_id,
                )
                handled = await service.handle_action_callback(callback_action, db)

            assert handled is True
            assert any(
                "fixed" in text for text in adapter.sent_texts
            )
```

*(These tests mock `app.services.turn_changes.get_latest` — check whether
this file already imports `turn_changes`/`ChangedFile`/`TurnChangesSnapshot`
at the top before adding a second, conflicting local import; add the
import at the top alongside the existing `app.core.db`/`app.models.chat`
imports from Task 5 of the previous plan if not already present.)*

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k Changes
```

Expected: FAIL — `/changes` falls through to `_cmd_help`.

- [ ] **Step 3: Add `/changes` to the known commands and dispatch**

```python
# app/remote/actions.py — _SLASH_COMMANDS
_SLASH_COMMANDS: frozenset[str] = frozenset(
    {
        "start", "help", "status", "new", "stop", "unpair", "actions",
        "settings", "health", "changes",
    }
)
```

```python
# app/remote/actions.py — inside dispatch_command, alongside the other elif branches
        elif command == "changes":
            return await self._cmd_changes(db, action)
```

- [ ] **Step 4: Implement `_cmd_changes`**

```python
# app/remote/actions.py — new method, near _cmd_settings
    async def _cmd_changes(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        from app.models.chat import ChatSession
        from app.remote.formatting import render_changes_card
        from app.services.turn_changes import get_latest

        pairing = await self._pairing_service.authorize(
            db,
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
        )
        if pairing is None:
            return RemoteActionResult(status="unauthorized")

        no_changes_text = (
            "No active task yet — send a message to start one, then "
            "/changes shows what it touched."
        )
        if pairing.active_session_id is None:
            await self._send(action.principal.destination_id, no_changes_text)
            return RemoteActionResult(status="ok", text=no_changes_text)

        session = await db.get(ChatSession, pairing.active_session_id)
        if session is None:
            await self._send(action.principal.destination_id, no_changes_text)
            return RemoteActionResult(status="ok", text=no_changes_text)

        session_id = str(session.id)
        snapshot = get_latest(session_id)
        if snapshot is None or not snapshot.files:
            no_files_text = "No file changes recorded for this task yet."
            await self._send(action.principal.destination_id, no_files_text)
            return RemoteActionResult(status="ok", text=no_files_text)

        bounded_files = snapshot.files[:8]
        file_tokens = {
            f.path: self._issue_token(
                connection_id=action.connection_id,
                principal_id=action.principal.principal_id,
                destination_id=action.principal.destination_id,
                session_id=session_id,
                action_kind="changes_diff",
                action_target=f.path,
            )
            for f in bounded_files
        }

        text, buttons = render_changes_card(
            title=session.title or "Task",
            files=[
                (f.path, f.status, f.additions, f.deletions) for f in bounded_files
            ],
            additions=snapshot.additions,
            deletions=snapshot.deletions,
            file_tokens=file_tokens,
        )

        await self._send(action.principal.destination_id, text, buttons=buttons)
        return RemoteActionResult(status="ok", text=text)
```

- [ ] **Step 5: Run and confirm the command-level tests pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py -k "changes_command"
```

Expected: PASS.

- [ ] **Step 6: Implement the `changes_diff` capability branch**

Unlike every existing capability action kind, this one fetches its content
fresh at tap time rather than reading a pre-stored `action_target` string
— it stores the *file path* in `action_target` and resolves the session's
workspace (needed for `control.get_file_diff`) from `cap.session_id` at
callback time.

```python
# app/remote/actions.py — inside _execute_action, alongside the set_mode/
# set_agent/set_model branches added in the previous plan
        elif cap.action_kind == "changes_diff":
            return await self._exec_changes_diff(cap, action, db)
```

```python
# app/remote/actions.py — new method, near _exec_set_model
    async def _exec_changes_diff(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        from uuid import UUID as _UUID

        from app.models.chat import ChatSession
        from app.remote import control

        try:
            session_uuid = _UUID(cap.session_id)
        except ValueError:
            await self._reply_text(
                action.principal.destination_id, "That task no longer exists."
            )
            return True

        session = await db.get(ChatSession, session_uuid)
        if session is None or not session.workspace:
            await self._reply_text(
                action.principal.destination_id,
                "That task's workspace is no longer available.",
            )
            return True

        diff = await control.get_file_diff(session.workspace, cap.action_target)
        if not diff.strip():
            await self._reply_text(
                action.principal.destination_id,
                f"No diff available for {cap.action_target}.",
            )
            return True

        redacted = _redact_text(diff)
        for text in _render_detail_cards(f"Diff: {cap.action_target}", redacted):
            await self._send(
                action.principal.destination_id,
                text,
                connection_id=action.connection_id,
                priority=RemoteOutboundPriority.HIGH,
            )
        return True
```

- [ ] **Step 7: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_actions.py
```

Expected: PASS (every test in the file, including the drill-down one).

- [ ] **Step 8: Full remote suite, lint, type-check**

```powershell
uv run pytest --no-cov -q tests/remote/
uv run ruff check app/remote/ tests/remote/
uv run ty check app/remote/
```

- [ ] **Step 9: Commit**

```bash
git add app/remote/actions.py tests/remote/test_actions.py
git commit -m "feat(remote): wire /changes command with on-demand diff drill-down"
```

---

## Self-review notes

- **Spec coverage:** AC-51 (Task 3), AC-52 (Task 4) are each covered.
  AC-53–58 remain out of scope for this plan.
- **The two route-import exceptions are each justified in the same place
  a reader would look for it:** `control.py`'s module docstring already
  explains the `get_registry` exception from Phase 2; Task 1 extends that
  same docstring reasoning to `health_diagnostics`/`get_diff_view` rather
  than introducing a second, separately-justified pattern.
- **`changes_diff` is flagged explicitly as the first fetch-on-tap
  capability** in this codebase (every other drill-down reads a
  pre-captured string) — Task 4 states this plainly so a future reader
  doesn't mistake `_send_detail`'s existing pre-stored-text assumption for
  a bug when they see this new capability doesn't route through it.
- **Type/name consistency:** `render_changes_card`'s `files` tuple order
  `(path, status, additions, deletions)` matches `ChangedFile`'s field
  order exactly (Task 2's docstring states this explicitly) and matches
  `_cmd_changes`'s list-comprehension call site (Task 4) exactly.
- **Known uncertainty flagged for the executor:** Task 1's test count
  ("14 tests") and Task 4's exact mock patch targets
  (`app.services.turn_changes.get_latest`, `app.remote.control.get_file_diff`)
  should be double-checked against `tests/remote/test_actions.py`'s actual
  top-of-file imports before writing — if `turn_changes`/`ChangedFile`/
  `TurnChangesSnapshot` aren't already imported there, add them, following
  the same pattern Task 5 of the previous plan used for `ChatSession`.
