# EvoFlux application harness

## Contract

EvoFlux has one agent harness and exactly two application modes:

| Mode | Workspace | Default outcome |
|---|---|---|
| Work | Session workspace/sandbox | Research, artifacts, browser and general execution |
| Coding | Persisted repository or project | Source changes, verification, graph and git workflows |

`AppMode` is the canonical runtime type. A new request selects a mode; after a
session exists, its persisted mode and workspace are authoritative. A resume
request cannot migrate a session as a side effect.

## Agent configuration

An agent Markdown file is the user-owned override surface. Code-owned first
party profiles contain built-in role descriptions, prompts, and mode
tool policy. `compile_agent_config` is the only merge implementation used by
both the runtime and settings API:

1. Load raw Markdown without side effects.
2. Apply the matching code-owned profile.
3. Add user-authored tools, optional skill metadata, MCP servers, and prompt text.
4. Apply `tools_opt_out` to code-owned tier tools.
5. Deduplicate the effective result.

Seed and materialised built-in Markdown files contain identity/model settings
and user overrides only. They do not duplicate code-owned capability lists.
Filesystem materialisation belongs to application bootstrap; loaders,
validation, and GET routes are pure.

## Skills and tools

Bundled skills are a small catalog of specialized artifact and operational
workflows. Their names and bodies are absent from the always-visible prompt and
tool schema. A workflow enters context only after an explicit composer
`/skill:<name>` directive or an on-demand `skill(action="list"|"load")` call.
Assigned skill metadata is never preloaded.

Request prose is never keyword-routed to a skill. Code graph is not a skill or
natural-language retrieval layer: the native `code_graph` tool accepts a known
exact symbol and one structural operation, with its contract enforced by the
tool schema and service boundary.

Tools declare their mode tier and role constraints in tool metadata. The
effective agent config may add allowed extras or opt out of defaults. Runtime
protocols may name guaranteed lifecycle/team tools, but first-party role
prompts remain capability-agnostic because optional tool schemas can be
deferred or excluded.

## Runtime context and hooks

Per-run hooks are assembled by `HookPipeline`. Each registration has:

- an ordered stage;
- one semantic owner name;
- one hook instance.

Duplicate owners fail immediately. Coding workspace context has one owner:
`WorkspaceInstructionsHook` lists repositories and injects each applicable
`AGENTS.md` instruction chain exactly once. Work sessions do not coordinate
with the code-graph watcher.

Team delegation routing is generated from the actual blueprint names and
descriptions. Adding a custom specialist never requires a hard-coded routing
branch.

## Required regression invariants

- Agent CRUD validates with the namespace's explicit mode and never creates
  files.
- GET routes do not mutate configuration.
- Only flat Work agents and `coding/<name>` agents are exposed.
- Runtime and API effective configs are identical.
- Unknown frontmatter fields survive a Form/Raw round trip.
- Multi-repo system prompts contain every root instruction once.
- Normal prose cannot synthesize a skill tool call.
- Assigned skills cannot inject bodies into first-turn history.
- The always-visible skill schema cannot enumerate the catalog.
- Persisted Work and Coding sessions cannot change mode on resume.
