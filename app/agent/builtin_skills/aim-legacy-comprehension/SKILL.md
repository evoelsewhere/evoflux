---
name: aim-legacy-comprehension
description: Reverse-engineers legacy code into knowledge-base docs bottom-up, dependency-first. Use when documenting an unfamiliar legacy codebase (COBOL, VB6, old Java, or any stack) before it gets migrated. Use when a business-rule catalog needs to be built from source code rather than from stale or missing documentation.
---

# AIM legacy comprehension

## Overview

Legacy comprehension for a migration project fails the same way almost every time: someone (or some LLM) is handed the whole codebase, or a whole file, and asked to "explain what this does." The result is either shallow (misses the actual business logic buried in a 2,000-line paragraph) or unaffordable (burns enormous context re-deriving what a callee does every single time it's referenced). This skill is the alternative: parse the code deterministically into the repository-local index first, then walk its relationships bottom-up so each unit's documentation can build on the documentation already written for the things it depends on.

## When to Use

- Building `modules/*.md` documentation for a legacy estate as part of an AIM project's Understand phase.
- Any time you're about to explain a legacy unit and its callees don't have documentation yet.
- Re-documenting a unit after its source changed (the code index reports that it is stale).

## When NOT to Use

**When NOT to use:** for target-stack code that already has current documentation or a modern codebase with reasonable naming — this discipline earns its cost specifically on unfamiliar, undocumented legacy source. Also not for a single quick question about one isolated function; that's an ordinary code-search task.

## The method

1. **Never read a unit before its dependencies are documented.** The unit's frontmatter already lists `depends_on` (filled from the index at assess time); confirm the unit with `code_context action=search refresh=true`, then inspect exact symbols with `action=callees`, `action=references`, or `action=neighborhood`. Check each dependency's state with `aim_units action=get` — phase `understood` with a real body means its doc is trustworthy. If a callee's doc doesn't exist yet, do that one first — or say so and let it be resequenced.
2. **Read the unit's own source plus its neighbors' existing docs**, not the neighbors' source. Once a callee has a doc, that doc is ground truth for what it does; re-reading its source every time defeats the purpose and burns context.
3. **Write for a developer who has never seen this codebase.** Purpose, control flow in prose (not a line-by-line transliteration), interfaces (what calls this, what this calls), side effects (files written, records updated, external systems touched). Write the BODY of `modules/<module>/<unit>.md`; leave the frontmatter state fields to the `aim_units` tool.
4. **Flag ambiguity instead of resolving it silently.** Dead code, unreachable branches, rules that seem to contradict each other — write the flag down. Ambiguity caught here is cheap; discovered during test compare it's expensive.
5. **Extract candidate business rules as you go** (see `aim-business-rule-extraction`) — comprehension and rule extraction are one pass over the code, not two.
6. **Close the loop in evidence**: return the written doc/rule paths and ambiguities to the workflow. Phase transitions are workflow-owned; the deterministic `mark_understood` node advances state only after this artifact-producing turn succeeds.

## Deriving the bottom-up order

The order comes from the graph, not from judgment calls:

1. **Index the estate first.** Call `code_context action=search refresh=true` so the repository-local index catches up before discovery. In an AIM project the source repos load their rulebook's structural extractors automatically (COBOL divisions/sections/paragraphs, JCL steps, VB6 procedures become nodes; `PERFORM`/`CALL`/`COPY`/`PGM=` become edges) — if `code_context` cannot return a known legacy symbol, fix the index before proceeding; don't read files in directory order.
2. **Leaves first.** A unit whose outgoing `calls`/`imports` edges all point at already-documented units (or at nothing) is ready. Start from units with no outgoing dependencies at all — utility paragraphs, copybooks, leaf procedures — and work upward. Discover each endpoint with `code_context action=search`, then query the exact symbol with `action=callees`, `action=references`, or `action=neighborhood` when reachability affects ordering.
3. **Cycles are one unit of work.** Legacy code cycles (A `PERFORM`s B, B `PERFORM`s A). Don't ping-pong: treat the whole cycle as a single documentation task, read its members together, and write their docs in one pass that cross-references within the cycle.
4. **Unresolved edges are leads, not blockers.** A `CALL 'XYZ'` whose target isn't in the graph means a dynamic call, a missing repo, or an external system. Flag it in the unit's doc and move on — don't stall the walk hunting for it.

## Verification

Before considering a unit's documentation done: does it cite what it calls and what calls it (not just describe the unit in isolation)? Does every non-obvious business decision in the source have a corresponding candidate rule, or an explicit note that none was found? Would a converter agent be able to implement this unit correctly from the doc alone, without re-reading the legacy source? Did you return concrete artifact paths and unresolved ambiguities for the workflow validator? If any answer is no, the doc isn't finished yet.
