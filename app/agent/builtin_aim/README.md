# AIM built-in content (AIM-0 → AIM-4)

Bundled AIM content, per `documents/research/aim-framework.md` in the EvoFlux repo:

- `rulebooks/java8-java21/` and `rulebooks/vb6-dotnet/` — the two AIM pilot rulebook packs (§3.7).
- `workflows/` — six stack-agnostic AIM pipeline definitions (§3.11, see `workflows/README.md`).

## Status

**Fully wired as of AIM-4 (commit ba9433c).** All pipelines run as real Workflows
(POST `/api/workflows/{name}/run` against an `aim`-mode session). The trigger
surface (`AimPipelinesPanel`) never opens a chat composer — gates are answered
inline via the Gate panel, post-run discussion via the Discussion panel.

| AIM milestone | Description |
|---|---|
| AIM-0 | Rulebooks + KB layout + builtin agents |
| AIM-1 | `aim_units` / `aim_compare` tools + rulebook install service |
| AIM-2 | `aim` mode shell (sidebar → project → features) |
| AIM-3 | Overview board, KB browser, Runs & Reports, post-run Discussion |
| AIM-4 | Pipelines wired to real Workflows engine; Gate panel for in-flight gates |
