# AIM built-in content (draft — AIM-0)

Bundled AIM content, per `documents/research/aim-framework.md` in the EvoFlux repo:

- `rulebooks/java8-java21/` and `rulebooks/vb6-dotnet/` — the two AIM-0 pilot rulebook packs (§3.7), one same-language upgrade (no structural parser needed) and one cross-language, screen-heavy migration (the proving ground for the structural fallback parser and the §3.13A UI/UX rules).
- `workflows/` — the three core, stack-agnostic AIM pipeline definitions (§3.11), written against the Workflows v5 schema ahead of the engine that will run them.

None of this is wired into a running mode yet. The stack-agnostic core roster lives at `seed/agents/aim/`, the method skills at `app/agent/builtin_skills/aim-*`, and the KB starting layout at `seed/aim-kb-template/` — those are usable today (skills, in particular, are auto-discovered); everything under this directory becomes live once AIM-1 (rulebook install service, `aim_units`/`aim_compare` tools) and AIM-2 (the `aim` mode itself) exist.
