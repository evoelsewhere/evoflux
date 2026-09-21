# Decisions

One file per durable decision: what was chosen, what it rules out, and why.
A decision belongs here when reversing it later would cost more than making it
did — a storage engine, a trust boundary, a protocol, an ordering guarantee.

```text
decisions/
└── NNNN-<slug>.md      # 0001-single-writer-sqlite.md
```

`NNNN` is the next free four-digit number. It orders the record; the slug names
it.

## The shape of one

```markdown
---
status: accepted        # proposed | accepted | superseded
date: YYYY-MM-DD
change: <change-id>     # the change that decided it
supersedes: NNNN        # omit unless it replaces one
---

# NNNN. <the decision, as a statement>

## Context

What made this a decision rather than a default: the constraint, the pressure,
the thing that would otherwise go wrong.

## Decision

What we do, in the present tense. One paragraph.

## Consequences

What this buys, what it costs, and what it now forbids. Name the option that
was rejected and the reason it lost — a decision with no rejected alternative
was not a decision.
```

## How one changes

It does not. An accepted decision is a record of what was true and why, so
correcting it means writing a new one that says `supersedes: NNNN` and setting
the old one's `status: superseded`. Rewriting history in place leaves the
codebase full of consequences whose cause no longer exists.
