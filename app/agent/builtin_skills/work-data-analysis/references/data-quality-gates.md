# Data-quality gates

Read the applicable gate before interpreting results.

## Source and grain

- State one row's meaning for every source.
- Verify uniqueness at the claimed key and explain legitimate repeats.
- Compare coverage period, refresh time, and source-of-truth ownership.
- Preserve units, currency, locale, and time-zone semantics.

## Joins

Measure row counts and key coverage before and after each join. Check
one-to-one, one-to-many, and many-to-many expectations. Report unmatched keys
and prevent fan-out from silently inflating totals.

## Missingness and exclusions

Quantify missingness by relevant segment and time. Determine whether absence
means zero, not applicable, not observed, or data failure. Record each filter
with rows and metric mass removed. Test whether exclusions change the result.

## Outliers and anomalies

Validate whether extreme values are errors, rare valid events, unit mistakes,
or the phenomenon of interest. Show results with and without any treatment;
never delete outliers solely because they are inconvenient.

## Experiments and forecasts

For experiments, verify assignment, exposure, sample ratio, pre-period balance,
independence, and stopping policy. For forecasts, backtest on a held-out period
when feasible and show scenario assumptions separately from observed inputs.

The analysis does not pass a gate merely because code ran successfully.
