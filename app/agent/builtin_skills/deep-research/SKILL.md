---
name: deep-research
description: "Use this skill for a thorough multi-source investigation that must end in a cited report: competitive landscapes, technology comparisons across many candidates, market or policy questions where one search is not enough. It scopes a brief, gathers evidence into a durable workspace, and writes one coherent sourced report. Do not use it for a question that one or two searches answer, or for experiments, benchmarks, and metric-driven runs."
---

# Deep Research

Orchestrate parallel research delegated team members, then write one coherent cited report. Research is parallel; writing is single-point — never let multiple agents write report sections.

## Step 0 — Always first

1. Run `date +%Y-%m-%d` via Bash. Never assume the current year from training data.
2. Triage:
   - Answerable with 1-2 searches? → STOP, just use `web_search` directly. Do not use this skill.
   - Enumeration task (N items × M fields, e.g. "compare 20 frameworks")? → still this skill, but use table-oriented decomposition (one delegated team member per item batch).
   - Open-ended investigation? → continue below.
3. Pick depth (default **standard**; user can override with words like "quick"/"exhaustive"):

| Mode | Delegated members (round 1) | Max follow-up rounds | Sources target |
|---|---|---|---|
| quick | 2-3 | 0 | 8+ |
| standard | 3-5 | 1 | 15+ |
| deep | 5-8 | 2 | 25+ |

These are hard budgets. Reflection (Phase 4) can spend them but never exceed them.

## Workspace

All state lives on disk at `./research/<slug>/` — never only in context (survives compaction):

```
research/<slug>/
├── brief.md         # research brief — the single contract for all phases
├── findings/        # F1.md, F2.md ... one per delegated team member, structured evidence
└── REPORT.md        # final deliverable
```

On resume: re-read `brief.md` + list `findings/`, skip completed angles, continue.

## Phase 1 — Scope

Ask at most one round of clarifying questions (`ask_user`), only if genuinely ambiguous: audience, time frame, region, decision at stake. If the user said "just run it" or intent is clear, skip asking and write assumptions into the brief instead.

Then write `brief.md`: refined question, scope boundaries (in/out), assumptions, depth mode, today's date. This brief — not the raw conversation — is what every later phase measures against.

## Phase 2 — Plan

Decompose the brief into 3-8 **independent** research angles. Pull from these lenses as applicable: core facts/definitions · recent developments (last 12 months) · quantitative data/benchmarks · counter-arguments & failure cases · practitioner experience (forums, issues) · academic work · key players/alternatives.

List angles in `brief.md` under `## Angles`. For deep mode or contested topics, show the angle list to the user for a quick confirm before spending budget.

## Phase 3 — Parallel research

Delegate one angle per member with `team_delegate`, dispatching them together so the angles run in parallel. Build each prompt from the locked template in [reference/subagent-prompt.md](reference/subagent-prompt.md) — reproduce it verbatim, replacing only the `{variables}`. Each delegated member:

- researches ONE angle only, using `web_search` and `web_fetch` and the free endpoints in [reference/sources.md](reference/sources.md)
- writes structured findings to `findings/F<n>.md` (claim / quote / URL / date / confidence per item)
- returns only a 3-5 line summary to you — raw page content must never enter your context

If a delegated team member fails or returns thin results, note it and move on; do not block other angles.

## Phase 4 — Reflect (gap check)

Read all `findings/*.md`. Against `brief.md`, ask: which parts of the brief have no evidence? Which major claims rest on a single source? Where do sources conflict?

- Gaps found AND follow-up budget remains → delegate targeted follow-ups with delta-queries (same template, narrower angle). Repeat once per remaining round.
- No budget left or coverage sufficient → proceed. Record unresolved gaps; they go in the report's "Open questions".

## Phase 5 — Write (single-point)

You alone write `REPORT.md` in one pass, following [reference/report.md](reference/report.md). Core rules:

- Every non-obvious claim carries an inline citation `[n]` mapping to a Sources section; citation URLs come only from findings files — never from memory.
- Where sources conflict, present both sides with dates; prefer newer + primary sources.
- Mark single-source claims with `[single source]`, speculation with `[speculative]`.
- End with: Open questions · Sources (numbered, with access date).

For deep mode, before finalizing do one critique pass: reread the report as a skeptical reviewer (unsupported claims? stale data? missing counter-view?) and fix in place.

Finally, give the user a 5-10 line summary of key conclusions and the report path.

## Unattended runs

EvoFlux has no external workflow runner for this pipeline. The on-disk
workspace is what makes a long run resumable: `brief.md`, `findings/F*.md`, and
`REPORT.md` are the checkpoints. On resume, re-read `brief.md`, list
`findings/`, skip the angles already covered, and continue from there.

Resolve every clarifying question with the user before a long unattended run
begins, and fold the answers into the brief — a run that stops halfway to ask
is the failure mode this workspace exists to prevent.
