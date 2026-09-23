# Pre-Share Review

QA an analysis before it is shared or used for a decision: question, data, methodology, calculations, visuals, claims, caveats, and recommendations. This is QA of the analysis; when trust depends on the underlying data (freshness, grain, duplicates, join coverage, source mismatch), run the checks in `references/data-quality.md` as a companion.

## Contents

- Stance
- Workflow
- Common pitfalls
- Spot-check recipes
- Visualization checks
- Confidence ratings
- Validation report

## Stance

- Validate the claims the analysis makes, not whether it looks polished.
- Prefer concrete evidence: recompute, inspect source data, trace records, reconcile against trusted sources.
- Label anything that cannot be verified and say what would verify it.
- Treat surprising results, causal claims, high-impact decisions, and externally shared work as higher risk.
- Select checks that fit the artifact; do not run every check mechanically.

## Workflow

1. **Inventory the artifact and claims.** Identify what is being validated (report, notebook, spreadsheet, SQL, dashboard, chart, pasted analysis) and open referenced artifacts. Extract the question, audience, decision, key claims, headline numbers, sources, windows, populations, filters, baselines, and stated caveats. Confirm every metric the user requested appears or is explicitly marked unavailable or out of scope.
2. **Methodology and assumptions.** The analysis answers the stated question, not an easier nearby one. Population, eligibility, exclusions, sampling, definitions, formulas, units, denominators, timezones, cohorts, and baselines match the decision. Flag hidden exclusions, inconsistent definitions, partial-period comparisons, and causal wording without experimental or otherwise credible causal evidence.
3. **Data selection.** Sources are appropriate and current enough; the "as of" date is stated or recoverable; no unexpected missing partitions, segments, or categories; nulls, deduplication, and filters do not silently exclude the population of interest; joins do not drop or multiply rows.
4. **Calculations.** Recompute the highest-impact numbers independently. Check grain, subtotals, non-zero denominators, rate bases, period-over-period bases, weighted averages, units, currency, timezone, and that mutually exclusive categories sum to totals. For SQL, inspect join types, group-by grain, filters, distinct counts, and row counts before and after joins. Use a notebook or spreadsheet formulas for reproducible spot checks.
5. **Reasonableness.** Compare magnitudes with known dashboards, prior reports, finance sources, or expected scale. Investigate jumps, drops, flatlines, exact round numbers, 0% or 100% rates, shares that should sum to about 100%, results that confirm the hypothesis without friction, and edge cases (empty segments, new entities, boundary dates).
6. **Visuals and rendered output.** Apply the visualization checks below. For rendered reports, dashboards, slides, PDFs, or HTML, inspect the final output for broken charts, missing tables, clipped text, stale placeholders, and layout problems.
7. **Narrative and conclusions.** Every conclusion has visible evidence. Verified findings are separated from interpretation and open questions. Note alternative explanations and recommendations that exceed the evidence.
8. **Confidence and required fixes.** Prioritize issues by decision impact. Block sharing when a number, denominator, join, window, population, comparison, or conclusion is materially unreliable; do not block for polish. List handoff blockers separately from caveats: missing access, unavailable artifacts, unrun checks, broken render steps, unresolved data-quality risks, absent owner confirmation. Record the notebook path, query, spreadsheet tab, or dashboard link used so the check is reproducible.

## Common pitfalls

- **Join explosion:** many-to-many joins inflate counts and sums. Compare row counts and distinct primary entities before and after; aggregate the right-hand table to the intended grain first; use `COUNT(DISTINCT primary_id)` through joins; comment intentional one-to-many joins.
- **Survivorship bias:** only entities that exist today are included; deleted, churned, or failed ones are missing. Ask who is not in the dataset.
- **Incomplete period comparison:** partial vs complete period. Use complete periods, equal elapsed days, or a prominent caveat.
- **Denominator shifting:** the eligible population changes between periods or segments; keep conversion, churn, activation, and retention definitions stable.
- **Average of averages:** aggregate from raw numerators and denominators or weight by group size.
- **Timezone mismatch:** different timestamp conventions or daily cutoffs across sources.
- **Selection bias in segmentation:** segments defined by the outcome being measured; define comparison groups by pre-treatment characteristics for lift or causal claims.
- **Other traps:** Simpson's paradox, correlation presented as causation, small samples, outlier-dominated means, multiple testing, cherry-picked ranges, look-ahead bias.

## Spot-check recipes

- Recompute a key metric from raw numerator and denominator.
- Trace a few records through joins, filters, and final output.
- Reconcile a key total against a trusted dashboard, prior report, or finance source.
- Reverse-engineer a headline number from components (users x revenue per user).
- Run a one-day, one-segment, or one-entity boundary check.
- Compute the same metric through an alternate query path when a claim is surprising or high stakes.

## Visualization checks

- Bar charts start at zero; waterfall, bridge, and variance charts may use a narrowed axis when exact values, units, and the focused scale are clear.
- Comparison charts share scales unless the difference is explicit and justified.
- Axes, units, legends, and date ranges are labeled; ordering matches the intended comparison.
- Truncated axes, dual axes, 3D effects, and inconsistent intervals are justified or redesigned.
- Titles state the finding the data supports, with scope or date range when needed; caveats sit near the claims they qualify.
- Precision and units are appropriate; rendered artifacts are checked in final form.

## Confidence ratings

- **Ready to share:** methodologically sound, key calculations verified or low risk, caveats clear.
- **Share with caveats:** directionally usable; specific assumptions, limits, or unverified checks must be communicated.
- **Needs revision:** material errors, unsupported claims, missing checks, or methodological problems.

## Validation report

Use this structure unless the user wants a lighter review:

```markdown
## Validation Report

### Overall Assessment: [Ready to share | Share with caveats | Needs revision]

### Methodology Review
[Question framing, data selection, population, definitions, comparisons, assumptions.]

### Issues Found
1. [Severity: High/Medium/Low] [Issue, evidence, impact]

### Calculation Spot-Checks
- [Metric or claim]: [Verified / Discrepancy found / Not verified] - [brief evidence]

### Visualization Review
[Chart or presentation issues, if applicable.]

### Handoff Blockers
- [Missing access, unrun check, broken render step, ...]

### Suggested Improvements
1. [Improvement and why it matters]

### Required Caveats for Stakeholders
- [Caveat that must be communicated]
```

Preserve the original artifact's source references (links, query IDs, notebook paths, spreadsheet tabs, dashboard URLs). Confirm every section the user requested or the format implies is present, or explain why it is omitted.
