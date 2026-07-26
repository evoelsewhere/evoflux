---
name: code-graph-navigation
description: "Triggers include: code graph, caller, impact analysis. Navigate indexed code symbols and structural relationships across one or more repositories. Use for definitions, callers/callees, imports, inheritance, interface conformance, overrides, references, dependency paths, ambiguity, and change-impact analysis; verify important findings against live source. Do not use as the primary method for literal/config search or proof of runtime behavior."
---

# Code Graph Navigation

Use the graph to narrow the search space, then confirm material claims in live
source. Treat it as a static index of resolved structure, not proof of runtime
behavior.

## When to Use

- Locate definitions, callers, callees, imports, hierarchy, type references,
  decorators, dependency injection, data access, or containment.
- Estimate the impact of changing a shared symbol.
- Trace a dependency path within a repository or across a linked project.
- Map an unfamiliar codebase without reading many whole files.
- Investigate duplicate symbols or ambiguous relationships.

## When NOT to Use

- Search literals, error text, comments, config keys, or prose with text search.
- Prove reflection, dynamic dispatch, generated registration, runtime data flow,
  or environment-dependent behavior; use source, LSP, tests, or runtime evidence.
- Wait on an absent or stale index. Continue with normal source navigation and
  state that graph-based coverage remains unverified.

## Query Strategy

### 1. Establish scope only when needed

Call `code_overview` for broad exploration or an unfamiliar project. Check that
the expected languages and a plausible number of files are indexed. In a linked
project, note every repository label and flag repositories with zero files.

Skip the overview when the target symbol and repository are already known.

### 2. Resolve the symbol

Call `code_search` with the most specific identifier available. Prefer a
qualified name and add `kind` when names collide. Keep each candidate's
repository, qualified name, kind, signature, and `file:line` together.

Use text search for non-identifiers. Never select a candidate by name similarity
alone; read the smallest relevant source range when multiple candidates remain.

### 3. Ask only for the relationships required

Call `code_graph` with:

- `direction="in"` for callers, importers, references, and change impact.
- `direction="out"` for callees, imports, dependencies, and ambiguity details.
- `direction="both"` only when both sides affect the conclusion.

Start with a modest `limit` for high-fan-out symbols and increase it only when
truncation hides relevant results. Avoid repeating the same query under minor
name variations before inspecting the returned candidates.

Interpret edge labels literally:

- Invocation: `calls` / `called by`.
- Modules: `imports` / `imported by`.
- Hierarchy: `extends`, `implements`, `overrides`, and their inverse labels.
- Dependency and data: `uses`, `references`, `reads`, `writes`, `throws`, and
  their inverse labels.
- Metadata and ownership: `decorated by`, `contains`, and their inverse labels.

A missing edge means "not resolved by the index," not "cannot happen." An
`ambiguous <kind> '<name>'` result means the index deliberately refused to pick
a target. Resolve it from imports, receiver types, namespaces, and the call site.

When graph output says imports are file-level, do not attribute those imports to
the selected class or function; they belong to its containing file.

### 4. Trace paths only for reachability questions

Call `code_path` when the question is how one symbol can reach another. Use
qualified endpoints when possible. Treat the result as a shortest indexed
dependency path, not as an execution trace.

For linked projects, automatic sibling lookup is a fallback rather than an
exhaustive all-repository search: local matches can take precedence, and a full
active-repository result set can hide sibling search results. Preserve repository
labels and inspect the sibling source directly when same-name collisions matter.
If no path is found, inspect unresolved imports and manifest/package boundaries
before concluding the components are independent.

### 5. Verify before editing or concluding

Read the exact definitions and call sites identified by the graph. Use LSP for
aliases, receiver types, overrides, and live diagnostics when available. Before
editing a shared API, inspect inbound relationships; after editing, run focused
tests for the affected behavior.

## Verification

Before reporting the result:

- Confirm the relevant repository was indexed and the selected symbol was
  disambiguated by qualified name and location.
- Check inbound and outbound relationships when impact depends on both.
- Report ambiguous, missing, truncated, and possibly stale results as
  uncertainty rather than absence.
- Confirm material claims with source and, when runtime behavior matters, with
  LSP, tests, logs, or execution.
- Distinguish indexed evidence, source-confirmed evidence, runtime-confirmed
  evidence, and remaining unknowns in the final explanation.
