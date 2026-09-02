---
name: coding-simplification
description: Use this skill to refactor existing code for clarity or reduced duplication without changing its observable behavior — deep nesting, boolean-flag parameters, generic names, or duplicated logic. It requires understanding why the current shape exists before changing it and proving behavior is unchanged; do not use it to implement new behavior, fix a bug, or restyle code with no clarity problem.
---

# Simplify existing code

Preserve behavior exactly; simplification is a clarity change, not a feature
or a bug fix.
Do not load bundled references when this skill activates.

## Understand before changing

1. State what the code currently does, including behavior that looks
   accidental — an existing edge case, ordering, or error path may be
   load-bearing even without a visible reason. Do not remove it without
   understanding why it is there (Chesterton's Fence): if the reason is
   unclear from code, tests, and history, name the uncertainty instead of
   deleting silently.
2. Scope the change to what motivated it. Do not restyle unrelated code in
   the same file, rename unrelated symbols, or introduce an abstraction the
   current requirement does not need.
3. Read [references/simplification-signals.md](references/simplification-signals.md)
   for concrete shape-to-refactor mappings and the codemod threshold.

When the code's current callers or the reason a pattern exists is not evident
from the visible source, call `code_context` with `action="search"` once
using the behavior or literal in question. Skip search when the exact symbol
is already known.

For an exact symbol being simplified, use `code_context` to confirm direct
`callers`/`references` so the refactor's public shape is preserved for every
caller. Start at depth 1. Once the symbol and its callers are known, make the
graph the next structural observation instead of continuing broad discovery.

Keep `refresh=true` for the first indexed query and after edits. Use
`refresh=false` only for an immediate follow-up that intentionally reuses the
same index version.

Read [references/code-context-contract.md](references/code-context-contract.md)
only after a result exposes ambiguity, cross-repository scope, or another
static fallback gap.

## Simplify

Prefer clarity over cleverness and follow the file's existing conventions
over a personally preferred style. Do not introduce a generic abstraction to
replace a handful of concrete, similar lines; three similar lines are often
clearer than a premature parameter or interface. For a refactor spanning more
than roughly 500 lines, prefer a codemod/AST-based transform over manual
edits so the change stays mechanical and reviewable.

## Prove behavior is unchanged

Run the existing test suite for the touched surface unmodified; a
simplification that requires changing an assertion has changed behavior, not
just shape. Add a regression test only when simplification exposes a
previously untested branch.

## Execution discipline and simplification stop

Confirm callers once; batch independent reads. Use `code_context`, `read`,
`grep`, and `glob` for source; do not use shell `cat`, `sed`, `head`, `tail`,
`nl`, `rg`, or `find` to reread source or bypass an observation receipt.
Reserve shell for formatter, lint/type, build, and test commands.

Stop once the motivating clarity problem is resolved and the existing tests
pass unmodified. Do not continue simplifying adjacent code the request did
not name.

## Deliverable

State what changed, why the prior shape existed (or that it could not be
determined), the callers confirmed unaffected, and the tests run to prove
behavior is unchanged.
