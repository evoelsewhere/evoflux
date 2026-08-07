---
name: work-data-analysis
description: Use this skill to turn tabular, experimental, operational, or business data into reproducible findings for a concrete decision. Apply it to KPI definitions, trends, segmentation, experiments, forecasts, reconciliations, anomalies, and data-quality investigations; do not use it for spreadsheet formatting alone, external fact research, or building an unrelated data pipeline.
---

# Analyze work data

Anchor analysis to a decision and make every material transformation
reproducible. A polished chart cannot rescue an undefined population or broken
join.

## Frame the analysis

1. Define the decision, audience, population, unit of analysis, time window,
   comparison, metrics, and required deliverable.
2. Distinguish metric definitions supplied by the user from definitions you
   infer. Surface decisions about cohort, attribution, time zone, currency,
   units, denominator, and exclusions.
3. Record data provenance and freshness before calculating.

## Audit before interpreting

Inspect schema, types, keys, cardinality, duplicates, missingness, coverage,
units, time zones, impossible values, and join behavior. Reconcile headline
counts or totals to a trusted baseline when one exists.

Read [references/data-quality-gates.md](references/data-quality-gates.md) when
joining sources, excluding rows, treating outliers, analyzing experiments,
forecasting, or resolving a mismatch with a reported metric.

Never silently coerce invalid values, drop duplicates, discard outliers,
impute missing fields, or switch denominators. Preserve a compact audit trail
of each consequential transformation.

## Analyze proportionately

Start with counts, distributions, and denominators. Segment only where it can
change the decision. Quantify uncertainty and test alternative reasonable
definitions that could reverse the conclusion.

For experiments, check assignment, sample ratio, exposure, pre-period balance,
multiple comparisons, and practical—not only statistical—significance. For
forecasts, separate observed inputs, model assumptions, scenarios, and error
range. Do not imply causation from observational correlation.

## Produce the artifact

Create the smallest table or visualization that makes the decision-relevant
relationship clear. Keep calculations reproducible in formulas, queries, or
code and preserve source data unless transformation is explicitly requested.
Protect row-level personal or confidential data in outputs.

## Deliverable

Lead with the direct finding and its decision implication. Include metric
definitions, data-quality exceptions, magnitude and uncertainty, sensitivity
results, reproducibility location, and the next measurement or action.
Distinguish observed, estimated, forecast, and imputed values.
