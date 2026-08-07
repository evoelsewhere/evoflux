---
name: work-router
description: Use this skill to route substantial knowledge-work requests to the smallest appropriate work specialist. Apply it when the user needs analysis, a decision, an executable plan, source-backed research, or publication-ready professional writing; skip it for casual conversation, simple lookup, or direct file formatting handled by a format-specific skill.
---

# Route knowledge work

Identify the decision or deliverable the user needs, then activate the smallest
specialist set that materially improves it.

## Routing procedure

1. Determine whether the requested output is evidence, a recommendation, an
   execution system, new external knowledge, or finished prose.
2. Select one primary specialist:
   - `work-data-analysis` for calculations, data quality, KPIs, experiments,
     segmentation, forecasting, or anomalies.
   - `work-decision` for choosing among viable options under constraints and
     tradeoffs.
   - `work-planning` for milestones, owners, dependencies, sequencing, risks,
     and verification gates.
   - `work-research` for claims that require gathering and reconciling sources
     beyond the current conversation.
   - `work-writing` for a publication-ready memo, brief, proposal, report,
     email, announcement, or policy.
3. Add a second specialist only when it owns a distinct stage. Research may
   feed a decision; analysis may feed a plan; writing may package an already
   established conclusion.
4. Do not activate writing merely because every answer contains prose, or
   research merely because a quick lookup is useful.
5. Select file-format or presentation skills separately when the deliverable
   itself requires them; this router governs reasoning workflow, not file
   mechanics.

Read [references/routing-matrix.md](references/routing-matrix.md) when the user
asks for several deliverables, the evidence source is ambiguous, or multiple
specialists appear equally plausible.

## Guardrails

- Route from the user's outcome, audience, and evidence gap.
- Prefer one primary specialist and a clear sequence over parallel context.
- Preserve uncertainty and never fabricate owners, dates, sources, or data.
- Continue without a specialist when the task is simple enough that loading
  one would only add ceremony.
