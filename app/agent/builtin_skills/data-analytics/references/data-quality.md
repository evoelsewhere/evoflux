# Data Quality Assessment

Decide whether a dataset, query result, dashboard, or source is trustworthy enough for its intended use (analysis, modeling, dashboards, experiments, pipelines). Start with the intended use and grain, run the highest-value checks for the data shape, and report concrete evidence, risk, likely cause, and the smallest useful remediation.

Use this file to investigate the underlying data. To QA a finished analysis, chart, or recommendation, use `references/pre-share-review.md`. To define a metric going forward, use `references/kpi-design.md`.

## Contents

- Workflow
- Core checks
- Shape-specific checks
- Temporal and distribution checks
- Severity
- Automated tests
- Output

## Workflow

1. **Clarify the quality question.** What the dataset represents, intended unit of analysis, downstream use, raw-ingestion vs transformed-model quality, and the comparison baseline (prior weeks, prior schema, trusted reference table). Identify expected grain, primary or candidate keys, important date columns, timezone, domain rules, allowed values, and business thresholds. Infer cautiously and label assumptions.
2. **Choose an inspectable path.** When checks need SQL or Python, default to a companion notebook (`references/notebooks.md`). For queryable tables, confirm schema, grain, sample rows, and query rules before heavier checks. Use pipeline or operations logs for freshness and lineage when they matter.
3. **Build a compact profile.** Row and column counts, names and types, candidate keys, duplicate rates on likely identifiers, min/max of date columns, null rates, distinct counts for categoricals, numeric summaries for measures. Confirm grain before interpreting anomalies: many apparent problems are mixed grain, partial backfills, late-arriving data, or duplicated joins.
4. **Run core checks** (below), comparing rates rather than counts and segmenting by time, source, country, platform, or version to separate real issues from expected variation.
5. **Run shape-specific and temporal checks** (below).
6. **Tie issues to risk and cause.** Broken trusted analysis, biased decisions, broken joins, stale dashboards, incorrect experiments, leakage, unreliable features, misleading segments. Localize: source, segment, partition, window, release, migration, backfill, upstream change.
7. **Recommend fixes or tests.** The smallest set of fixes, monitoring, or automated tests that materially reduce risk. Save the notebook or query path that produced the findings.

## Core checks

- **Completeness:** null rate by column and by partition, segment, and time bucket; empty strings and sentinels (`''`, `'unknown'`, `'n/a'`, `0`, `-1`); required-column population. Distinguish acceptable sparsity from broken completeness; look for columns newly null after schema or pipeline changes.
- **Uniqueness:** exact duplicate rows, duplicate primary and composite keys at the intended grain, near-duplicates from whitespace, casing, formatting, or late updates. Report count, share of rows, and whether duplication is isolated to a range, source, or segment. Normalize strings before judging duplicates.
- **Validity:** type conformance after casting; formats for IDs, emails, URLs, enums, country codes, timestamps; ranges for measures, percentages, counts, dates; allowed values for controlled vocabularies.
- **Consistency:** cross-field rules (for example `is_cancelled = false` with non-null `cancelled_at`), unit and currency consistency, status/timestamp alignment, agreement between duplicated fields from different sources.
- **Integrity and join coverage:** orphan foreign keys, unexpected one-to-many or many-to-many expansion, coverage loss when joining to dimensions or experiment assignments, row counts before and after joins, broken slowly changing dimension joins.
- **Timeliness:** lag from event time to load time and load time to report time, missing recent partitions, unexplained historical rewrites or backfills. Treat recent partitions carefully when data arrives late.
- **Volume and shape:** row-count and distinct-count drift against history, added/removed/retyped columns, share-of-total drift for major categories, new or vanished categories.

## Shape-specific checks

| Shape | Check for |
|---|---|
| Event data | Duplicate event IDs, future timestamps, session or user coverage gaps, abrupt event-mix changes after releases. |
| Dimension tables | Non-unique business keys, orphan surrogate keys, status changes without timestamps, unexpected churn in reference values. |
| Fact tables | Mixed grain, impossible measures (negative revenue or quantity), join blowups, late or partially loaded partitions. |
| ML feature or scoring tables | Leakage from post-outcome fields, sparsity spikes, range shifts after model or feature changes, label drift. |
| Experiment data | Duplicate assignments, variant imbalance beyond expectation, exposure without assignment, events before assignment time. |

## Temporal and distribution checks

Prioritize these when the user says "after X date", "suddenly", "recently", or "only started appearing":

- first-seen and last-seen dates; daily or weekly trends of null rate, duplicate rate, row count, and category share;
- change points around launches, migrations, incidents, model changes, or backfills;
- outliers with robust methods (quantiles, MAD, IQR) before z-scores; shifts in mean, median, variance, zero rate, and long tail;
- leakage and time travel: features populated before they should exist, future-dated records, unstable recent partitions, backfills that change history without annotation.

Call out when an anomaly could be a legitimate launch, experiment, migration, incident, model change, or backfill.

## Severity

- **Critical:** breaks trusted analysis, core joins, production dashboards, or key decisions (duplicated grain, missing primary keys, stale production data).
- **High:** materially biases decisions (large null spikes, core-dimension category drift, invalid business-rule values, leakage, severe join coverage loss).
- **Medium:** localized or explainable issues that still need documentation, monitoring, or owner follow-up.
- **Low:** cosmetic inconsistencies, expected sparsity, known edge cases with no material effect.

## Automated tests

Good candidates: primary-key uniqueness, not-null on required columns, accepted values for stable enums, referential integrity, freshness thresholds, seasonality-aware volume bounds. Be cautious with hard-coded distribution thresholds on volatile metrics, strict uniqueness in messy entity resolution, and recent partitions when late data is normal. Suggest a test only when the rule is stable, important, and maintainable.

## Output

Do not dump raw profiling output; tie every finding to a risk and impact. Prefer small high-signal tables. Structure:

1. dataset and grain summary
2. checks performed
3. findings
4. temporal or trend anomalies
5. likely causes and impacted use cases
6. recommended fixes or automated tests
7. assumptions and open questions

For each finding give: what failed; evidence (counts, rates, segments, dates); why it matters; severity and confidence; likely cause when known; remediation or test. Preserve inspectable evidence: SQL, notebook path, source paths, sample rows (non-sensitive), chart outputs.

For stakeholder-facing assessments, package the findings as a report (`references/deliverables.md`) unless the user asked for a quick inline answer or another artifact.
