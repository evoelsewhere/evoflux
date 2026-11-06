# Settling the brief

A workbook encodes decisions that are expensive to reverse: what one row
means, which numbers are drivers, what the totals reconcile to. Guessing them
silently produces a model that computes confidently and answers the wrong
question.

The rule: **ask once, about what would change the model, and only what the
data and the request cannot already answer.**

## Answer from context first

- The supplied data fixes grain, columns, types, and period. Inspect it before
  asking anything about it — row counts, keys, null counts, date range.
- The user's words fix purpose: "model", "report", "clean this up", "export",
  and "reconcile" are four different deliverables.
- An existing workbook fixes conventions. Match its layout, its number
  formats, and its colour meanings rather than imposing new ones.

## When to skip entirely

- The request is a mechanical transform: export, split, patch known cells.
- The workbook exists and the change is local to named cells or a new column.
- The user gave the grain, the drivers, and the output explicitly.
- The user asked for speed or already declined questions this session.

## What is worth asking

At most three, one `ask_user` call, options with a marked recommendation:

1. **Grain and population.** What does one row represent, and which rows are
   in scope? Every later total inherits this answer, and a wrong grain is not
   visible in the output — it just makes every figure quietly incorrect.
2. **Drivers versus constants.** Which inputs should the reader be able to
   change? That decides what becomes a labelled input cell and what is a
   formula. A model whose assumptions are buried in formulas cannot be used.
3. **The output and its reconciliation.** What decision does this support, and
   is there a trusted figure the totals must match? A known reconciliation
   target turns verification from opinion into a check.

Column widths, fonts, freeze panes, and file name are defaults you take
yourself. Number formats follow the data's own meaning: ask only when currency
or unit is genuinely ambiguous.

## How to ask

Use `ask_user` with concrete options, recommendation first and marked, each
option carrying its consequence. One call.

If unanswered, take the defaults, state each assumption in the plan, and
continue. Never let an unanswered question become an invisible one.

## The plan, and the gate

Before building, put in front of the user:

- the sheet list, and for each sheet its purpose and its grain;
- the input cells you will create, with the value you intend to seed;
- the formulas that carry the result, described in words;
- the reconciliation you will run, or a statement that none exists;
- every transformation you will apply to the source data — rows excluded,
  types coerced, duplicates resolved — each with its reason.

That last list is the gate's real work. Silent cleaning is how a number that
nobody can reproduce ends up in a decision.

Wait for approval. Skip the gate only for a mechanical transform.

After approval the plan is the contract. If the data forces a departure — a
key that does not join, a period with no rows — stop and say so rather than
patching around it.
