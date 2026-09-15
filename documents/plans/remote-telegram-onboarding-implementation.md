# Remote Telegram Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement AC-54 — a successful pairing sends a card naming the current permission mode and offering setup, health check, and start-working actions, instead of today's plain confirmation text with no way forward.

**Architecture:** A new `render_onboarding_card` builder in `formatting.py`, three new capability action kinds in `actions.py` (`onboarding_setup`, `onboarding_health`, `onboarding_start`) that delegate to the existing `_cmd_settings`/`_cmd_health` implementations (no new business logic — onboarding just gives the phone a shortcut into commands it already has), and `runtime.py`'s `_handle_pairing` sends the new card instead of the old plain-text confirmation. A rejected pairing still sends nothing (AC-9, unchanged).

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, `ruff`, `ty`.

**Spec:** `documents/plans/remote-telegram-control-surface.md`, AC-54.

## Global Constraints

- The mode line always reflects `ChatSession.model_fields["permission_mode"].default` (currently `"auto"`) — read programmatically, never hardcoded, so it can't silently drift from the model's real default.
- A rejected pairing attempt sends nothing at all (AC-9) — this plan touches only the success path.
- "Set up" and "Health check" reuse `_cmd_settings`/`_cmd_health` exactly as `/settings`/`/health` already do — no new session/db logic. At pairing time there is no active session yet, so tapping "Set up" shows the existing "no active task yet" message, same as typing `/settings` would right after pairing.

---

### Task 1: `render_onboarding_card` in `app/remote/formatting.py`

**Files:**
- Modify: `app/remote/formatting.py`
- Test: `tests/remote/test_formatting.py`

**Interfaces:**
- Produces: `render_onboarding_card(*, label: str, default_permission_mode: str, setup_token: str, health_token: str, start_token: str) -> tuple[str, tuple[RemoteButton, ...]]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/remote/test_formatting.py`:

```python
def test_render_onboarding_card_names_the_phone_and_states_auto_mode() -> None:
    text, buttons = formatting.render_onboarding_card(
        label="My Phone",
        default_permission_mode="auto",
        setup_token="setup-tok",
        health_token="health-tok",
        start_token="start-tok",
    )
    assert "My Phone" in text
    assert "connected to EvoFlux" in text
    assert "auto" in text
    assert "won't ask" in text
    assert len(buttons) == 3
    assert {b.token for b in buttons} == {"setup-tok", "health-tok", "start-tok"}


def test_render_onboarding_card_escapes_label() -> None:
    text, _ = formatting.render_onboarding_card(
        label="<script>alert(1)</script>",
        default_permission_mode="auto",
        setup_token="s",
        health_token="h",
        start_token="w",
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_onboarding_card_states_non_auto_mode_without_the_auto_warning() -> None:
    text, _ = formatting.render_onboarding_card(
        label="My Phone",
        default_permission_mode="ask",
        setup_token="s",
        health_token="h",
        start_token="w",
    )
    assert "ask" in text
    assert "won't ask" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_formatting.py -k onboarding -v`
Expected: FAIL with `AttributeError: module 'app.remote.formatting' has no attribute 'render_onboarding_card'`.

- [ ] **Step 3: Implement**

Add to `app/remote/formatting.py`'s `__all__` and body (near `render_settings_card`):

