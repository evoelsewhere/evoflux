# Analysis

Investigations: what was measured, compared or reproduced, and what it showed.
This is the only part of the catalogue that is allowed to be out of date,
because it is a record of a question at a moment, not a statement of what is
true now.

```text
analysis/
└── YYYY-MM-DD-<topic>.md
```

## What belongs here

- A benchmark or profile, with the numbers and how they were produced.
- A comparison of options, with the criteria and what each one scored.
- A reproduction of a failure: the conditions, the observation, the cause.
- A survey of the existing code done before proposing a change.

## What does not

- The decision an investigation led to — that is
  `architecture/decisions/`, which cites the analysis.
- Proof that a change works — that is the change's own `evidence/`.
- Anything a reader should treat as current. If it must stay true, it belongs
  in `specs/`, `architecture/` or `reference/`.

## How it changes

It does not get corrected; it gets dated. Every page states when it was written
and against which revision, and a later finding is a new page rather than an
edit to the old one. An analysis nobody can date is an opinion.
