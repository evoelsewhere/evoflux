---
name: oad/debug
description: EvoFlux workflow for investigating bugs, regressions, sessions, and runtime issues.
---

Debug the reported issue.

Workflow:

1. **Triage the report**
   - Extract the symptom, expected behavior, reproduction steps, affected surface (backend/frontend/desktop/agent/provider), session id, workspace, model, logs, and timing clues.
   - If the report is ambiguous, inspect available evidence first; ask only when a missing decision blocks safe progress.

2. **Choose the fastest evidence path**
   - **Live session / agent behavior:** use the API endpoints directly or the test suite:
     ```bash
     uv run pytest tests/agent/mode/team/ -q
     ```
   - **Backend/API issue:** hit the smallest route/service path, inspect logs, then add/adjust pytest coverage.
   - **Frontend issue:** inspect relevant components/hooks/stores, run focused `bun` checks/tests, and use existing UI state patterns.
   - **Desktop/CLI/provider issue:** inspect the specific command/provider path and environment assumptions.

3. **Reproduce narrowly**
   - Recreate the smallest scenario that demonstrates the bug.
   - Match the user's mode/workspace/model/message sequence when relevant.
   - Capture durable evidence: raw HTTP response, persisted history, SSE events, logs, failing test output, or UI state.

4. **Diagnose from code and evidence**
   - Search for existing patterns before editing.
   - Identify the boundary that failed: route validation, persistence, queueing, stream emission, agent loop, hook, tool, provider, frontend store, or renderer.
   - Preserve unrelated work; do not reset or overwrite changes you did not make.

5. **Fix surgically**
   - Make the smallest change that addresses the proven root cause.
   - Add or update focused regression coverage at the closest layer.
   - Update related docs only when behavior, API contract, or operator workflow changed.

6. **Verify and report**
   - Re-run the reproduction and the focused tests/checks for touched areas.
   - If feasible, run the repository's standard lint/type/test commands for the changed surface.
   - Report root cause, changed files, checks run with results, and any remaining risk or unverified area.
