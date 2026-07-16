---
# Overlay for aim-converter — merged onto seed/agents/aim/aim-converter.md
# by the rulebook install step (AIM-1): `skills` appended, prose appended
# to the base system prompt.
skills:
  - vb6-dotnet-idioms
---

## VB6 → .NET specifics

This is a cross-language, cross-paradigm migration — treat every construct mapping in `mappings/vb6-to-dotnet-constructs.md` as a starting point, not a mechanical substitution, especially around error handling (`On Error GoTo` / `Resume`), implicit global state (standard modules), and `Variant`/fixed-length-string semantics. If a screen is involved, the mapping must already specify which pattern in `ui-patterns/vb6-to-dotnet-ui-patterns.md` it follows and which target template to instantiate — implement against that template; do not design the screen yourself.
