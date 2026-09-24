# Remote Telegram: Decidable Approvals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Telegram permission gate decidable (show the real command
and a derived severity instead of just a tool name) and make it actually
resolve (fix the card so it edits into a decided state instead of keeping
live buttons forever) — Phase 1 of the larger control-surface spec, covering
exactly AC-45, AC-46, and AC-47.

**Architecture:** A new pure module (`app/remote/severity.py`) derives a
display-only severity from tool name and command text. `app/remote/formatting.py`
gains two builders — the ask-card and the resolved-card — that render it.
`app/remote/gates.py`'s permission path is extracted into its own method that
uses both, issues an `always` token alongside `once`/`reject`, stamps every
sent card with a `correlation_id`, and replaces the dead
`chat_id`/`message_id` fields with a generic edit-to-resolved-form path used
by all three gate kinds.

**Tech Stack:** Python 3.12, FastAPI, asyncio, pytest, pytest-asyncio.

**Spec:** [`remote-telegram-control-surface.md`](remote-telegram-control-surface.md)
(amends `remote-channel-telegram.md` and `remote-telegram-response-ui.md`) —
this plan implements exactly AC-45, AC-46, and AC-47 of that document.

## Global Constraints

- Severity is advisory display only — it must never change which requests
  are gated, which replies are accepted, or how any reply resolves (AC-46).
  `PermissionService` remains the sole gating authority.
- Every field not authored as a static string in `formatting.py` is redacted
  via `_redact_text` (or `protect_outbound_text` directly) and then
  HTML-escaped, redaction first, escaping last (AC-24, already accepted).
- `on_gate`/`on_reply` stay synchronous and non-blocking — no database read,
  no `await`, inside either (matches the accepted spec's observer contract;
  `on_gate` today has no DB access and this plan must not add one).
- Callback tokens stay opaque, `<=64` bytes, connection/principal-bound —
  unchanged token issuance mechanism (`_issue_token`), just one more token
  per permission request when `always_patterns` is non-empty.
- `answer_callback` is still called before gate resolution (AC-26) — nothing
  in this plan changes `handle_callback`'s ordering.
- Every task cites its spec ACs, writes a failing test before implementation,
  and leaves the test suite green at its checkpoint.
- Commit at the end of each task.

---

## File and interface map

New units:

- `app/remote/severity.py` — `Severity` type alias and `derive_severity()`.
- `tests/remote/test_severity.py`.

Changed units:

- `app/remote/formatting.py` — adds `render_permission_card` and
  `render_permission_resolved_card`.
- `app/remote/gates.py` — `_PendingGate` drops `chat_id`/`message_id`, gains
  `command: str`; `on_gate`'s permission branch becomes
  `_on_permission_asked`; `on_reply` becomes gate-kind-generic and always
  edits via `correlation_id`; `_resolve_permission` accepts `always`;
  `_edit_remove_buttons`/`_do_edit_remove` are replaced by
  `_enqueue_resolved_edit`/`_do_resolved_edit`.
- `tests/remote/test_formatting.py`, `tests/remote/test_gates.py` — updated
  and new focused evidence.

---

### Task 1: Severity derivation

**ACs:** AC-46

**Files:**

- Create: `app/remote/severity.py`
- Create: `tests/remote/test_severity.py`

**Interfaces:**

- Produces: `Severity = Literal["high", "elevated", "normal"]`,
  `derive_severity(*, tool: str, command: str) -> Severity`.
