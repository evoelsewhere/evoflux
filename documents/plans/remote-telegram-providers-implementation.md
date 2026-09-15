# Remote Telegram Providers (Read-Only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement AC-53 — `/settings` shows how many providers are configured, and no remote code path can ever reach a credential-accepting provider endpoint.

**Architecture:** One new read-only aggregation in `control.py` (`count_configured_providers`) calling the existing `GET /api/settings/providers` route function directly — the third documented, deliberate exception to "service layer only" in this module (after the model catalog and health/diff). `render_settings_card` grows an optional `configured_provider_count` line. The AC's real weight is the inspection test: a static scan proving `app/remote/` never references any of the five write-capable provider functions (`save_provider`, `save_provider_visible_models`, `test_provider`, `list_provider_models`, `delete_provider`).

**Scope note:** The control-surface spec's mockup shows a `[ Providers ]` button opening a picker. Providers are read-only in this feature (no pick to make), so this plan implements the count line only — the load-bearing part of AC-53 per the spec's own Permissions section ("Provider read-only is enforced by inspection test rather than by convention") is the inspection test, not a richer display. A drill-down listing configured providers by name, or per-provider usage (AC references "usage"), is left for a follow-up if wanted.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, `ruff`, `ty`.

**Spec:** `documents/plans/remote-telegram-control-surface.md`, AC-53.

## Global Constraints

- No remote code path may import or call `save_provider`, `save_provider_visible_models`, `test_provider`, `list_provider_models`, or `delete_provider` (all in `app/api/routes/settings.py`) — proven by a static inspection test, not by convention.
- `count_configured_providers()` calls `app.api.routes.settings.list_providers()` directly (no `Depends`-injected state, matching the two existing departures already documented in `control.py`'s module docstring) and counts `is_configured` — it must never trigger a second call per `/settings` render beyond what that route already does internally (result caching is that route's own concern, already in place for daemon/model-discovery probes).

---

### Task 1: `control.py` — `count_configured_providers`

**Files:**
- Modify: `app/remote/control.py`
- Test: `tests/remote/test_control.py`

**Interfaces:**
- Produces: `async def count_configured_providers() -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/remote/test_control.py`:

```python
@pytest.mark.asyncio
async def test_count_configured_providers_counts_only_configured_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.settings import ProviderInfo, ProvidersListBody

    def _entry(id_: str, *, is_configured: bool) -> ProviderInfo:
        return ProviderInfo(
            id=id_,
            label=id_,
            description="",
            kind="api_key",
            is_configured=is_configured,
        )

    async def _fake_list_providers() -> ProvidersListBody:
        return ProvidersListBody(
            providers=[
                _entry("openai", is_configured=True),
                _entry("anthropic", is_configured=True),
                _entry("mistral", is_configured=False),
            ]
        )

    monkeypatch.setattr(
        "app.api.routes.settings.list_providers", _fake_list_providers
    )

    count = await control.count_configured_providers()

    assert count == 2


@pytest.mark.asyncio
async def test_count_configured_providers_is_zero_with_none_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.settings import ProvidersListBody

    async def _fake_list_providers() -> ProvidersListBody:
        return ProvidersListBody(providers=[])

    monkeypatch.setattr(
        "app.api.routes.settings.list_providers", _fake_list_providers
    )

    count = await control.count_configured_providers()

    assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_control.py -k configured_providers -v`
Expected: FAIL with `AttributeError: module 'app.remote.control' has no attribute 'count_configured_providers'`.

- [ ] **Step 3: Implement**

Add to `control.py`'s `__all__` and body:

```python
async def count_configured_providers() -> int:
    """How many catalog providers currently have usable credentials —
    the one number `/settings` shows for AC-53. Calls the same route
    function the desktop Settings screen uses (see this module's
    docstring for why app/remote/ makes this exception) rather than
    reimplementing the static-credential/daemon-reachability checks
    GET /api/settings/providers already performs."""
    from app.api.routes.settings import list_providers

    result = await list_providers()
    return sum(1 for provider in result.providers if provider.is_configured)
```

