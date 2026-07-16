---
name: aim-legacy-comprehension
description: Reverse-engineers legacy code into knowledge-base docs bottom-up, dependency-first. Use when documenting an unfamiliar legacy codebase (COBOL, VB6, old Java, or any stack) before it gets migrated. Use when a business-rule catalog needs to be built from source code rather than from stale or missing documentation.
---

# AIM legacy comprehension

## Overview

Legacy comprehension for a migration project fails the same way almost every time: someone (or some LLM) is handed the whole codebase, or a whole file, and asked to "explain what this does." The result is either shallow (misses the actual business logic buried in a 2,000-line paragraph) or unaffordable (burns enormous context re-deriving what a callee does every single time it's referenced). This skill is the alternative: parse the code deterministically into a graph first, then walk that graph bottom-up so each unit's documentation can build on the documentation already written for the things it depends on.

## When to Use

- Building `modules/*.md` documentation for a legacy estate as part of an AIM migration project's Understand phase.
- Any time you're about to explain a legacy unit and its callees don't have documentation yet.
- Re-documenting a unit after its source changed (the code graph told you it's now stale).

## When NOT to Use

**When NOT to use:** for target-stack code that already has current documentation or a modern codebase with reasonable naming and structure — this discipline earns its cost specifically on unfamiliar, undocumented, or unconventional legacy source. Also not the right tool for a single quick question about one isolated function; that's an ordinary code-search task.

## The method

1. **Never read a unit before its dependencies are documented.** Check the code graph (`code_search`, `code_graph`, `code_overview`, `code_path`, or the structural-parser equivalent for languages without a tree-sitter grammar) to find what a unit calls, includes, or reads. If a callee's `modules/` doc doesn't exist yet, do that one first — or if you can't, say so and let the dependency get done out of band.
2. **Read the unit's own source plus its neighbors' existing docs**, not the neighbors' source. Once a callee has a doc, treat that doc as the ground truth for what it does; re-reading its full source every time defeats the purpose and burns context you don't have to spend.
3. **Write for a developer who has never seen this codebase.** Purpose, control flow in prose (not a line-by-line transliteration of the legacy syntax), interfaces (what calls this, what this calls), side effects (files written, records updated, external systems touched).
4. **Flag ambiguity instead of resolving it silently.** Dead code, unreachable branches, rules that seem to contradict something you already documented — write it down as a flag, don't quietly pick an interpretation. Ambiguity caught here is cheap; ambiguity discovered later during test compare is expensive.
5. **Extract candidate business rules as you go** (see the `aim-business-rule-extraction` skill) rather than treating comprehension and rule extraction as separate passes over the same code.

## Deriving the bottom-up order

The order comes from the graph, not from judgment calls:

1. **Index the estate first.** Reindex the source workspace so the graph is current. In an AIM project the source repos load their rulebook's structural extractors automatically (COBOL divisions/sections/paragraphs, JCL steps, VB6 procedures become nodes; `PERFORM`/`CALL`/`COPY`/`PGM=` become edges) — if `code_search` on a known legacy symbol returns nothing, the index hasn't run; fix that before proceeding, don't fall back to reading files in directory order.
2. **Leaves first.** A unit whose outgoing `calls`/`imports` edges all point at already-documented units (or at nothing) is ready. Start from units with no outgoing dependencies at all — utility paragraphs, copybooks, leaf procedures — and work upward. `code_path` between a unit and a suspected dependency confirms ordering questions cheaply.
3. **Cycles are one unit of work.** Legacy code cycles (A `PERFORM`s B, B `PERFORM`s A). Don't ping-pong: treat the whole cycle as a single documentation task, read its members together, and write their docs in one pass that cross-references within the cycle.
4. **Unresolved edges are leads, not blockers.** A `CALL 'XYZ'` whose target isn't in the graph means a dynamic call, a missing repo, or an external system. Flag it in the unit's doc and move on — don't stall the whole order hunting for it.
5. **Record progress in `aim_units`**, not in your head: set a unit's phase forward when its doc lands, so the next session (or the next teammate on a cloned KB) resumes the walk instead of re-deriving it.

## Verification

Before considering a unit's documentation done, check: does it cite what it calls and what calls it (not just describe the unit in isolation)? Does every non-obvious business decision in the source have a corresponding candidate rule, or an explicit note that none was found? Would a converter agent be able to implement this unit correctly from the doc alone, without re-reading the legacy source? If any answer is no, the doc isn't finished yet.
