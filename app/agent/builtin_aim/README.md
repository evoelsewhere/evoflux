# AIM built-in workflows (AIM-0 → AIM-4)

Bundled AIM content, per `documents/research/aim-framework.md` in the EvoFlux repo:

- `workflows/` — ten stack-agnostic AIM pipeline definitions (§3.11, see `workflows/README.md`).
- `seed/aim-kb-template/rulebook/` — a safe sample copied into each new KB.

Stack and engagement policy belongs only to `<kb>/rulebook/`. Builtin AIM code
never selects, installs, merges, or falls back to a global rulebook.

## Status

**Workflow wiring is complete; project rulebook maturity varies by capability.** All
pipelines run as real Workflows (POST `/api/workflows/{name}/run` against an
`aim`-mode session), but each project's local manifest declares each stage as
`ready`, `template`, or `unavailable`. A wired workflow is not evidence that a
project has production runners, mappings, or cutover automation.

| AIM milestone | Description |
|---|---|
| AIM-0 | Project rulebook template + KB layout + builtin agents |
| AIM-1 | `aim_units` / `aim_compare` tools + KB-local rulebook resolution |
| AIM-2 | `aim` mode shell (sidebar → project → features) |
| AIM-3 | Overview board, KB browser, Runs & Reports, post-run Discussion |
| AIM-4 | Pipelines wired to real Workflows engine; Gate panel for in-flight gates |
| AIM-5 | Dependency-aware suggested workflow board with live readiness and audited snapshots |
