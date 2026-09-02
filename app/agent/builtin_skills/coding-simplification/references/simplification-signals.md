# Simplification signals

Read this reference when choosing which concrete refactor to apply.

## Shape-to-refactor mapping

| Signal | Refactor |
| --- | --- |
| Deep nested conditionals | Guard clauses / early return |
| Boolean flag parameter changing behavior | Split into named functions, or an options object |
| Generic name (`data`, `handle`, `process`) | Rename to the concrete concept it holds |
| Repeated conditional dispatch on a type/tag | Replace with a dispatch table or polymorphism |
| Long parameter list of related values | Group into one named type |
| Duplicated block across 2-3 call sites | Extract only if the duplication represents one concept, not a coincidence |

Coincidental duplication (two blocks that happen to look similar today but
serve different concepts) should stay duplicated; unifying it creates a false
shared dependency that diverges later.

## Rule of 500

A refactor touching roughly 500 lines or more by hand risks silent behavior
drift and an unreviewable diff. Prefer a codemod, AST-based transform, or
scripted rename so the change is mechanical, and review a diff sample rather
than every occurrence.

## Balance against over-simplification

Do not collapse necessary variation into a false abstraction to make code
look shorter. A slightly longer, explicit version that matches each caller's
real need is simpler to change safely than a clever one that hides special
cases inside conditionals.
