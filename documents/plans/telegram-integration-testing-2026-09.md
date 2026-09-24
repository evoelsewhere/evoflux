# Telegram Integration — Testing & Fixes (2026-09-17)

Status: **Bugs fixed, awaiting restart** — code changes applied, backend not yet restarted

## Live test results (WebBridge, web.telegram.org)

### End-to-end test matrix

| # | Test | Status | Notes |
|---|---|---|---|
| 1 | Bot receives message | PASS | All messages delivered within seconds |
| 2 | Agent generates response | PASS | Correct answers for factual queries (2+2=4) |
| 3 | Done card sent back | PASS | Shows title, elapsed time, tool count |
| 4 | `/actions` command | PASS | Shows workflows and projects with buttons |
| 5 | `/history` command | PASS | Shows recent sessions |
| 6 | `/new` command | PASS | Creates new task |
| 7 | `/status` command | PASS | Shows connection status, paired device |
| 8 | Button callbacks | PASS | Project/workflow selection works |
| 9 | HTML formatting | PASS | Tables, bold, links, code render correctly |
| 10 | Rich content responses | PASS | Multi-paragraph Vietnamese/English responses with tables |
| 11 | Tool call counting | PASS | Correctly shows 0, 3, 7 tool calls |
| 12 | Tool log content | **FAIL** | Shows "unknown: {}" for every tool call |
| 13 | Model name in footer | **FAIL** | No model name shown on any card |
| 14 | Token counts in footer | **FAIL** | No input/output tokens shown |
| 15 | Cached tokens in footer | **FAIL** | No cached token count shown |
| 16 | Cost in footer | **FAIL** | No USD cost shown |
| 17 | Context window in footer | **FAIL** | No context window size shown |
| 18 | Error card formatting | **FAIL** | Raw HTTP 400 dump instead of user-friendly message |

### What's working (8/18 pass)

- Message send/receive flow
- Agent response generation
- Done card with title, elapsed time, tool count
- Slash commands (`/actions`, `/history`, `/new`, `/status`)
- Button callbacks (project, workflow selection)
- HTML rendering (tables, bold, links, code)
- Rich multilingual responses (Vietnamese with tables)
- Tool call counting accuracy

### What's broken (6/18 fail — data pipeline bugs)

#### Bug 1: Tool log shows "unknown: {}" for every tool call

**Evidence:** Every Tool log button returns entries like:
```
unknown: {}
unknown: {}
```
instead of `read: {"path": "file.py"}` or `webbridge: {"actions": [...]}`.

**Root cause:** `app/remote/turn_activity.py:74-77` reads tool calls with
`call.get("name")` and `call.get("arguments")`, but the agent loop stores
tool calls in OpenAI's nested format:
`{"function": {"name": "...", "arguments": "..."}, "id": "...", "type": "function"}`.

**Fix applied:** Check `call.get("function")` dict first, fall back to flat format.

**File:** `app/remote/turn_activity.py` (lines 74-82)

---

#### Bug 2: Cost never displayed — dict vs scalar type mismatch

**Evidence:** No done card shows cost. `_TurnDeliveryState.usage_cost_usd`
is always `None`.

**Root cause:** `app/remote/outbound.py` checked
`isinstance(cost, (int, float))` but `UsageEvent.cost` is `dict[str, float]`
(e.g. `{"input": 0.001, "output": 0.002}`). The dict never matched.

**Fix applied:** Check `isinstance(cost, dict)` first, sum values. Keep scalar
fallback.

**File:** `app/remote/outbound.py` (line 795)

---

#### Bug 3: Model name never displayed — wrong field lookup

**Evidence:** No done card shows model name. `usage_model` is always `None`.

**Root cause:** `UsageEvent` has no top-level `model` field. The publisher
stores model IDs in `metadata.models` (a list). Old code tried
`data.get("model")` and `data.get("metadata", {}).get("model")` — both `None`.

**Fix applied:** Extract model from `metadata.models` list via
`_pick_primary_model()` (returns last entry, which is the primary model).

**File:** `app/remote/outbound.py` (line 777)

---

#### Bug 4: Error card dumps raw HTTP details

**Evidence:** Model-unavailable error showed:
```
Lead agent 'evoflux' failed: opencode:deepseek-v4-flash-free rejected the request (HTTP 400): Error from provider (Console): Upstream request failed: Model is unavailable.
```

**Fix applied:** `_sanitize_error_message()` in formatting.py detects
"model is unavailable" / "rejected the request" patterns and shows:
```
Model opencode:deepseek-v4-flash-free is currently unavailable.
Check your provider dashboard or try a different model.
```

**File:** `app/remote/formatting.py` (line 271)

---

### Features added (not bugs, but missing)

#### Context window info in usage footer

**Before:** Only elapsed time and tool count shown.
**After:** Done card shows:
```
📊 gpt-4o · 128K ctx · 1,234 → 567 tok · 890 cached · $0.0050
```

**Implementation:**
- `_TurnDeliveryState` gains `usage_context_window: int | None`
- `_handle_usage` looks up `get_model_limits(model).context_length`
- `render_done_card` gains `context_window` param
- New `_format_token_count()` helper: 128000→"128K", 1000000→"1M"

**Files:** `app/remote/outbound.py`, `app/remote/formatting.py`

---

### Pre-existing issues (not caused by this work)

| Issue | Location | Notes |
|---|---|---|
| Test failure: undefined `status` | `tests/remote/telegram/test_adapter.py:987` | Pre-existing |
| Ruff format: `gates.py` | `app/remote/gates.py` | Pre-existing |

---

## Files changed

| File | Change |
|---|---|
| `app/remote/turn_activity.py` | Fix tool_calls key path for OpenAI nested format |
| `app/remote/outbound.py` | Fix cost dict handling, model extraction, add context_window |
| `app/remote/formatting.py` | Add context_window, _format_token_count, _sanitize_error_message |
| `documents/plans/telegram-integration-testing-2026-09.md` | This document |

## Verification

- **116 tests pass** across `test_formatting.py`, `test_outbound.py`,
  `test_turn_activity.py`, `test_live_activity.py`
- **Ruff check/format clean** on all modified files
- **Python smoke tests** verify nested/flat tool call parsing, cost dict
  summing, model extraction, token count formatting

## Next steps

1. Restart backend to pick up code changes
2. Send test message via Telegram and verify usage footer appears
3. Click Tool log and verify tool names are resolved
4. Trigger a model error and verify user-friendly error message
5. Log `test_actions.py` failures as separate pre-existing issue
