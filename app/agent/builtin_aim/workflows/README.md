# AIM pipeline library (builtin, scope: aim)

Ten stack-agnostic AIM pipelines per `documents/research/aim-framework.md`
§3.11/§4.1 (AIM-4), conforming to the live Workflows v1 schema
(`documents/plans/workflows-feature-plan.md` §4.2) and discovered as a
builtin root by `app/services/workflows_fs.py`:

| Workflow | What it drives |
|---|---|
| `aim-assess` | inventory + wave plan, gated, then optional suggestion plan |
| `aim-suggest-workflow` | dependency-aware next-action board snapshot; no phase transitions |
| `aim-understand` | selected unit + unresolved dependency closure → docs + candidate rules |
| `aim-review-rules` | candidate rules → human confirmation or explicit no-rules evidence |
| `aim-design-unit` | mapping → architect approval → designed |
| `aim-convert-unit` | approved mapping → implement in target |
| `aim-convert-wave` | deterministic unit list → batch gate → foreach convert |
| `aim-capture-golden` | inspect + approve → capture trusted legacy expected output |
| `aim-test-compare` | runners + aim_compare → certify/triage gate |
| `aim-cutover-check` | readiness query → confirm → phase flip |

They run only in `mode="aim"` sessions (scope rule) and, like every
workflow, require manifest approval per content hash before triggering —
the manifest covers the `aim_units` tool calls, agent rosters, and shell
access these pipelines use. Repair loops live *inside* agent turns, never
as graph cycles (Phase 1 DAG rule).

Workflow outputs use `readiness_status` only for the preflight result. Outcome
fields are explicit (`decision`, `verdict`, evidence paths, and processed counts),
and branch-specific fields are omitted when that branch did not execute.
