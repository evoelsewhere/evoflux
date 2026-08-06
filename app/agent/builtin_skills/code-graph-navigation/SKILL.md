---
name: code-graph-navigation
description: "Navigate indexed source with code_query, which returns current line-numbered code and structural relationships. Use for locating implementations, understanding behavior and flows, or checking change impact."
---

# Code Graph Navigation

Call `code_query` with the user's question, any known symbol or file names, and
one structured operation: `locate`, `explain`, `impact`, `trace`, or `change`.
Choose the operation through the function argument; never infer it in runtime
code from words in the user's message. The retrieval engine handles freshness,
language coverage, dirty source, and fallback itself.

Use the returned line-numbered source directly; do not read the same files
again. The result also includes callers, callees, imports, inheritance, and
other resolved relationships when available. A missing relationship means the
index did not resolve it, not that the runtime behavior is impossible.

Use as many materially distinct `code_query` calls as the task needs. Split a
large investigation by subsystem, repository, named flow, or uncovered source
range when one context pack cannot supply enough evidence. Never repeat the
same query with the same file budget. After every result, reuse its included
source and make the next query narrower and complementary; stop querying once
the evidence is sufficient. Use `grep`, `glob`, or `read` only for configs,
docs, generated artifacts, exact prose/literals, unsupported languages, or
source ranges explicitly reported as missing. Use tests, logs, or runtime
inspection to prove dynamic behavior.