- Consumes: nothing (pure function, no imports from elsewhere in
  `app.remote`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_severity.py
from app.remote.severity import derive_severity


def test_destructive_command_is_high_severity():
    assert derive_severity(tool="shell", command="rm -rf build/") == "high"


def test_force_push_is_high_severity():
    assert (
        derive_severity(tool="shell", command="git push --force origin main")
        == "high"
    )


def test_shell_tool_without_destructive_pattern_is_elevated():
    assert derive_severity(tool="shell", command="pytest -q") == "elevated"


def test_python_tool_is_elevated():
    assert derive_severity(tool="python", command="print(1)") == "elevated"


def test_read_only_tool_is_normal():
    assert derive_severity(tool="read", command="tests/test_auth.py") == "normal"


def test_detection_is_case_insensitive():
    assert derive_severity(tool="shell", command="RM -RF /tmp/x") == "high"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_severity.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.remote.severity'`.

- [ ] **Step 3: Implement `severity.py`**

```python
# app/remote/severity.py
"""Advisory-only command severity for permission cards.

Display hint alone — never consulted by any gating decision.
``PermissionService`` (``app/agent/permission.py``) is the sole authority on
whether a request blocks; this module exists only so a phone operator sees
"rm -rf" and "read a file" rendered differently, never to decide anything.
"""

from __future__ import annotations

from typing import Literal

Severity = Literal["high", "elevated", "normal"]

__all__ = ["Severity", "derive_severity"]

#: Substrings that mark a command as destructive regardless of tool.
_DESTRUCTIVE_SUBSTRINGS = (
    "rm -rf",
    "rm -r -f",
    "git clean -fd",
    "git reset --hard",
    "git push --force",
    "git push -f",
    "drop table",
    "drop database",
    "truncate table",
)

#: Tools that run arbitrary code/commands — elevated even without a
#: destructive-pattern match.
_ELEVATED_TOOLS = frozenset({"shell", "bash", "python", "process", "rm"})


def derive_severity(*, tool: str, command: str) -> Severity:
    """Derive a display-only severity from a permission request's tool and
    command text. Never raises; unknown input degrades to "normal"."""
    lowered = command.lower()
    if any(pattern in lowered for pattern in _DESTRUCTIVE_SUBSTRINGS):
        return "high"
    if tool in _ELEVATED_TOOLS:
        return "elevated"
    return "normal"
```

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_severity.py
```

Expected: PASS (6 tests).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/severity.py tests/remote/test_severity.py
uv run ty check app/remote/severity.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/severity.py tests/remote/test_severity.py
git commit -m "feat(remote): add advisory-only permission severity derivation"
```

---

### Task 2: Permission card rendering

**ACs:** AC-45, AC-46 (display half), AC-47 (resolved-card content)

**Files:**

- Modify: `app/remote/formatting.py`
- Modify: `tests/remote/test_formatting.py`

**Interfaces:**

- Produces: `render_permission_card(*, tool: str, command: str, severity: str,
  agent: str, always_glob: str | None, always_token: str | None,
  once_token: str, reject_token: str) -> tuple[str, tuple[RemoteButton, ...]]`,
  `render_permission_resolved_card(*, command: str, resolution: str) ->
  tuple[str, tuple[RemoteButton, ...]]`.
- Consumes: `app.remote.contracts.RemoteButton`, `escape` (already in this
  module).

- [ ] **Step 1: Write the failing tests**

```python
# tests/remote/test_formatting.py (add)
def test_render_permission_card_shows_command_and_severity_icon():
    text, buttons = formatting.render_permission_card(
        tool="shell",
        command="rm -rf build/",
        severity="high",
        agent="evoflux",
        always_glob=None,
        always_token=None,
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert "rm -rf build/" in text
    assert "\U0001f534" in text  # red circle = high severity
    assert "shell" in text
    assert "evoflux" in text
    assert buttons == (
        RemoteButton(text="Allow once", token="once-tok"),
        RemoteButton(text="Reject", token="reject-tok"),
    )


def test_render_permission_card_escapes_command():
    text, _ = formatting.render_permission_card(
        tool="shell",
        command="echo <script>alert(1)</script>",
        severity="elevated",
        agent="evoflux",
        always_glob=None,
        always_token=None,
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_permission_card_adds_allow_for_session_button_with_glob():
    text, buttons = formatting.render_permission_card(
        tool="shell",
        command="git push origin main",
        severity="elevated",
        agent="evoflux",
        always_glob="git push *",
        always_token="always-tok",
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert "git push *" in text or any("git push *" in b.text for b in buttons)
    assert buttons == (
        RemoteButton(text="Allow once", token="once-tok"),
        RemoteButton(
            text="\U0001f512 Allow for session — git push *", token="always-tok"
        ),
        RemoteButton(text="Reject", token="reject-tok"),
    )


def test_render_permission_card_omits_always_button_without_glob():
    _, buttons = formatting.render_permission_card(
        tool="read",
        command="tests/test_auth.py",
        severity="normal",
        agent="evoflux",
        always_glob=None,
        always_token=None,
        once_token="once-tok",
        reject_token="reject-tok",
    )
    assert len(buttons) == 2


def test_render_permission_resolved_card_states_decision_and_has_no_buttons():
    text, buttons = formatting.render_permission_resolved_card(
        command="rm -rf build/", resolution="once"
    )
    assert "rm -rf build/" in text
    assert "Allowed once" in text
    assert buttons == ()


def test_render_permission_resolved_card_escapes_command():
    text, _ = formatting.render_permission_resolved_card(
        command="<script>alert(1)</script>", resolution="reject"
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py -k permission
```

Expected: FAIL with `AttributeError: module 'app.remote.formatting' has no
attribute 'render_permission_card'`.

- [ ] **Step 3: Implement the builders**

```python
# app/remote/formatting.py — add to __all__:
    "render_permission_card",
    "render_permission_resolved_card",
```

```python
# app/remote/formatting.py — new module-level constants, near _STATUS_ICON
_SEVERITY_ICON = {"high": "\U0001f534", "elevated": "\U0001f7e0", "normal": "\U0001f527"}
_SEVERITY_LABEL = {
    "high": "Dangerous command",
    "elevated": "Command",
    "normal": "Permission requested",
}
_RESOLUTION_ICON = {"once": "✅", "always": "\U0001f512", "reject": "❌"}
_RESOLUTION_LABEL = {
    "once": "Allowed once",
    "always": "Allowed for session",
    "reject": "Rejected",
}
```

```python
# app/remote/formatting.py — new functions
def render_permission_card(
    *,
    tool: str,
    command: str,
    severity: str,
    agent: str,
    always_glob: str | None,
    always_token: str | None,
    once_token: str,
    reject_token: str,
) -> tuple[str, tuple[RemoteButton, ...]]:
    icon = _SEVERITY_ICON.get(severity, "\U0001f527")
    label = _SEVERITY_LABEL.get(severity, "Permission requested")
    text = (
        f"{icon} <b>{escape(label)}</b>\n"
        f"<pre>{escape(command)}</pre>\n"
        f"<i>{escape(tool)} · {escape(agent)}</i>"
    )
    buttons = [RemoteButton(text="Allow once", token=once_token)]
    if always_token and always_glob:
        buttons.append(
            RemoteButton(
                text=f"\U0001f512 Allow for session — {escape(always_glob)}",
                token=always_token,
            )
        )
    buttons.append(RemoteButton(text="Reject", token=reject_token))
    return text, tuple(buttons)


def render_permission_resolved_card(
    *, command: str, resolution: str
) -> tuple[str, tuple[RemoteButton, ...]]:
    icon = _RESOLUTION_ICON.get(resolution, "✅")
    label = _RESOLUTION_LABEL.get(resolution, "Resolved")
    text = f"{icon} <b>{escape(label)}</b>\n<pre>{escape(command)}</pre>"
    return text, ()
```

Note: `RemoteButton(text=f"...\U0001f512 Allow for session — {escape(always_glob)}", ...)`
already escapes `always_glob` inline — the test's expected button text uses
the literal glob `"git push *"` which contains no HTML-special characters,
so `escape("git push *") == "git push *"` and the equality assertion holds.

- [ ] **Step 4: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_formatting.py
```

Expected: PASS (all tests in the file, including the 6 new ones).

- [ ] **Step 5: Lint**

```powershell
uv run ruff check app/remote/formatting.py tests/remote/test_formatting.py
uv run ty check app/remote/formatting.py
```

- [ ] **Step 6: Commit**

```bash
git add app/remote/formatting.py tests/remote/test_formatting.py
git commit -m "feat(remote): render permission cards with the real command and severity"
```

---

### Task 3: Wire the gate bridge — real cards, `always` reply, and visible resolution

**ACs:** AC-45, AC-46, AC-47, AC-28 (revised)

**Files:**

- Modify: `app/remote/gates.py`
- Modify: `tests/remote/test_gates.py`

**Interfaces:**

- Changes `_PendingGate`: removes `chat_id`, `message_id`; adds
  `command: str = ""`.
- Changes `RemoteGateBridge._resolve_permission`: accepts `"always"` as a
  valid `cap.action` in addition to `"once"`/`"reject"`.
- Produces (private, no external callers): `_on_permission_asked`,
  `_enqueue_resolved_edit`, `_do_resolved_edit`, `_resolution_text`.
- Consumes: `app.remote.severity.derive_severity`,
  `app.remote.formatting.render_permission_card`,
  `app.remote.formatting.render_permission_resolved_card`.

- [ ] **Step 1: Write failing tests for the real permission card**

```python
# tests/remote/test_gates.py (add near the permission-card tests)
# Async + a drain sleep, matching this file's existing convention for
# on_gate tests (_enqueue_send schedules a fire-and-forget task; a plain
# sync test has no running loop for that task to be scheduled on at all).
@pytest.mark.asyncio
async def test_on_gate_permission_renders_the_real_command(
    bridge: RemoteGateBridge, adapter: FakeAdapter
) -> None:
    bridge.on_gate(
        session_id="sess-1",
        event_type="permission_asked",
        data={
            "request_id": "req-1",
            "tool": "shell",
            "patterns": ["rm -rf build/"],
            "always_patterns": [],
            "metadata": {"agent": "evoflux"},
        },
        connection_id=uuid4(),
        destination_id="chat-1",
    )
    await asyncio.sleep(0.05)

    assert len(adapter.sent) == 1
    assert "rm -rf build/" in adapter.sent[0].text
    assert "Permission requested: shell" not in adapter.sent[0].text
    assert adapter.sent[0].correlation_id == "gate:req-1"
    assert [b.text for b in adapter.sent[0].buttons] == ["Allow once", "Reject"]


@pytest.mark.asyncio
async def test_on_gate_permission_offers_allow_for_session_with_glob(
    bridge: RemoteGateBridge, adapter: FakeAdapter
) -> None:
    bridge.on_gate(
        session_id="sess-1",
        event_type="permission_asked",
        data={
            "request_id": "req-1",
            "tool": "shell",
            "patterns": ["git push origin main"],
            "always_patterns": ["git push *"],
            "metadata": {"agent": "evoflux"},
        },
        connection_id=uuid4(),
        destination_id="chat-1",
    )
    await asyncio.sleep(0.05)

    button_texts = [b.text for b in adapter.sent[0].buttons]
    assert len(button_texts) == 3
    assert "git push *" in button_texts[1]
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py -k "real_command or allow_for_session"
```

Expected: FAIL — `adapter.sent[0].text` still says
`"Permission requested: shell"`, no `correlation_id`.

- [ ] **Step 3: Extract and rewrite the permission path in `on_gate`**

```python
# app/remote/gates.py — imports, add:
import asyncio

from app.remote.formatting import (
    escape,
    render_permission_card,
    render_permission_resolved_card,
)
from app.remote.severity import derive_severity
```

```python
# app/remote/gates.py — replace the _PendingGate dataclass
@dataclass
class _PendingGate:
    """Tracks one gate's outstanding capabilities and the command text (if
    any) needed to render its resolved form later."""

    request_id: str
    session_id: str
    gate_kind: GateKind
    tokens: list[str] = field(default_factory=list)
    command: str = ""
```

```python
# app/remote/gates.py — replace on_gate's body
    def on_gate(
        self,
        session_id: str,
        event_type: str,
        data: dict,
        connection_id: UUID,
        destination_id: str,
    ) -> None:
        """Handle a gate event by creating opaque tokens and enqueuing a card.

        Called by the projection's ``_handle_gate``.
        """
        request_id = data.get("request_id", "")
        if not request_id:
            return

        if event_type == "permission_asked":
            self._on_permission_asked(session_id, data, connection_id, destination_id, request_id)
            return

        gate_kind: GateKind
        actions: list[tuple[str, str]]  # (action_label, button_text)

        if event_type == "question_asked":
            gate_kind = "question"
            questions = data.get("questions", [])
            if questions:
                first_q = questions[0]
                text = f"Question: {first_q.get('question', '')}"
                options = first_q.get("options", [])
                actions = [(opt, opt) for opt in options[:8]]  # bound to 8
            else:
                text = "Question asked."
                actions = []
        elif event_type == "plan_approval_requested":
            gate_kind = "plan"
            plan_text = data.get("plan", "")
            steps = data.get("steps", [])
            text = f"Plan ready for review ({len(steps)} steps)."
            if plan_text:
                text = f"Plan: {plan_text[:200]}"
            actions = [("approve", "Approve"), ("reject", "Reject")]
        else:
            return

        buttons: list[RemoteButton] = []
        gate = _PendingGate(
            request_id=request_id,
            session_id=session_id,
            gate_kind=gate_kind,
        )

        for action_value, button_text in actions:
            token = self._issue_token(
                connection_id=connection_id,
                principal_id="",
                destination_id=destination_id,
                session_id=session_id,
                request_id=request_id,
                gate_kind=gate_kind,
                action=action_value,
            )
            buttons.append(RemoteButton(text=button_text, token=token))
            gate.tokens.append(token)
            self._pending_by_token[token] = request_id

        self._pending_gates[request_id] = gate

        text = _redact_text(text)
        msg = RemoteOutboundMessage(
            connection_id=connection_id,
            destination_id=destination_id,
            text=text,
            buttons=tuple(buttons),
            priority=RemoteOutboundPriority.HIGH,
            correlation_id=f"gate:{request_id}",
        )
        self._enqueue_send(msg)

    def _on_permission_asked(
        self,
        session_id: str,
        data: dict,
        connection_id: UUID,
        destination_id: str,
        request_id: str,
    ) -> None:
        """Render and send a decidable permission card (AC-45/AC-46): the
        real command and a derived, advisory-only severity, never a tool
        name alone."""
        tool = data.get("tool", "unknown")
        patterns = data.get("patterns") or []
        command = patterns[0] if patterns else tool
        always_patterns = data.get("always_patterns") or []
        always_glob = always_patterns[0] if always_patterns else None
        agent_name = data.get("metadata", {}).get("agent", "agent")
        severity = derive_severity(tool=tool, command=command)

        gate = _PendingGate(
            request_id=request_id,
            session_id=session_id,
            gate_kind="permission",
            command=_redact_text(command),
        )

        once_token = self._issue_token(
            connection_id=connection_id,
            principal_id="",
            destination_id=destination_id,
            session_id=session_id,
            request_id=request_id,
            gate_kind="permission",
            action="once",
        )
        gate.tokens.append(once_token)
        self._pending_by_token[once_token] = request_id

        always_token: str | None = None
        if always_glob:
            always_token = self._issue_token(
                connection_id=connection_id,
                principal_id="",
                destination_id=destination_id,
                session_id=session_id,
                request_id=request_id,
                gate_kind="permission",
                action="always",
            )
            gate.tokens.append(always_token)
            self._pending_by_token[always_token] = request_id

        reject_token = self._issue_token(
            connection_id=connection_id,
            principal_id="",
            destination_id=destination_id,
            session_id=session_id,
            request_id=request_id,
            gate_kind="permission",
            action="reject",
        )
        gate.tokens.append(reject_token)
        self._pending_by_token[reject_token] = request_id

        self._pending_gates[request_id] = gate

        text, buttons = render_permission_card(
            tool=tool,
            command=gate.command,
            severity=severity,
            agent=agent_name,
            always_glob=_redact_text(always_glob) if always_glob else None,
            always_token=always_token,
            once_token=once_token,
            reject_token=reject_token,
        )
        msg = RemoteOutboundMessage(
            connection_id=connection_id,
            destination_id=destination_id,
            text=text,
            buttons=buttons,
            priority=RemoteOutboundPriority.HIGH,
            correlation_id=f"gate:{request_id}",
        )
        self._enqueue_send(msg)
```

- [ ] **Step 4: Update the one pre-existing test this rename breaks**

`test_permission_gate_creates_allow_and_reject_buttons`
(`TestGateRendering`) asserts the old button label verbatim:

```python
assert msg.buttons[0].text == "Allow"
assert msg.buttons[1].text == "Reject"
```

`render_permission_card` labels the first button `"Allow once"`. Update
those two lines in place:

```python
        assert msg.buttons[0].text == "Allow once"
        assert msg.buttons[1].text == "Reject"
```

- [ ] **Step 5: Run and confirm all three pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py -k "real_command or allow_for_session or creates_allow_and_reject"
```

Expected: PASS (3 tests: the 2 new ones plus the updated pre-existing one).

- [ ] **Step 6: Write a failing test for `always` reply support**

Mirrors the existing `test_callback_resolves_permission_once`/
`test_callback_resolves_permission_reject` in `TestCallbackOrdering`
exactly — same `patch(...)` + `MagicMock` house style, going through the
public `handle_callback`, not the private resolver.

```python
# tests/remote/test_gates.py (add to class TestCallbackOrdering)
    @pytest.mark.asyncio
    async def test_callback_resolves_permission_always(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={
                "request_id": "req-1",
                "tool": "shell",
                "patterns": ["git push origin main"],
                "always_patterns": ["git push *"],
            },
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        # Token order from _on_permission_asked: once, always, reject.
        always_token = gate.tokens[1]

        from unittest.mock import patch

        mock_svc = MagicMock()
        mock_svc.reply.return_value = True

        with patch(
            "app.agent.permission.get_service_for_session", return_value=mock_svc
        ):
            action = _make_action(callback_token=always_token, connection_id=conn_id)
            await bridge.handle_callback(action)

        mock_svc.reply.assert_called_once_with("req-1", "always")
```

- [ ] **Step 7: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py -k resolves_permission_always
```

Expected: FAIL — `remote_gate_invalid_permission_action` branch returns
`False` for `action="always"`, so `mock_svc.reply` is never called.

- [ ] **Step 8: Accept `always` in `_resolve_permission`**

```python
# app/remote/gates.py — replace _resolve_permission's action check
    async def _resolve_permission(
        self, cap: GateCapability, action: RemoteInboundAction
    ) -> bool:
        """Resolve a permission gate. Remote accepts once/always/reject
        (AC-28, revised) — "always" is session-scoped in PermissionService
        (it appends a rule to session_ruleset, not a permanent grant), which
        is exactly what the remote card's "Allow for session" label says."""
        from app.agent.permission import Reply, get_service_for_session

        if cap.action not in ("once", "always", "reject"):
            logger.warning(
                "remote_gate_invalid_permission_action action={}",
                cap.action,
            )
            return False
        reply_value: Reply = cap.action  # ty: ignore[invalid-assignment]

        svc = get_service_for_session(cap.session_id)
        if svc is None:
            logger.debug(
                "remote_gate_permission_service_missing session_id={}",
                cap.session_id,
            )
            return False

        resolved = svc.reply(cap.request_id, reply_value)
        if resolved:
            logger.info(
                "remote_gate_permission_resolved request_id={} reply={}",
                cap.request_id,
                reply_value,
            )
        return resolved
```

- [ ] **Step 9: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py -k resolves_permission_always
```

Expected: PASS.

- [ ] **Step 10: Write a failing test for visible resolution**

`test_on_reply_cleans_up_capabilities` already exists in `TestReplyEvents`
and covers capability/token cleanup — add the one thing it doesn't cover:
that the card is actually edited into a resolved, decision-stating form.
This test must be `async` (unlike its sync sibling) because
`_enqueue_resolved_edit`'s fire-and-forget task needs a running event loop
to actually schedule, and a brief `asyncio.sleep` to let that task run
before asserting on `adapter.edited`.

```python
# tests/remote/test_gates.py — add to class TestReplyEvents
    @pytest.mark.asyncio
    async def test_on_reply_edits_the_card_to_a_resolved_form(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={
                "request_id": "req-1",
                "tool": "shell",
                "patterns": ["rm -rf build/"],
            },
            connection_id=uuid4(),
            destination_id="chat-1",
        )

        bridge.on_reply(
            "sess-1", "permission_replied", {"request_id": "req-1", "reply": "once"}
        )
        await asyncio.sleep(0.05)

        assert len(adapter.edited) == 1
        assert adapter.edited[0].correlation_id == "gate:req-1"
        assert adapter.edited[0].buttons == ()
        assert "Allowed once" in adapter.edited[0].text
        assert "rm -rf build/" in adapter.edited[0].text
```

- [ ] **Step 11: Run and confirm failure**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py -k resolved_form
```

Expected: FAIL — `on_reply`'s `chat_id is not None and message_id is not
None` guard is always false, so `adapter.edited` stays empty.

- [ ] **Step 12: Replace `on_reply` and the dead edit path**

```python
# app/remote/gates.py — replace on_reply
    def on_reply(self, session_id: str, event_type: str, data: dict) -> None:
        """Handle a gate reply event by editing its card into a resolved,
        button-free form (AC-47).

        Called by the projection when a ``permission_replied``,
        ``question_replied``, or ``plan_approval_replied`` event fires.
        """
        request_id = data.get("request_id", "")
        if not request_id:
            return

        gate = self._pending_gates.pop(request_id, None)
        if gate is None:
            return

        for token in gate.tokens:
            self._capabilities.pop(token, None)
            self._pending_by_token.pop(token, None)

        resolution_text = self._resolution_text(gate, data)
        self._enqueue_resolved_edit(gate, resolution_text)

    def _resolution_text(self, gate: _PendingGate, data: dict) -> str:
        """Build the resolved-form message text for one gate kind. Only
        permission gates have a per-decision label defined by the spec
        (AC-45's "Allowed once"/"Allowed for session"/"Rejected"); question
        and plan gates get a generic resolved marker."""
        if gate.gate_kind == "permission":
            reply = data.get("reply", "reject")
            text, _buttons = render_permission_resolved_card(
                command=gate.command or "(command unavailable)", resolution=reply
            )
            return text
        return "✅ <b>Resolved</b>"

    def _enqueue_resolved_edit(self, gate: _PendingGate, text: str) -> None:
        """Edit this gate's card into its resolved form — fire-and-forget,
        matching the delivery pattern already used by ``_enqueue_send``."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._do_resolved_edit(gate, text))
        except RuntimeError:
            pass

    async def _do_resolved_edit(self, gate: _PendingGate, text: str) -> None:
        try:
            msg = RemoteOutboundMessage(
                connection_id=UUID(int=0),  # not used for edit lookup
                destination_id="",
                text=text,
                buttons=(),
                correlation_id=f"gate:{gate.request_id}",
            )
            await self._adapter.edit(msg)
        except Exception as exc:
            logger.debug(
                "remote_gate_resolved_edit_failed request_id={} error={}",
                gate.request_id,
                exc,
            )
```

```python
# app/remote/gates.py — delete the now-unused _edit_remove_buttons and
# _do_edit_remove methods entirely (replaced by _enqueue_resolved_edit /
# _do_resolved_edit above).
```

- [ ] **Step 13: Run and confirm pass**

```powershell
uv run pytest --no-cov -q tests/remote/test_gates.py
```

Expected: PASS (every test in the file, including the pre-existing
`test_on_reply_cleans_up_capabilities` and the new resolved-form test).

- [ ] **Step 14: Full remote suite and lint**

```powershell
uv run pytest --no-cov -q tests/remote/
uv run ruff check app/remote/gates.py tests/remote/test_gates.py
uv run ty check app/remote/gates.py
```

Expected: all green. If any other test in the suite referenced
`_edit_remove_buttons`, `_PendingGate.chat_id`, or `_PendingGate.message_id`
directly, update it to the new `_enqueue_resolved_edit` path — grep first:

```powershell
grep -rn "chat_id\|message_id\|_edit_remove_buttons" tests/remote/test_gates.py
```

- [ ] **Step 15: Commit**

```bash
git add app/remote/gates.py tests/remote/test_gates.py
git commit -m "fix(remote): permission cards show the real command and actually resolve"
```

---

## Self-review notes

- **Spec coverage:** AC-45 (Task 2 + 3's card rendering), AC-46 (Task 1 +
  Task 2's severity display), AC-47 (Task 3's correlation-id send + resolved
  edit + dead-field removal), AC-28 revised (Task 3 Steps 5-8's `always`
  support) are each covered by a task above. AC-48 through AC-58 (mode/model/
  agent control, health, changes, live mode, onboarding, command-set) are
  explicitly out of scope for this plan — they are later phases of the same
  spec, to be written as separate plan documents once this phase lands, per
  the spec's own stated rollout order.
- **Type consistency:** `_PendingGate.command` (Task 3) matches the
  `gate.command` reads in `_resolution_text`; `render_permission_card`'s
  parameter names (Task 2) match every call site in `_on_permission_asked`
  (Task 3) exactly; `_resolve_permission`'s `Reply` import and literal values
  match `app/agent/permission.py:63`'s `Reply = Literal["once", "always",
  "reject"]` verified during spec research.
- **No placeholders:** every step above contains complete, runnable code —
  no "similar to Task N" references, no TODO markers.
