---
name: decision-analysis
description: Turns a fuzzy choice into an auditable, evidence-backed recommendation using framing, options, and a weighted trade-off matrix. Use when comparing approaches, evaluating trade-offs, assessing risk, or deciding between alternatives. Triggers on "which should I", "compare options", "is it worth it", "trade-offs", or "help me decide".
---

# Decision Analysis

## Overview

Most bad decisions are not bad calls — they are unframed ones. The dimensions get compared in someone's head, one factor silently dominates, and the reasoning evaporates the moment the decision is made, so nobody can tell later whether it was right or just confident.

This skill makes the reasoning **explicit and auditable**: frame the problem, enumerate real options with honest trade-offs, score them against weighted criteria, and recommend one — with the single biggest risk and an early-warning signal named up front. The matrix is not bureaucracy; it is what lets a reader (or a future you) see *why* and revisit deliberately when conditions change.

## When to Use

- Choosing between two or more genuinely competing approaches
- Weighing a trade-off where the right answer isn't obvious
- Assessing whether something is "worth it" (cost vs benefit vs risk)
- A decision with real stakes, lock-in, or hard reversibility
- You need to justify a recommendation to someone else

**When NOT to use:**

- The choice is trivial or easily reversible — just decide and move on
- There is only one viable option — state it and why, no matrix needed
- The user wants raw research/facts, not a recommendation (use research-and-fact-checking)
- It's a values/taste call with no objective criteria

## The Process

Copy this checklist when applying the skill:

```
Decision cycle:
- [ ] Step 1: FRAME — restated decision, constraints, success criteria, unknowns
- [ ] Step 2: OPTIONS — enumerated real alternatives incl. "do nothing"
- [ ] Step 3: CRITERIA — chose criteria, assigned explicit weights
- [ ] Step 4: SCORE — scored each option, showed the matrix
- [ ] Step 5: RECOMMEND — picked one, named biggest risk + revisit signal
```

### Step 1: FRAME — Define what's actually being decided

Restate the decision in one sharp sentence. Sharpen it if the user's framing is vague. Then separate:

- **Hard constraints** — non-negotiable. An option that violates one is disqualified, not penalised.
- **Soft constraints** — preferences that influence scoring.
- **Success criteria** — how you'll know, later, that the choice was right.
- **Key unknowns** — facts you'd need but don't have yet.

State every assumption and label it `ASSUMED` until confirmed.

```
Decision: "Adopt a managed queue (SQS) or self-host (RabbitMQ) for job processing."
Hard constraints: must stay under $X/mo; must support delayed delivery.
Soft constraints: prefer minimal ops burden; team already knows AMQP.
Success criteria: <1% job loss; on-call pages for the queue drop to ~0.
Unknowns: [ASSUMED] peak throughput ≈ 5k msg/s — confirm from metrics.
```

### Step 2: OPTIONS — Enumerate the real alternatives

List the genuine choices — and always include **"do nothing / status quo"** when it's valid; it is the baseline every option must beat. Avoid strawman options that exist only to make the favourite look good. For each option, capture:

- What it **optimises for**
- What it **sacrifices**
- **Cost** to adopt (effort, money, time, switching cost)
- **Reversibility** (easy rollback vs one-way door / lock-in)
- **Failure modes** — what breaks, under what conditions, how badly

### Step 3: CRITERIA — Choose and weight

Derive 3–6 decision criteria from the constraints and success criteria in Step 1. Assign each an explicit weight (e.g. 1×–3×) reflecting how much it matters *for this decision*. Weighting before scoring is what stops the loudest factor from silently winning. Make the weights visible so a reader can challenge them.

### Step 4: SCORE — Build the matrix

Score each option 1–5 per criterion. Show the full matrix, multiply by weights, and total. If a hard constraint is violated, mark the option disqualified rather than letting a high score elsewhere rescue it.

```
| Criterion (weight)      | SQS | RabbitMQ |
|-------------------------|-----|----------|
| Ops burden (3×)         |  5  |    2     |
| Cost at scale (2×)      |  3  |    4     |
| Team familiarity (1×)   |  2  |    5     |
| Delayed delivery (2×)   |  5  |    4     |
| **Weighted total**      |**33**|  **29** |
```

The matrix makes the reasoning auditable: anyone can challenge a weight or a score, and the conclusion moves with the evidence.

### Step 5: RECOMMEND — Commit, with a tripwire

- Pick **one** option, derived from the matrix. If you override the numbers, say exactly why (a factor the matrix underweights, a constraint that trumps the total).
- Name the **single biggest risk** of the recommended option and a concrete mitigation.
- Define the **earliest signal** that the choice was wrong — a metric, event, or deadline — so the decision can be revisited on purpose, not in a crisis.

## Operating Rules

- **Quantify over narrate.** "P99 340ms at 50k rows" beats "might be slow." If you can't measure, give a worst-case bound and label it an estimate.
- **Don't hedge.** "It depends" is a non-answer. Specify the exact condition that flips the decision and recommend for each branch.
- **Surface second-order effects.** A fix that solves A while creating B and C may be worse than a duller option that stays local.
- **Right-size the rigour.** A reversible, low-stakes choice deserves a quick call; a one-way door deserves the full matrix.
- **Keep weights honest.** Set weights from the constraints *before* scoring — never tune them afterwards to justify a favourite.
- **Cite the evidence.** Tie scores to measurements, sources, or stated assumptions — not vibes.

## Output

```markdown
## Decision
<Restated in one sentence · hard constraints · success criteria>

## Assumptions
- [ASSUMED] ... — <will confirm via Y>
- [CONFIRMED] ... — <source>

## Options
| Option | Optimises for | Sacrifices | Cost | Reversible | Key failure mode |
|--------|---------------|------------|------|------------|------------------|
| A      | ...           | ...        | Low  | Yes        | ...              |
| B      | ...           | ...        | Med  | No         | ...              |

## Weighted matrix
| Criterion (weight) | A | B |
|--------------------|---|---|
| <Criterion> (3×)   | 4 | 2 |
| **Weighted total** |**18**|**16**|

## Recommendation
**Go with <X>.** <Reasoning tied to the matrix — 2–3 sentences.>
**Biggest risk:** <failure mode> → **Mitigation:** <action>
**Revisit if:** <metric or event that means this was the wrong call>
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I already know the answer, the matrix is busywork" | If you're right, the matrix confirms it in minutes and makes it defensible. If you're wrong, it's the cheapest place to find out. |
| "Just tell me which one" | A verdict with no reasoning can't be trusted, challenged, or revisited. Show the trade-offs. |
| "It depends on too many things" | Then name the one or two things it depends on, and recommend per branch. That *is* the answer. |
| "Do nothing isn't a real option" | It's the baseline. If no option beats it on the matrix, the honest recommendation is to wait. |
