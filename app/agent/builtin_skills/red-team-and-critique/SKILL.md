---
name: red-team-and-critique
description: Stress-tests a plan, proposal, claim, or argument by attacking its weakest assumptions, modeling failure, and surfacing stronger alternatives. Use when you need a devil's advocate, a pre-mortem, or an honest critique before committing. Triggers on "poke holes", "what could go wrong", "red-team this", "play devil's advocate", or "stress-test".
---

# Red-Team & Critique

## Overview

Agreement is cheap and dangerous. A proposal that has only ever been nodded at is untested; the cracks are still there, they just haven't been found yet. This skill is the discipline of deliberately trying to **break** a plan, claim, or argument before reality does — when course-correction is still cheap.

The goal is rigour, not contrarianism. A useful critique is specific, fair, and actionable: it attacks the strongest version of the idea, ranks findings by how much they matter, and offers a path forward — not a list of nitpicks designed to look clever. A challenge raised today is far cheaper than the failure it prevents.

## When to Use

- Before committing to a plan, design, or significant decision
- Pressure-testing a claim, estimate, or argument that "feels right"
- A pre-mortem: imagining the failure before it happens
- Reviewing someone's proposal where honest pushback is wanted
- High stakes, lock-in, or irreversibility raise the cost of being wrong

**When NOT to use:**

- The user wants encouragement, momentum, or a draft — not a teardown
- The decision is trivial or fully reversible — critique is overhead
- Reviewing *code* specifically (use code-review-and-quality / security-and-hardening); this skill is for plans, proposals, and arguments
- A direction is already chosen and the task now is execution, not re-litigation

## The Process

Copy this checklist when applying the skill:

```
Red-team cycle:
- [ ] Step 1: STEELMAN — restated the proposal in its strongest form
- [ ] Step 2: ASSUMPTIONS — listed the load-bearing beliefs
- [ ] Step 3: PRE-MORTEM — "it's 6 months later and it failed; why?"
- [ ] Step 4: PROBE EDGES — load, bad input, scale, dependency failure, adversary
- [ ] Step 5: RANK — sorted findings by impact × likelihood
- [ ] Step 6: PATH — gave each serious finding a mitigation/test/alternative
```

### Step 1: STEELMAN — Understand it at its strongest

Before attacking, restate the proposal in its **strongest, most charitable form** — in one or two sentences. This is not politeness; it is what makes the critique land. Attacking a weakened or misread version produces objections the author can wave away, and you learn nothing. If you can't steelman it, you don't understand it well enough to critique it yet.

### Step 2: ASSUMPTIONS — Find the load-bearing beliefs

Every plan rests on a few beliefs that, if false, collapse it. These — not cosmetic details — are the target. List them explicitly, then ask of each: *what if this is wrong?*

```
Proposal: "Cache the user profile for 5 minutes to cut DB load."
Load-bearing assumptions:
- Profile data tolerates 5 min staleness   ← if false: users see stale permissions
- Read load is the actual bottleneck        ← if false: the cache solves nothing
- Invalidation on write is reliable          ← if false: silent corruption
```

### Step 3: PRE-MORTEM — Assume it already failed

Project forward: *it is six months later and this failed badly. Narrate why.* Working backwards from an assumed failure surfaces modes that forward, optimistic reasoning glosses over. List the most plausible failure stories.

### Step 4: PROBE THE EDGES

Stress the proposal at its boundaries:

- **Load / scale** — what happens at 10×? 100×? Where's the serialisation point?
- **Bad input** — malformed, missing, hostile, or out-of-range data.
- **Dependency failure** — a service it relies on is slow, down, or wrong.
- **Assumption breakdown** — the conditions from Step 2 don't hold.
- **Adversary** — someone actively tries to abuse or break it.
- **Second-order effects** — who's hurt, what behaviour does it incentivise, what new problem does it create downstream?

### Step 5: RANK — Severity, not volume

Sort findings by **impact × likelihood**. One catastrophic-and-likely flaw outranks ten cosmetic nitpicks. Drowning a real risk in trivia is itself a failure of critique — it lets the author dismiss the whole review. Separate **fatal flaws** from **real risks** from **minor concerns** from **preferences**, and label which is which.

### Step 6: PATH — Don't just diagnose

For each serious finding, offer one of: a **mitigation**, a **test or measurement** that would settle whether it's real, or a **stronger alternative**. A critique that only tears down is half the work; the value is a better outcome.

## Challenge Lenses

Run the proposal past each:

- **Assumptions** — which unstated beliefs must hold? What if they don't?
- **Failure modes** — what breaks, under what conditions, how badly?
- **Incentives & second-order effects** — who's hurt, what behaviour is encouraged, what's created downstream?
- **Alternatives** — is there a simpler or more robust option being ignored?
- **Evidence** — is a key claim unsupported, outdated, or from a biased source?

## Operating Rules

- **Read before you challenge.** Evidence-free criticism is noise. Ground every objection in the actual proposal or data.
- **Be specific.** "This won't scale" is useless. "At 10k concurrent users the single write lock at step 3 serialises everything" is actionable.
- **Steelman, then strike.** Attack the strongest version, never a caricature.
- **Calibrate honestly.** Say which findings are fatal, which are risks, which are taste. Don't inflate to seem rigorous.
- **Stay constructive.** The aim is a better outcome, not winning the exchange. Offer a path, not just a verdict.
- **Know when to stop.** Once the load-bearing risks are surfaced and ranked, stop. Endless nitpicking buries the signal.

## Output

```markdown
## Steelman
<The proposal in its strongest form — 1–2 sentences>

## Critical risks (ranked by impact × likelihood)
1. **[fatal | high | medium]** <Risk> — <why it bites> → <mitigation / test / alternative>
2. ...

## Minor concerns
- <Lower-stakes issues, briefly>

## Verdict
<Proceed | proceed with changes | reconsider> — <one-line rationale>
```



## Verification

- Copy this checklist when applying the skill:

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It looks solid, I'll just approve it" | "Looks solid" is the state of every plan right before the flaw is found. Approval without an attack is untested. |
| "I'll list everything I can think of" | A flood of nitpicks hides the one risk that matters and gets the whole review dismissed. Rank by severity. |
| "Being critical means being negative" | Useful critique is constructive — it attacks the strongest version and offers a path. Cheap negativity attacks a strawman. |
| "We've already decided, no point poking holes" | If it's reversible, the pre-mortem is cheap insurance. If it's not, finding the flaw now is the only chance you get. |