And extend the module docstring's exception list with this third departure, and add `"count_configured_providers"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/remote/test_control.py -v`
Expected: PASS, all tests in the file green.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/control.py tests/remote/test_control.py && uv run ty check app/remote/control.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/control.py tests/remote/test_control.py
git commit -m "feat(remote): count configured providers for /settings (AC-53)"
```

---

### Task 2: `render_settings_card` gains the Providers line

**Files:**
- Modify: `app/remote/formatting.py`
- Test: `tests/remote/test_formatting.py`

**Interfaces:**
- Produces: `render_settings_card(..., configured_provider_count: int | None = None)` — when given, adds a `"Providers"` line right after `"Responses"`; `None` omits the line entirely (same optional-section pattern already used for `redaction_policy`/`notify_scope`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/remote/test_formatting.py`:

```python
def test_render_settings_card_shows_configured_provider_count() -> None:
    text, _ = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
        configured_provider_count=3,
    )
    assert "Providers" in text
    assert "3" in text


def test_render_settings_card_omits_providers_line_when_not_supplied() -> None:
    text, _ = formatting.render_settings_card(
        connection_label="evoflux-api",
        model="claude-sonnet-5",
        permission_mode="ask",
        agent_name="evoflux",
        response_mode="summary",
        response_mode_tokens={},
        mode_tokens={},
        agent_tokens={},
        model_tokens={},
    )
    assert "Providers" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_formatting.py -k configured_provider -v`
Expected: FAIL — `test_render_settings_card_shows_configured_provider_count` fails with `TypeError: render_settings_card() got an unexpected keyword argument 'configured_provider_count'`.

- [ ] **Step 3: Implement**

In `app/remote/formatting.py`'s `render_settings_card` signature, add (after `model_tokens`):

```python
    configured_provider_count: int | None = None,
```

and after the existing `"Responses"` line in `lines`:

```python
    if configured_provider_count is not None:
        lines += [
            "",
            f"<b>Providers</b>\n{configured_provider_count} configured",
        ]
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
git commit -m "feat(remote): show configured provider count on the settings card (AC-53)"
```

---

### Task 3: Wire the count into `/settings`

**Files:**
- Modify: `app/remote/actions.py`
- Test: `tests/remote/test_actions.py`

**Interfaces:**
- Consumes: `control.count_configured_providers()` (Task 1), `render_settings_card(..., configured_provider_count=...)` (Task 2).

- [ ] **Step 1: Write the failing test**

Add to `TestSettings` in `tests/remote/test_actions.py`:

```python
    @pytest.mark.asyncio
    async def test_settings_command_shows_configured_provider_count(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test",
                mode="work",
                session_type="main",
                permission_mode="ask",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.id = uuid4()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"
            mock_pairing.response_mode = "summary"

            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.remote.control.count_configured_providers",
                    new=AsyncMock(return_value=2),
                ),
            ):
                settings_action = _make_action(text="/settings")
                await service.dispatch_command(db, settings_action)

            sent_text = adapter.sent_messages[-1].text
            assert "2 configured" in sent_text
```

This needs `from unittest.mock import AsyncMock` — check the top of `tests/remote/test_actions.py`; it already imports `MagicMock, patch` from `unittest.mock`, so add `AsyncMock` to that same import line rather than a second import statement.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/remote/test_actions.py -k configured_provider_count -v`
Expected: FAIL — `"2 configured" not in sent_text` (the settings card is sent without a Providers line at all).

- [ ] **Step 3: Implement**

In `app/remote/actions.py`'s `_cmd_settings`, after the existing `model_tokens = {...}` block and before the `render_settings_card(...)` call:

```python
        configured_provider_count = await control.count_configured_providers()
