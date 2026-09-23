# KPI Design

Design KPI frameworks, metric definitions, targets, guardrails, and measurement plans that help a team make product or business decisions. If the task is to reconcile existing metrics, dashboards, or sources of truth, start with `references/data-quality.md` and return here only to define the metric going forward, redesign the framework, choose guardrails, or set targets.

## Contents

- 1. Clarify the decision and operating context
- 2. Gather evidence before recommending
- 3. Generate a wide candidate set
- 4. Compare and select
- 5. Set targets when needed
- 6. Deliver the recommendation
- Example metric shapes

## 1. Clarify the decision and operating context

Identify the decision the metrics support, the review cadence, and who acts on the result. Ask about goal, cadence, or measurement constraints only when the answer would change the recommendation.

## 2. Gather evidence before recommending

When the prompt does not say what success means, gather context with `references/business-context.md`: goal, current state, audience, constraints, risks, existing definitions, prior decisions, and baseline or target context. Use it to learn how related metrics were defined before and which risks should shape drivers and guardrails.

## 3. Generate a wide candidate set

List candidate outcome, driver, and guardrail metrics before narrowing. Each candidate needs a clear definition and a plausible link to the decision.

## 4. Compare and select

Judge candidates on whether they:

- **reflect the goal** — for proxies, explain why they track real progress and where they mislead;
- **inform a real decision** — movement changes what the team does or investigates;
- **show signal at the decision cadence** — annual retention may be the right outcome but useless for a weekly launch review unless paired with earlier indicators;
- **can be influenced** by the team, or are paired with drivers it can move;
- **can be measured operationally** without one-off manual work;
- **are hard to game** — improving the metric should not hide harm to quality, trust, retention, or cost.

Score lightly only when it explains tradeoffs. Recommend 1-3 primary KPIs, 1-2 drivers per KPI when they improve diagnosis, and 1-2 guardrails when tradeoffs are likely. Add nothing that does not improve decisions.

For each recommended metric give: what it measures, why it matters, the calculation (numerator, denominator, grain, window, filters), the source, pros and cons against the criteria above, and caveats or guardrails.

## 5. Set targets when needed

Treat targets as a separate judgment from metric selection; set them when asked or when a threshold is needed for the recommendation to be useful.

- **Top-down:** benchmarks, historical performance, comparable products, market context, or a reasoned view of what "good" must look like.
- **Bottom-up:** what the team can realistically do — what ships, how adoption builds, which levers move the metric.

Identify the data the chosen approach needs (internal performance, benchmarks, results of similar past work) and use it. Compare aspirational targets with what planned work, available audience, expected adoption, and historical movement make plausible. State the anchor, assumptions, and confidence. If key inputs are missing, share the method and ask for the data; offer a provisional range when evidence is directional, or recommend the measurement needed before a firm target.

## 6. Deliver the recommendation

Deliver inline by default; a KPI framework does not need a report file just because it compares several candidates. Produce a chart or report (`references/visualization.md`, `references/deliverables.md`) when a visual materially helps — for example a target against historical performance or a candidate scoring view — or when the user asks for a document, dashboard, notebook, spreadsheet, or deck. Include:

1. initiative summary
2. recommended metrics with definition and rationale
3. target recommendation, if any, with anchor, assumptions, and method
4. evidence reviewed
5. assumptions and missing context
6. risks and guardrails
7. open questions

## Example metric shapes

Inspiration, not a template:

- **Launch or adoption:** adoption or value-realization outcome; drivers for activation, engagement, repeat use, time to value; experience-quality guardrails.
- **Growth:** the business outcome being improved (activation, retention, monetization); drivers that explain how growth happens; quality guardrails.
- **Funnel:** completion outcome; drivers at advance and drop-off points; downstream-quality guardrails.
- **Operating review:** health, pacing, and action-oriented metrics showing whether the business is on track and where attention is needed.
- **Experiment or intervention:** one primary success metric tied to the decision, diagnostics that explain movement, guardrails for unintended effects.
- **Data, model, or analytics initiative:** technical performance tied to the workflow it improves, with adoption, reliability, cost, or fairness guardrails.
- **Platform, reliability, operations:** service health, throughput, quality, cost efficiency, and customer impact in terms the owning team can act on.
