---
name: coding-investigate
description: Use this skill to understand or diagnose existing code when no change has been decided yet — trace an exact symbol's definition, callers, callees, references, impact, and cross-repository wiring; reproduce and isolate the unknown cause of a failing test, build, runtime path, integration, or race; or reproduce a browser-observable defect live through console, DOM, and network inspection. Do not use it once the cause and contract are already known and only the edit remains, or to audit a diff someone already wrote.
---

# Investigate code behavior

This skill owns the read-first posture: establish what the code actually does,
or why it actually failed, before anything is changed. It routes to one focused
workflow; the workflow body is the authoritative contract for that work.

## Route the request

Pick the narrowest match, then read that workflow file completely before
acting. Do not read a workflow you did not select.

| Evidence in the request | Workflow |
| --- | --- |
| Unfamiliar behavior, ownership, wiring, configuration, or an exact-symbol relationship question, with no reported failure | `references/workflows/investigate.md` |
| A test, build, runtime path, integration, or concurrent workflow fails and the responsible condition is unknown | `references/workflows/debug.md` |
| The symptom is only observable in a browser — UI defect, console error, failed network call, or visual regression | `references/workflows/browser-verify.md` |

Read a workflow with `skill(action="read_resource")` using the path exactly as
written above; resource paths are relative to this skill directory.

`browser-verify.md` additionally requires a live browser tool. If none is
granted in this session, say so and route to `debug.md` instead of simulating
browser evidence.

Routing notes that decide close cases:

- A failure symptom outranks curiosity. "Explain how X works" is investigation;
  "X is broken, find out why" is debugging even when both need the same trace.
- Browser-verify is chosen by *where the symptom is observable*, not by the
  language of the fix. A Python worker crash is ordinary debugging even when a
  browser triggered it; a silent button with a console error is browser-verify
  even when the bug lives in backend code.
- Debugging may fix and prove its own root cause when the user authorized a
  fix. It does not hand off for that.

## Shared discipline

`references/code-context-contract.md` is the indexed-code contract for every
workflow here. Read it only on ambiguity, truncation, stale index data,
cross-repository edges, or dynamic wiring — not preemptively.

Every workflow in this skill shares these limits:

- Use `code_context`, `read`, `grep`, and `glob` for source discovery. Do not
  use shell `cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find` to reread source
  or bypass an observation receipt.
- Reserve shell for repository-native test, build, lint, diagnostics, and
  runtime commands.
- Reuse a revision-aware covered-range receipt instead of reading again.
- Do not mutate code under `investigate.md`. Under `debug.md` and
  `browser-verify.md`, edit only after the cause is named and only when the
  request authorized a fix.

## Do not use this skill for

- Implementing a decided change, refactoring, or staging a migration — use
  `coding-change`.
- Auditing an existing diff, designing tests, or a security review — use
  `coding-verify`.
- Measured performance work or telemetry design — use `coding-operate`.
- Building new UI from scratch.
