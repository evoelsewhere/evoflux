# Project context for ASDD

This file is read before every phase. It is the repository's own voice: what
this codebase is, what a change here has to respect, and what "done" means
locally. Replace the placeholders below — an accurate paragraph here saves more
agent turns than any instruction elsewhere.

## Context

_What this repository ships, who uses it, and what it must not break. Two or
three sentences; agents read this first and reason from it._

## Conventions

- _Language, framework and layout an agent should follow._
- _Where durable logic belongs, and where it does not._
- _The commands that prove a change works._

## Rules

### Proposal

- _What a proposal here must always state — affected component, user impact,
  breaking-change status._

### Design

- _When a design document is required beyond the risk tier default._

### Specs

- _Domain vocabulary a requirement must use, and scenarios that must always be
  covered (migration, rollback, failure)._

### Tasks

- _Documentation, changelog or release steps a change here always includes._

## Catalogue

- `project.md` — this file: the repository's own context and rules.
- `architecture/` — process, storage, concurrency and trust boundaries.
- `architecture/decisions/NNNN-<slug>.md` — durable decisions, ADR-style.
- `specs/<capability>/spec.md` — the current contract for one behavior.
- `reference/` — exact API, configuration, schema and CLI contracts.
- `analysis/` — investigations, dated; historical rather than normative.
- `changes/<change-id>/` — one proposed change and everything it needs.
- `changes/archive/YYYY-MM-DD-<change-id>/` — changes already folded into the
  specs.

Each directory holds a `README.md` stating what belongs in it. Read that one
before writing a page into it.
