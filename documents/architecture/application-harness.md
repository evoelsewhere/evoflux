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
3. Add user-authored tools, explicitly assigned skills, MCP servers, and prompt text.
4. Apply `tools_opt_out` to code-owned tier tools.
5. Deduplicate the effective result.

Seed and materialised built-in Markdown files contain identity/model settings
and user overrides only. They do not duplicate code-owned capability lists.
Filesystem materialisation belongs to application bootstrap; loaders,
validation, and GET routes are pure.

## Skills and tools

Bundled skills are a curated, code-scoped catalog. `work-router` and
`coding-router` are the implicit entry points for broad mode-specific work;
their specialists are explicit-only to avoid thirteen generic descriptions
competing on every request. Narrow artifact, operational, and native-tool
workflows such as `code-graph-navigation` remain independently discoverable
when their concrete output or exact-symbol operation is relevant.

Runtime catalogs, the agent editor, composer, explicit-selection hook, and
`skill` tool all apply the same valid, mode-aware projection. Settings keeps a
separate management projection: its unscoped catalog represents the actual
precedence winner (including an invalid bundle that needs repair), while an
explicit Work/Coding view selects that mode's effective implementation. If no
valid implementation exists in the requested mode, Settings alone may expose
the invalid winner so its bundle can be repaired; this fallback never enters a
runtime catalog. User/project skills default to both modes; a hidden
`.evoflux.json` sidecar beside `SKILL.md` stores the portable bundle default.
Optional `agents/openai.yaml` provides UI metadata and implicit-invocation
policy; references, scripts, assets, and evals remain part of the portable
bundle.

Settings exposes three user-owned runtime preferences: Work/Coding
availability, bounded catalog auto-discovery, and manual invocation through
`/skill:<name>` or `$skill-name`. They are stored outside the portable bundle
in `skill-settings.json`, keyed by an opaque identity for the exact discovered
variant. Project identities include their root location, so same-name skills
in different repositories cannot share an override. This overlay is the final
metadata layer and is applied before mode-aware collision selection. Built-in,
administrator, and symlinked bundles remain byte-for-byte read-only while
these runtime preferences stay editable. Editing bundle content never copies
an effective runtime mode back into `.evoflux.json`; resetting the preferences
restores the bundle defaults.

The overlay is bounded, atomically replaced, locked across workers, and kept
at mode `0600`. Invalid individual records fall back to bundle defaults with an
actionable diagnostic. If the whole JSON store is malformed or unsupported,
discovery also falls back to bundle defaults, but writes refuse to overwrite
it; recovery requires backing up and repairing or removing the malformed
`skill-settings.json` explicitly.

Skill loading follows three disclosure tiers:

1. Valid, implicit skill `name + description + SKILL.md locator` metadata is
   present in a mode-filtered catalog. The catalog is capped at 2% of a known
   model context window, or 8,000 UTF-8 bytes when the window is unknown.
2. The full `SKILL.md` body is loaded only after the model selects an exact
   catalog/router name, the user names `$skill-name` (or legacy
   `/skill:<name>`), or the user explicitly assigns that skill to an agent.
   Agent assignment is the sole preload path.
3. Bundle resources are enumerated on activation and read individually only
   when the selected workflow needs them.

Discovery covers `.agents/skills`, `.claude/skills`, `.evoflux/skills`, and
`.opencode/skills` across every authorized repository, followed by user,
administrator, and bundled roots. Malformed bundles are fault-isolated;
collisions, legacy names, policy errors, and symlinks surface as diagnostics.
Symlinked bundles are readable but never editable through Settings.

Request prose is never keyword-routed to a skill. Code graph has an optional
progressively disclosed workflow skill and a native execution tool. The
`code-graph-navigation` body is loaded only after semantic or explicit
selection; the native `code_graph` tool accepts a known exact symbol and one
structural operation, with its contract enforced independently by the schema
and service boundary.

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

Successful skill activation is stored as a structured assistant/tool pair with
the bundle directory, revision, instructions, and resource manifest. Exact
activation pairs survive conversation compaction within a bounded durable-skill
budget; resource reads and catalog listings may be summarized. If an old
activation falls outside that budget, the runtime clears its ephemeral loaded
marker so the skill can be loaded exactly again.

## Required regression invariants

- Agent CRUD validates with the namespace's explicit mode and never creates
  files.
- GET routes do not mutate configuration.
- Only flat Work agents and `coding/<name>` agents are exposed.
- Runtime and API effective configs are identical.
- Unknown frontmatter fields survive a Form/Raw round trip.
- Multi-repo system prompts contain every root instruction once.
- Normal prose is not transformed into a skill search query or server-selected
  skill call.
- The bounded Tier-1 catalog contains metadata but no `SKILL.md` body.
- Assigned skills preload exact bodies; unassigned skills remain on demand.
- Explicit-only specialists stay out of the implicit catalog but remain
  addressable by a router or `/skill:<name>`.
- Activated skill instructions remain exact through compaction.
- Symlinked bundles cannot be updated or deleted through Settings CRUD.
- Runtime preference edits never rewrite `SKILL.md`, `agents/openai.yaml`, or
  `.evoflux.json`, including for built-in and symlinked bundles.
- Same-name skill variants in different repositories have isolated runtime
  preferences, and reset always targets the opaque variant identity.
- An invalid higher-precedence bundle remains visible and repairable in the
  Settings management projection but never replaces a valid runtime fallback.
- Work cannot list or load a Coding-only bundled skill, and vice versa.
- Persisted Work and Coding sessions cannot change mode on resume.
