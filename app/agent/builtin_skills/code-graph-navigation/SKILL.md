---
name: code-graph-navigation
description: "Navigate indexed source with one code_query call that returns current line-numbered code and structural relationships. Use for locating implementations, understanding behavior and flows, or checking change impact."
---

# Code Graph Navigation

Call `code_query` with the user's question and any known symbol or file names.
The model does not need to select an intent, freshness policy, language, or
symbol kind. The retrieval engine handles graph lookup, dirty source, and
unsupported-language fallback itself.

Use the returned line-numbered source directly; do not read the same files
again. The result also includes callers, callees, imports, inheritance, and
other resolved relationships when available. A missing relationship means the
index did not resolve it, not that the runtime behavior is impossible.

Call `code_query` again only with a more specific name when the first result
identifies code it could not include. Use `grep`, `glob`, or `read` for configs,
docs, generated artifacts, exact prose/literals, or when the result explicitly
reports missing graph coverage. Use tests, logs, or runtime inspection to prove
dynamic behavior.
