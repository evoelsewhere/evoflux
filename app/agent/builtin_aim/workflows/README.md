# AIM pipeline library (builtin, scope: aim)

Seven stack-agnostic AIM pipelines per `documents/research/aim-framework.md`
§3.11/§4.1 (AIM-4), conforming to the live Workflows v1 schema
(`documents/plans/workflows-feature-plan.md` §4.2) and discovered as a
builtin root by `app/services/workflows_fs.py`:

| Workflow | What it drives |
|---|---|
| `aim-assess` | inventory + wave plan, gated |
| `aim-understand` | one unit → KB doc + candidate rules |
| `aim-design-unit` | mapping → architect approval → designed |
| `aim-convert-unit` | approved mapping → implement in target |
| `aim-convert-wave` | deterministic unit list → batch gate → foreach convert |
| `aim-test-compare` | runners + aim_compare → certify/triage gate |
| `aim-cutover-check` | readiness query → confirm → phase flip |

They run only in `mode="aim"` sessions (scope rule) and, like every
workflow, require manifest approval per content hash before triggering —
the manifest covers the `aim_units` tool calls, agent rosters, and shell
access these pipelines use. Repair loops live *inside* agent turns, never
as graph cycles (Phase 1 DAG rule).