```python
def render_onboarding_card(
    *,
    label: str,
    default_permission_mode: str,
    setup_token: str,
    health_token: str,
    start_token: str,
) -> tuple[str, tuple[RemoteButton, ...]]:
    """The first-run card sent right after a successful pairing (AC-54) —
    a starting point rather than a dead end. The mode line is stated
    because it is the single most consequential default the operator
    should know about at pairing time: "auto" means no approval prompts
    will ever reach this phone."""
    mode_line = f"Mode is <code>{escape(default_permission_mode)}</code>"
    if default_permission_mode == "auto":
        mode_line += " — the agent won't ask before running commands."
    else:
        mode_line += "."
    text = (
        f'✅ <b>Paired!</b> This phone ("{escape(label)}") is now connected '
        f"to EvoFlux.\n\n{mode_line}"
    )
    buttons = (
        RemoteButton(text="⚙️ Set up", token=setup_token),
        RemoteButton(text="\U0001fa7a Health check", token=health_token),
        RemoteButton(text="\U0001f4ac Just start working", token=start_token),
    )
    return text, buttons
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/remote/test_formatting.py -v`
Expected: PASS, all tests in the file green.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/formatting.py tests/remote/test_formatting.py && uv run ty check app/remote/formatting.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/formatting.py tests/remote/test_formatting.py
git commit -m "feat(remote): add render_onboarding_card for the first-run pairing message (AC-54)"
```

---

### Task 2: Onboarding capability tokens in `app/remote/actions.py`

**Files:**
- Modify: `app/remote/actions.py`
- Test: `tests/remote/test_actions.py`

**Interfaces:**
- Produces: `RemoteActionService.build_onboarding_card(action: RemoteInboundAction, *, label: str) -> tuple[str, tuple[RemoteButton, ...]]` (public — `runtime.py` calls this directly, Task 3). Three new `_execute_action` action kinds: `onboarding_setup`, `onboarding_health`, `onboarding_start`.
- Consumes: `render_onboarding_card` (Task 1), the existing `_cmd_settings`/`_cmd_health`/`_issue_token`/`_reply_text`.

- [ ] **Step 1: Write the failing tests**

Add a new class to `tests/remote/test_actions.py`, after `TestSettings` (or anywhere top-level — read the file's existing `_make_action`/fixture names first, matching `TestSettings`'s own patterns for a paired action):

```python
class TestOnboarding:
    @pytest.mark.asyncio
    async def test_build_onboarding_card_mints_three_distinct_tokens(
        self, service: RemoteActionService
    ) -> None:
        action = _make_action(text="/start")

        text, buttons = service.build_onboarding_card(action, label="My Phone")

        assert "My Phone" in text
        assert len(buttons) == 3
        tokens = {b.token for b in buttons}
        assert len(tokens) == 3  # all distinct

    @pytest.mark.asyncio
    async def test_onboarding_setup_button_behaves_like_settings(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        onboarding_action = _make_action(text="/start", connection_id=conn_id)
        _text, buttons = service.build_onboarding_card(onboarding_action, label="My Phone")
        setup_token = next(b.token for b in buttons if "Set up" in b.text)

        mock_pairing = MagicMock()
        mock_pairing.active_session_id = None
        mock_pairing.label = "My Phone"

        async with db_module.async_session_factory() as db:
            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                callback_action = _make_action(
                    kind=RemoteInboundActionKind.CALLBACK,
                    callback_token=setup_token,
                    connection_id=conn_id,
                )
                handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert "No active task yet" in adapter.sent_messages[-1].text

    @pytest.mark.asyncio
    async def test_onboarding_health_button_sends_health_diagnostics(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        onboarding_action = _make_action(text="/start", connection_id=conn_id)
        _text, buttons = service.build_onboarding_card(onboarding_action, label="My Phone")
        health_token = next(b.token for b in buttons if "Health" in b.text)

        mock_pairing = MagicMock()

        async with db_module.async_session_factory() as db:
            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.remote.control.get_health_diagnostics",
                    new=AsyncMock(return_value={"checks": []}),
                ),
            ):
                callback_action = _make_action(
                    kind=RemoteInboundActionKind.CALLBACK,
                    callback_token=health_token,
                    connection_id=conn_id,
                )
                handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert "Health" in adapter.sent_messages[-1].text

    @pytest.mark.asyncio
    async def test_onboarding_start_button_sends_a_friendly_prompt(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        onboarding_action = _make_action(text="/start", connection_id=conn_id)
        _text, buttons = service.build_onboarding_card(onboarding_action, label="My Phone")
        start_token = next(b.token for b in buttons if "start" in b.text.lower())

        async with db_module.async_session_factory() as db:
            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=start_token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert adapter.sent_messages  # something was sent
```

This needs `from uuid import uuid4` (already imported at the top of the file per earlier tasks in this session) and `AsyncMock` (already added to the `unittest.mock` import line by the providers plan).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_actions.py -k TestOnboarding -v`
Expected: FAIL — `AttributeError: 'RemoteActionService' object has no attribute 'build_onboarding_card'`.

- [ ] **Step 3: Implement**

In `app/remote/actions.py`, add a public method (near `_cmd_settings`, since it shares the same token-issuing shape):

```python
    def build_onboarding_card(
        self, action: RemoteInboundAction, *, label: str
    ) -> tuple[str, tuple[RemoteButton, ...]]:
        """The first-run card sent right after a successful pairing
        (AC-54). Unlike every other card this module builds, no session
        or turn exists yet — these three tokens' session_id/action_target
        are unused placeholders, the same repurposed-field pattern already
        used for the response-mode tokens' pairing-id reuse."""
        from app.models.chat import ChatSession
        from app.remote.formatting import render_onboarding_card

        setup_token = self._issue_token(
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
            destination_id=action.principal.destination_id,
            session_id="",
            action_kind="onboarding_setup",
            action_target="",
        )
        health_token = self._issue_token(
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
            destination_id=action.principal.destination_id,
            session_id="",
            action_kind="onboarding_health",
            action_target="",
        )
        start_token = self._issue_token(
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
            destination_id=action.principal.destination_id,
            session_id="",
            action_kind="onboarding_start",
            action_target="",
        )
        default_mode = ChatSession.model_fields["permission_mode"].default
        return render_onboarding_card(
            label=label,
            default_permission_mode=default_mode,
            setup_token=setup_token,
            health_token=health_token,
            start_token=start_token,
        )
```

Add the three branches to `_execute_action`'s elif chain (after `set_response_mode`, before `changes_diff`):

```python
        elif cap.action_kind == "onboarding_setup":
            return await self._exec_onboarding_setup(cap, action, db)
        elif cap.action_kind == "onboarding_health":
            return await self._exec_onboarding_health(cap, action, db)
        elif cap.action_kind == "onboarding_start":
            return await self._exec_onboarding_start(cap, action, db)
```

Add the three handlers near `_exec_set_response_mode`:

```python
    async def _exec_onboarding_setup(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        """/settings already self-sends its reply — nothing further to do
        here, matching how /settings itself works when typed directly."""
        await self._cmd_settings(db, action)
        return True

    async def _exec_onboarding_health(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        """Unlike /settings, _cmd_health does not self-send (its text is
        normally sent by runtime.py's /health fallback path) — send it
        explicitly here."""
        result = await self._cmd_health(db, action)
        if result.text:
            await self._reply_text(action.principal.destination_id, result.text)
        return True

    async def _exec_onboarding_start(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        await self._reply_text(
            action.principal.destination_id,
            "Great — type your first message whenever you're ready.",
        )
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/remote/test_actions.py -v`
Expected: PASS, all tests in the file green.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/actions.py tests/remote/test_actions.py && uv run ty check app/remote/actions.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/actions.py tests/remote/test_actions.py
git commit -m "feat(remote): add onboarding capability tokens (setup/health/start) (AC-54)"
```

---

### Task 3: Wire the onboarding card into `runtime.py`'s pairing success path

**Files:**
- Modify: `app/remote/runtime.py`
- Test: `tests/remote/test_runtime.py`

**Interfaces:**
- Consumes: `RemoteActionService.build_onboarding_card` (Task 2).

- [ ] **Step 1: Write the failing test**

Add to `tests/remote/test_runtime.py`, near `test_handle_pairing_consumes_a_token_minted_via_the_shared_service`:

```python
@pytest.mark.asyncio
async def test_handle_pairing_success_offers_onboarding_buttons(
    session, fake_stores, fake_adapters
) -> None:
    connection = await _make_connection(session, enabled=True)
    fake_stores[connection.id] = FakeCredentialStore("secret-token")
    await remote_runtime.start()
    link = pairing_service.issue_link(connection)
    token = link.url.rsplit("start=", 1)[-1]

    action = RemoteInboundAction(
        connection_id=connection.id,
        kind=RemoteInboundActionKind.PAIRING_START,
        principal=RemotePrincipal(
            connection_id=connection.id,
            principal_id="12345",
            destination_id="12345",
            display="Test User",
        ),
        source_key=f"telegram:{connection.id}:1",
        pairing_token=token,
    )

    await remote_runtime._handle_pairing(action)

    assert len(fake_adapters[0].sent) == 1
    confirmation = fake_adapters[0].sent[0]
    assert "auto" in confirmation.text
    assert len(confirmation.buttons) == 3
    button_texts = {b.text for b in confirmation.buttons}
    assert any("Set up" in t for t in button_texts)
    assert any("Health" in t for t in button_texts)
    assert any("start working" in t.lower() for t in button_texts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/remote/test_runtime.py -k onboarding_buttons -v`
Expected: FAIL — `assert 0 == 3` (today's confirmation message carries no buttons at all).

- [ ] **Step 3: Implement**

In `app/remote/runtime.py`'s `_handle_pairing`, replace the plain-text confirmation send with:

```python
            # A silently-persisted pairing is indistinguishable from a
            # failed one from the phone's side — confirm it with a
            # starting point rather than a dead end (AC-54). Never sent on
            # rejection (AC-9: a refusal reveals no connection state).
            if self._adapter is not None and self._actions is not None:
                text, buttons = self._actions.build_onboarding_card(
                    action, label=result.label
                )
                await self._adapter.send(
                    RemoteOutboundMessage(
                        connection_id=action.connection_id,
                        destination_id=action.principal.destination_id,
                        text=text,
                        buttons=buttons,
                        priority=RemoteOutboundPriority.HIGH,
                    )
                )
```

This replaces the entire previous `if self._adapter is not None:` block (the one building the old plain `f'✅ Paired! ...'` string) — same guard condition plus the new `self._actions is not None` check (defensive: `_actions` is always set by the time a real `/start` deep link can be consumed, since the adapter's poll loop that delivers it only starts after `_start_locked` finishes constructing `_actions`, but the guard costs nothing and avoids a crash if that invariant is ever violated by a future refactor).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest --no-cov -q tests/remote/test_runtime.py -v`
Expected: PASS, all tests in the file green — including the pre-existing `test_handle_pairing_consumes_a_token_minted_via_the_shared_service`, which only asserts `"connected" in confirmation.text.lower()` and is unaffected by the added buttons.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/runtime.py tests/remote/test_runtime.py && uv run ty check app/remote/runtime.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/runtime.py tests/remote/test_runtime.py
git commit -m "feat(remote): send the onboarding card on a successful pairing (AC-54)"
```

---

## Final verification (after all three tasks)

- [ ] Run the full test suite: `uv run pytest --no-cov -q`
- [ ] Run `uv run ruff check .`
- [ ] Run `uv run ty check app/`
- [ ] Merge to local `main` following this session's established pattern: check `git status --short` on the main checkout first, fast-forward merge, re-run tests on the merged result, no push.

## Out of scope for this plan

This closes AC-54, the last item in the original control-surface spec (AC-45 through AC-58). Any further Telegram remote-control work (e.g. a `/providers` drill-down, live-mode UI polish) is a new request, not part of that spec.