```

and add `configured_provider_count=configured_provider_count,` as an argument to the `render_settings_card(...)` call (after `model_tokens=model_tokens,`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest --no-cov -q tests/remote/test_actions.py -v`
Expected: PASS, all tests in the file green.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/actions.py tests/remote/test_actions.py && uv run ty check app/remote/actions.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/actions.py tests/remote/test_actions.py
git commit -m "feat(remote): wire the configured-provider count into /settings (AC-53)"
```

---

### Task 4: AC-53 inspection test — providers stay read-only

**Files:**
- Create: `tests/remote/test_ac53_providers_read_only.py`

**Interfaces:**
- Consumes: nothing new — pure static source inspection over the `app/remote/` package.

- [ ] **Step 1: Write the failing test**

```python
"""AC-53 inspection test: no remote code path may reach a credential-
accepting provider endpoint.

A behavioral test could only prove the paths it thinks to exercise; a
static scan proves the *absence* of a reference anywhere in the package,
which is what AC-53 actually promises ("proven by an inspection test
over the remote dispatch surface", not by convention or by enumerating
every possible callback)."""

from __future__ import annotations

import re
from pathlib import Path

_REMOTE_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "app" / "remote"

#: Every provider endpoint in app/api/routes/settings.py that accepts or
#: mutates credentials, visibility, or existence — AC-53's "no remote
#: path reaches PUT .../providers/{id}, POST .../test, or any other
#: credential-accepting endpoint".
_WRITE_CAPABLE_PROVIDER_FUNCTIONS = (
    "save_provider",
    "save_provider_visible_models",
    "test_provider",
    "list_provider_models",
    "delete_provider",
)


def _remote_source_files() -> list[Path]:
    assert _REMOTE_PACKAGE_ROOT.is_dir(), _REMOTE_PACKAGE_ROOT
    return list(_REMOTE_PACKAGE_ROOT.rglob("*.py"))


def test_no_remote_source_file_references_a_write_capable_provider_function() -> None:
    files = _remote_source_files()
    assert len(files) > 10  # sanity: the glob actually found the package

    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name in _WRITE_CAPABLE_PROVIDER_FUNCTIONS:
            if re.search(rf"\b{re.escape(name)}\b", text):
                offenders.append(f"{path.relative_to(_REMOTE_PACKAGE_ROOT)}: {name}")

    assert offenders == []


def test_slash_commands_do_not_include_a_provider_write_command() -> None:
    from app.remote.actions import _SLASH_COMMANDS

    # A future "/providers" command must stay a read-only view — nothing in
    # today's bounded command set (AC-58) implies a write, and this guards
    # against one being added under a name that sounds like a listing.
    assert "provider" not in {cmd.lower() for cmd in _SLASH_COMMANDS}
    assert "providers" not in {cmd.lower() for cmd in _SLASH_COMMANDS}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/remote/test_ac53_providers_read_only.py -v`
Expected: at this point in the plan (after Tasks 1-3 land) both tests should already PASS, since nothing in this plan ever imports a write-capable function. Run it anyway to confirm — this task exists to make that guarantee explicit and permanent, not to fix a violation. If it unexpectedly fails, that is a real finding: something written in Tasks 1-3 imported a write path and must be fixed before proceeding.

- [ ] **Step 3: No implementation step — the test is the deliverable.**

- [ ] **Step 4: Lint and type-check**

Run: `uv run ruff check tests/remote/test_ac53_providers_read_only.py && uv run ty check tests/remote/test_ac53_providers_read_only.py`
Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add tests/remote/test_ac53_providers_read_only.py
git commit -m "test(remote): add the AC-53 provider-read-only inspection test"
```

---

## Final verification (after all four tasks)

- [ ] Run the full test suite: `uv run pytest --no-cov -q`
- [ ] Run `uv run ruff check .`
- [ ] Run `uv run ty check app/`
- [ ] Merge to local `main` following this session's established pattern: check `git status --short` on the main checkout first, fast-forward merge, re-run tests on the merged result, no push.

## Out of scope for this plan

- A `/providers` drill-down listing configured provider names, or per-provider usage (tokens/cost) — the spec's "usage" wording is not built here; see this plan's Scope note.
- Phase 6 — onboarding (AC-54's richer first-run card).
