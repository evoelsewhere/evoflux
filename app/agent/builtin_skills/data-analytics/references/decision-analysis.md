# Product and Business Decision Analysis

Answer a product or business question with metric-backed evidence and a recommendation: choosing a direction, prioritizing opportunities, evaluating a launch or change, segmenting users, sizing tradeoffs, or deciding what to do next. The audience should end with enough trustworthy evidence and uncertainty framing to pick a practical next action.

## Contents

- 1. Start from the decision
- 2. Gather decision-relevant context
- 3. Frame the analysis
- 4. Run focused quantitative analysis
- 5. Translate evidence into implications
- 6. Hand off the recommendation

## 1. Start from the decision

State plainly: the decision the analysis informs, who uses the answer and what they can act on, the scope and comparison that make an answer useful, the outcome or behavior that matters, and the assumptions needed to proceed. Do not let unclear scope turn into broad exploration.

## 2. Gather decision-relevant context

Run a context pass with `references/business-context.md` before deeper analysis, sized to the task. When the prompt is self-contained, keep it brief: confirm the decision frame, definitions, source assumptions, and obvious gaps. Context should clarify:

- intent: what the work was meant to accomplish;
- definitions: how the work, metric, or source is measured;
- timing: what changed around the analysis period;
- constraints: caveats or limits on what action is realistic.

## 3. Frame the analysis

Turn the question into a focused framework:

- the data questions that would support or change the recommendation;
- the comparisons and dimensions to inspect;
- the unit of analysis that matches the decision;
- the metric definitions and caveats needed to interpret results.

Write what the answer needs to show in plain language first, then pick the data that matches that meaning as closely as possible, including who is counted. If a field or event captures only part of what the decision cares about, say what it leaves out. If the success metric, drivers, or guardrails are undefined, design them first with `references/kpi-design.md`. If the recommendation depends on explaining a metric movement, use `references/metric-diagnostics.md`.

## 4. Run focused quantitative analysis

- **Follow the framework.** Run the analyses that could change the recommendation first. Track emerging questions; answer the ones that matter and leave lower-impact cuts as follow-up.
- **Use the right comparison.** Do not call a group the best opportunity because it has the most total usage. Check whether it is simply larger, whether the pattern holds after normalizing by the active base, whether it is growing or shrinking, whether the usage reflects the outcome that matters, and whether context changes the reading.
- **Size the opportunities.** For each important option, state what is compared, which metric represents impact, its denominator or population, and whether the data is complete enough. Keep material unknown or unclassified groups visible.
- **Keep work inspectable.** Record queries and calculations in a notebook (`references/notebooks.md`). Check source trust with `references/data-quality.md` when freshness, grain, joins, or missingness could matter.
- **Reconcile.** When dashboards and direct queries both exist, reconcile them or explain the difference.

## 5. Translate evidence into implications

Interpret findings inside the business context rather than presenting numbers and context as separate streams. Use only the lenses that would change the recommendation:

| Lens | Question |
|---|---|
| Current scale | Is it large enough today to matter? |
| Momentum | Growing, shrinking, accelerating, newly emerging? |
| Breadth | Broad-based or confined to a narrow corner? |
| Concentration | Does it depend on a few entities, events, or outliers? |
| Intensity | Is per-unit behavior deep enough to signal real need, value, or risk? |
| Efficiency | Better output, margin, conversion, or quality per unit of input? |
| Addressability | Can the team act with available product, GTM, operational, or technical levers? |
| Differentiation | Does this group need a distinct motion, experience, or message? |
| Substitution | Could behavior or spend shift from another path? |
| Risk or dependency | Quality, trust, compliance, technical, or data constraints? |
| Coverage | Are unknown or sparsely tagged records large enough to change the answer? |

Explain why the chosen lenses matter; mention omitted cuts only when they could change the interpretation. If context shows the initial sizing misses the actionable part of the opportunity, add the focused sizing cut. When evidence conflicts, say so and state which interpretation is better supported.

## 6. Hand off the recommendation

Make the recommendation explicit:

- what to believe or do next;
- why the evidence supports it;
- caveats and dependencies that matter;
- the follow-up analysis that would most improve confidence.

Label a recommendation provisional when evidence is incomplete and state what would change confidence. Run `references/pre-share-review.md` before sharing stakeholder-facing recommendations, high-impact claims, or surprising results.

Package the result as a report (`references/deliverables.md`) unless the user asked for an inline or chat-only answer, asked for no file, or chose another artifact. Pass narrative ingredients, not only result tables: direct answer and recommendation, key evidence and how to read it, the decision implication, unresolved uncertainty, and recommended follow-up.
