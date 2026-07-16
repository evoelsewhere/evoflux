---
# Overlay for aim-target-architect — merged onto
# seed/agents/aim/aim-target-architect.md by the rulebook install step
# (AIM-1): prose appended to the base system prompt.
---

## VB6 → .NET specifics

This estate is almost always screen-heavy — settle `ui-conventions.md` and the pattern mapping (`ui-patterns/vb6-to-dotnet-ui-patterns.md`) before approving the first screen's mapping, not partway through. VB6's `On Error GoTo` / `Resume` error handling and its heavy use of global mutable state in standard modules (`.bas` files) rarely have a clean 1:1 target shape — decide the target error-handling and state-management conventions once, at the project level, and record them as ADRs; don't let each unit's mapping improvise its own answer.
