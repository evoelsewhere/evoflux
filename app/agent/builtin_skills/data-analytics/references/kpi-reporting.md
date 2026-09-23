# KPI Reporting

Turn business or product metrics into decision-ready operating readouts: scorecards, KPI updates, WBR/MBR/QBR, executive summaries. This file owns what is reported, how metrics are interpreted, whether driver context is validated, and the operating takeaway. Metric-system design lives in `references/kpi-design.md`; new driver investigation in `references/metric-diagnostics.md`.

## Contents

- Workflow
- Standards
- Readout formats

## Workflow

1. **Clarify the purpose.** Audience, the conversation the readout supports, what is being reported, the period evaluated, the comparison or target that makes performance interpretable, and the freshness cutoff.
2. **Define the metric framework.** Confirm an existing framework or build one with `references/kpi-design.md`. Lead with the primary KPI, then the smallest set of supporting metrics that explain movement, guard against harmful tradeoffs, or show pacing. When the primary KPI is top-line or composite, define its driver decomposition first (numerator and denominator, volume and rate, mix, funnel stages, segments, cohorts, operational inputs). Use an existing metric tree when available; do not invent a causal hierarchy the definitions do not support.
3. **Lock definitions and sources.** KPI definition, source, window, reporting cutoff, comparison period, target or pacing expectation. Ask before treating an assumed target or pacing basis as authoritative. Make a focused source pass across structured data (actuals, definitions, comparison periods), dashboards, docs, and team communication (context and source-of-truth guidance) before drafting; do not assume from a sparse prompt that actuals are unavailable. When a definition changed, show restated history or call out the break. Check source trust with `references/data-quality.md` when quality issues could change the numbers.
4. **Pull topline actuals.** Never draft a readout from placeholders. If actuals are blocked, stop and say what source or access is needed, unless the user asked for a template or mockup. For each headline KPI give current value, absolute and relative change versus comparison, and a short interpretation. Flag anything that breaks comparability first: tracking change, backfill, partial outage, missing day.
5. **Put numbers in context.** Compare against the defined target, plan, pacing model, benchmark, historical range, or peer group. For deadline goals, show whether the metric is on pace to hit the target by period end, using the provided pacing definition; if none exists, ask, or state that a calculated fallback was used and how. Show absolute and percent variance to target and a red/yellow/green status when useful, naming its basis.
6. **Explain validated drivers.** A plausible story is not enough. Use `references/metric-diagnostics.md` to identify and validate drivers, or reuse trusted prior analysis that already validates them.
7. **Add business context and implications.** Let driver findings guide the context search (`references/business-context.md`), and link context to the metric only when timing, population, and measured change support it. State whether the movement is concerning, whether the KPI is on track, at risk, or ahead, and the warranted action — or the next validation step when evidence does not support action.
8. **Validate.** Run `references/pre-share-review.md` on numbers, methodology, caveats, and the claimed status, drivers, and implications. Fix material issues; carry remaining limitations into the readout.
9. **Deliver.** A quick status update or findings-in-chat request is an inline answer. Otherwise produce the readout as a report (`references/deliverables.md`) using the matching format below, passing: headline status and implication; actuals, targets, pacing basis, comparison periods; validated drivers and unresolved uncertainty; audience, cadence, and destination; charts that would clarify it. For slides or decks, build the portable source report first, then read the `pptx-official` skill to create and verify the deck from the same evidence.

## Standards

**Metrics**
- Never present a KPI as precise when its definition, source, window, or comparison is unclear.
- Make calculation logic, inclusion and exclusion rules, grain, and time treatment explicit when they affect interpretation.
- Reconcile totals and compare against prior reporting when possible. Do not compare periods, cuts, or targets that are not definitionally compatible; call out definition changes, backfills, denominator shifts, and calendar effects.

**Status and pacing**
- Include headline takeaway, actual, comparison, target or pacing, driver summary, and implication unless a narrower readout is requested.
- Put actuals next to their target or baseline.
- Keep recurring sections consistent across runs; explain any omitted section briefly.
- Use traffic-light status only when it helps prioritize; pair color with text and state the basis.

**Drivers**
- Quantify drivers; prose is not a substitute for sizing.
- For top-line movement, show a compact decomposition: top-line actual, component drivers, largest contributors or non-drivers, residual or unresolved movement. Use an additive bridge only when components reconcile.
- Separate validated drivers from context and hypotheses; do not elevate business events into causes without supporting timing, population, and measured change.
- State whether movement is broad-based or concentrated when it changes the implication; name unresolved uncertainty instead of inventing an explanation.

**Presentation**
- Lead with the answer, then evidence; write for skimmers.
- Use compact business-readable numbers such as `123k (+8% w/w, +19% m/m)`; round consistently and label units.
- Replace adjectives like "strong", "healthy", "soft" with the evidence that justifies them.
- Keep caveats next to the claim they affect; drop caveats that do not change interpretation.

## Readout formats

Starting patterns, applied after the analysis and validation are complete:

- **Inline written update** (chat, email, memo): answer first, then headline actuals, comparison or pacing, main drivers, and the implication or next step.
- **Document or report:** summary, KPI snapshot, driver analysis, business context, implications, caveats, and reader-relevant source and calculation notes.
- **Single slide:** one main message, a compact view of headline metrics, and only the driver, risk, or action detail that supports it. Ask whether the user wants a report/HTML or a slide file when unclear.
- **Executive business review deck:** concise executive summary (status, what changed, what needs attention); KPI cards or a scorecard; body sections organized around the main performance drivers, each linking evidence to the operating takeaway and action; dense tables and deeper cuts in an appendix; prior follow-ups with owner and status for recurring reviews; closing prioritized actions or open questions.
- **Scorecard or KPI card:** for comparing many KPIs at once — actual, comparison, target or pacing, status, and a short driver note per row; expand below the table when a driver story needs room.
