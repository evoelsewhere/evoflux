# Share browser tool result plumbing without merging trust boundaries

Status: implemented

## Problem and outcome

`browser_use` and `webbridge` intentionally target different browser and trust
boundaries, but independently implement the same multimodal result aggregation
and untrusted-content wrapping rules. The duplication makes security labeling
and mixed text/image behavior easier to drift.

The accepted outcome is one internal helper module used by both tools while
preserving every tool name, JSON schema, action payload, backend, permission,
session-routing, and rendered-result contract.

## Goals

- Centralize untrusted browser-result wrapping.
- Centralize ordered aggregation of text and multimodal browser action results.
- Preserve the backend-specific untrusted notices and action models.
- Pin provider-facing tool definitions to their pre-refactor hashes.
- Add focused unit coverage for the shared helper behavior.

## Non-goals

- Do not merge `browser_use` and `webbridge` into one tool.
- Do not share action models whose payload semantics differ.
- Do not add, remove, rename, or reorder actions.
- Do not change domain, extension, permission, sharing, or session policies.
- Do not change MCP app or attachment propagation behavior in this refactor.

## User flows and states

Normal sessions continue to expose the in-app browser and exclude WebBridge.
WebBridge-tagged sessions continue to expose the user's external browser and
exclude competing browser/web backends. Empty batches, text-only batches,
mixed text/image batches, action errors, screenshots, and untrusted page data
render exactly as before.

## Requirements and acceptance criteria

- **AC-1:** `browser_use` retains definition hash
  `80acd06cc8ca8e003a537ebfe6e12c2815e5fbcdb44af1fbccf3de7b444d51bf`.
- **AC-2:** `webbridge` retains definition hash
  `db5eb677a1e17daed4613edc1661dbf45736e2181837953ceeb83cedbcd4aa2a`.
- **AC-3:** Both backends call the same ordered result-aggregation helper for
  empty, text-only, and mixed multimodal batches.
- **AC-4:** Both backends call the same untrusted-result wrapper while retaining
  their exact existing notice text.
- **AC-5:** Tool names, deferred state, action models, backends, and session
  exclusion policy remain unchanged.
- **AC-6:** Focused browser, WebBridge tool-level, and tier-policy tests pass;
  Ruff, ty, and `git diff --check` pass for affected files.

## API, event, tool, and UI contracts

No public HTTP, SSE, desktop command, provider tool definition, or UI contract
changes. The new module is private backend plumbing. Tool definition hashes are
computed from canonical JSON with sorted keys and compact separators.

## Data model, migration, and retention

Not applicable. No persistence, schema, migration, retention, or artifact-path
change.

## Permissions, security, privacy, and trust

The existing independent browser policies remain authoritative. Shared code is
limited to marking page-derived content as untrusted and combining already
produced results. It does not dispatch actions or make authorization decisions.
The helper deliberately receives the notice string so each backend can preserve
its current threat wording.

## Concurrency, failure, recovery, and idempotency

The helpers are pure and preserve input order. They introduce no I/O, global
state, retry, or concurrency behavior. Exceptions and action-scoped error text
continue to be produced by each backend before aggregation.

## Observability and diagnostics

Existing tool telemetry remains keyed to `browser_use` or `webbridge`. Schema
hash failures identify provider-contract drift during tests. Shared-helper tests
identify ordering, separator, metadata, or trust-label drift directly.

## Compatibility, rollout, and rollback

This is an internal behavior-preserving refactor with no migration. Rollback
inlines the two helpers back into each tool. The independent backend files and
all action models remain intact, keeping rollback low risk.

## Verification matrix

| Acceptance criterion | Implementation owner | Evidence |
|---|---|---|
| AC-1, AC-2 | browser tool definitions | schema digest tests |
| AC-3, AC-4 | `browser_shared.py` and both callers | shared helper plus backend tool tests |
| AC-5 | both tool modules and team tier policy | definition and tier-policy tests |
| AC-6 | affected backend/tests | full browser/WebBridge focused pytest, Ruff, ty, and diff checks |

## Ownership and source map

- `app/agent/tools/builtin/browser_shared.py` — pure shared result helpers.
- `app/agent/tools/builtin/browser_use_tool.py` — in-app browser schemas,
  policy, dispatch, and rendering.
- `app/agent/tools/builtin/webbridge_tool.py` — extension browser schemas,
  dispatch, and rendering.
- `app/agent/mode/team/tier_policy.py` — mutually exclusive browser routing,
  unchanged.
- `tests/agent/tools/test_browser_shared.py` — helper and schema invariants.
- `tests/agent/tools/test_browser_use_tool.py` — in-app behavior.
- `tests/api/test_webbridge.py` — WebBridge tool-level behavior.
