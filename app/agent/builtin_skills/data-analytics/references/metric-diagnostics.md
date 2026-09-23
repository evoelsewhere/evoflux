# Metric Diagnostics

Explain why a metric changed, missed a target, spiked, or disagrees with another number. Reproduce the metric, define the comparison, quantify the movement, validate drivers, and state what is verified, likely, unresolved, and worth doing next.

## Contents

- 1. Define the diagnostic question
- 2. Validate the metric definition and source
- 3. Establish the pattern
- 4. Choose the diagnostic plan
- 5. Decompose and validate drivers
- 6. State implications and hand off

## 1. Define the diagnostic question

Pin down:

- what the metric means in business terms;
- the time window and comparison that make the change measurable;
- the population and grain that determine what counts;
- the source that owns the metric definition;
- the question type: movement, concentration, incident, or reconciliation.

When the metric meaning, ownership, recent changes, or plausible explanations are unclear, gather context first with `references/business-context.md`.

## 2. Validate the metric definition and source

Confirm definition, grain, aggregation, filters, joins, exclusions, freshness, lineage, and any disagreement between trusted surfaces. Keep this focused on issues that could change the answer.

- Treat named semantic layers and familiar tables as candidates, not the selection. For broad metric questions, run live discovery before choosing the controlling source.
- When both exist, inspect at least one business-facing surface (dashboard, metric doc) and one lower-level source (table, event log), then state why the selected source owns the answer.
- If freshness, grain, joins, missingness, schema drift, outliers, or distribution shifts could affect trust, run the relevant checks from `references/data-quality.md`.
- When the work needs fresh SQL/Python, modeling, or multi-step decomposition, keep it in a notebook (`references/notebooks.md`).

## 3. Establish the pattern

Quantify the metric over the relevant period and scope, and reproduce any comparison the question makes. Do not search for causes until size, timing, and scope are verified or explicitly marked uncertain.

## 4. Choose the diagnostic plan

Pick the smallest set of cuts likely to explain the pattern. Choose driver dimensions from the metric's operating logic and what the business monitors or can act on, not every available field.

On a lower-level table, do not limit drivers to the fields the first query returned. Recreate or join the business grouping the question needs (product family, segment, region, cohort, customer hierarchy). If the grouping cannot be reconstructed, say so before simplifying.

| Question type | Plan |
|---|---|
| Metric change | Compare focal window to baseline, rank segment contributions, check peer/historical context, test mix shift vs within-segment movement. |
| Spike, regression, incident | Pin onset, peak, recovery; look at distribution shape, not only averages; find affected slices; decide broad vs localized; check whether traffic or failure behavior changed. |
| Largest contributors, concentration | Define "largest", rank entities, compare share of total and change, look for major movers, entrants, exits. |
| Reconciliation, difference | Align definitions, filters, grain, numerator, denominator, exclusions; quantify the components of the gap and state the residual. |

## 5. Decompose and validate drivers

Size each major driver with the strongest available evidence: whether it explains the pattern, its size relative to the base or gap, whether it is broad or concentrated, and whether it holds under the right comparison. Follow promising cross-cuts; stop when more cuts are unlikely to change the conclusion or confidence.

- Express drivers against the relevant base, comparison, or share of total.
- For rates, check whether the numerator, denominator, or both moved.
- For additive metrics, compute contribution share when it sharpens the story.
- Separate composition (mix) effects from within-segment performance when that changes the explanation.
- Prefer mutually exclusive driver buckets; reconcile the decomposition exactly or size and explain the residual.
- Treat measurement as a candidate cause: logging changes, incomplete recent data, duplicated rows, or a shifted denominator can produce the pattern without any business change.
- Use context to say whether the pattern is ordinary, unusual, expected, or tied to a known change.

Add a chart when it makes the claim easier to verify (`references/visualization.md`).

## 6. State implications and hand off

Lead with the answer, then:

- the pattern being explained;
- the strongest driver explanation and its evidence;
- why it matters for the business;
- confidence in the explanation;
- the implication, next action, or follow-up that matters most.

Keep implications visibly separate from verified facts. Do not claim causality from timing alone; label plausible hypotheses as such. If the user needs a recommendation or tradeoff decision, continue with `references/decision-analysis.md`.

Before handing off, confirm the analysis contains the headline movement, driver contribution shares or effect sizes, source and window reconciliation, the executed SQL or query references, and caveats that would change interpretation. For stakeholder-facing conclusions, run `references/pre-share-review.md`.

Package the result as a report (`references/deliverables.md`) unless the user asked for an inline or chat-only answer, asked for no file, or chose another artifact. A direct diagnostic question is not by itself a request for an inline answer.
