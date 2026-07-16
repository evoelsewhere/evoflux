---
# Overlay for aim-converter — the rulebook install step (AIM-1) merges this
# onto seed/agents/aim/aim-converter.md: `skills` are appended (not
# replaced), and the prose below is appended to the base system prompt.
skills:
  - java-modernization-idioms
---

## Java 8 → 21 specifics

This pair is a same-language upgrade, not a cross-language translation — the risk is idiomatic drift and quietly-changed semantics (see the `java-modernization-idioms` skill), not structural loss. Prefer modernizing a construct only when the mapping in `mappings/common-constructs.md` says the semantics are equivalent; if a "nicer" Java 21 idiom would change behavior at the margins (e.g. `List.of()` rejecting nulls where the legacy list allowed them), keep the safer form and note why in the mapping doc rather than modernizing it away.
