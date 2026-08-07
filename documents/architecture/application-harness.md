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

Bundled skills are a curated, code-scoped catalog. Safe specialists participate
directly in implicit resolution; there is no router skill or circular
"skill-to-select-a-skill" bootstrap layer. Native code-graph guidance is
embedded in the Coding workflows that use it; there is no separate graph
routing skill competing with debugging, investigation, review, or delivery.

Runtime catalogs, the agent editor, composer, explicit-selection hook, and
`skill` tool all apply the same valid, mode-aware projection. Settings keeps a
separate management projection: its unscoped catalog represents the actual
precedence winner (including an invalid bundle that needs repair), while an
explicit Work/Coding view selects that mode's effective implementation. If no
valid implementation exists in the requested mode, Settings alone may expose
the invalid winner so its bundle can be repaired; this fallback never enters a
runtime catalog. User/project skills default to both modes; a hidden
`.evoflux.json` sidecar beside `SKILL.md` stores the portable bundle default.
Optional `agents/evoflux.yaml` provides native UI metadata,
implicit-invocation policy, and tool dependencies. Portable third-party
`agents/openai.yaml` remains a fallback when no EvoFlux metadata exists;
references, scripts, assets, and evals remain part of the bundle.

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
2. The full `SKILL.md` body is loaded only after the structured implicit stage
   selects an exact eligible name, the main model selects an exact catalog
   name, the user names `$skill-name` (or legacy `/skill:<name>`), or the user
   explicitly assigns that skill to an agent. Agent assignment is the sole
   unconditional preload path.
3. Task resources are enumerated on activation without their contents. The
   skill body states a narrow evidence condition for each optional reference,
   and the model reads one only after that condition is observed. Control-plane
   metadata (`agents/`) and evaluation fixtures (`evals/`) are neither
   advertised nor readable as task resources.

Bundled skill quality is behavioral rather than a prose-length requirement.
Each description defines positive triggers and near-miss boundaries. The body
keeps only the core workflow, selects a degree of freedom proportional to the
task, names observable stop conditions, and routes every optional resource by
an evidence condition. Fragile workflows use explicit states and transition
gates; judgment-heavy workflows keep flexible criteria. A rule such as
"exact identifier → graph" must identify when the transition fires, which
operation follows, and which observations are forbidden after the transition,
not merely recommend the graph somewhere in a narrative checklist.

Every bundled skill carries balanced activation evals. Deterministic workflow
boundaries may additionally declare `expected_operation`,
`expected_trajectory`, and `forbidden_behaviors`; the validator rejects
malformed trajectory metadata. These fixtures are control-plane artifacts and
never enter model context. Generic filler, duplicated reference content, eager
resource reads, and examples that contradict the live runtime contract are
catalog defects even when the bundle is structurally valid.

Implicit invocation is a first-class pre-model stage. It sends only the latest
user request, application mode, and eligible Tier-1 metadata to the active
runtime provider and requires one structured decision: one exact skill or no
skill. The runtime validates mode, policy, exact identity, and confidence before
using the canonical activation pair. Resolver failure is non-fatal and falls
back to the bounded model-visible catalog. The resolver never receives skill
bodies or repository/tool output and never executes task tools.

Discovery covers `.agents/skills`, `.claude/skills`, `.evoflux/skills`, and
`.opencode/skills` across every authorized repository, followed by user,
administrator, and bundled roots. Malformed bundles are fault-isolated;
collisions, legacy names, policy errors, and symlinks surface as diagnostics.
Symlinked bundles are readable but never editable through Settings.

Request prose may rank eligible Tier-1 skill metadata with deterministic
lexical/reciprocal-rank retrieval so relevant routing cards survive a tight
catalog budget. Ranking never filters the eligible catalog, loads a skill, or
leaves the skill-discovery boundary. In particular, request prose is never
forwarded to repository search or code graph. The native `code_graph` tool
accepts a known exact symbol and one structural operation; schema and service
boundaries enforce that contract independently. Coding skill bodies carry the
operation-selection, ambiguity, cross-repository, and fallback discipline only
after the relevant workflow is activated.

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

Command execution has one continuation contract. `shell` starts a
non-interactive command, journals raw combined stdout/stderr to a
session-scoped artifact, and returns a bounded head/tail observation. If the
command outlives `yield_time_ms`, `shell` returns an opaque process ID and
activates the deferred `process` tool. `process` owns list, poll, wait, and
terminate; poll and wait consume only output produced since the previous
observation. There are no parallel `bg` or `shell_bg_*` APIs. Preview servers
reuse the same journalled process runtime but keep their specialized lifecycle
inside `preview`, so they do not leak into the model's command-process registry.

The durable transcript remains authoritative for reload, audit, and UI
rendering; oversized raw payloads remain available through their artifact
references. At the provider boundary, `ToolContextProjectionHook` keeps the most recent
tool-call batches exact and replaces older oversized text-only results with
deterministic receipts containing status, bounded head/tail context, and the
artifact locator when available. It never mutates persisted messages, never
projects multimodal parts, and never projects `skill` results. This prevents
every later model call from paying again for historical grep, read, graph,
shell, or future tool output while preserving exact skill instructions.

Large generic tool results use the same metadata channel as shell artifacts:
the tool hook records per-call artifact metadata, the live `tool_end` event
exposes it to the UI, and the agent loop attaches it to `ToolMessage.extra` for
reload. User-entered `!command` execution passes through the same shell
formatter and metadata path instead of maintaining a second output protocol.

## Required regression invariants

- Agent CRUD validates with the namespace's explicit mode and never creates
  files.
- GET routes do not mutate configuration.
- Only flat Work agents and `coding/<name>` agents are exposed.
- Runtime and API effective configs are identical.
- Unknown frontmatter fields survive a Form/Raw round trip.
- Multi-repo system prompts contain every root instruction once.
- Normal prose may rank or semantically resolve skill metadata but is never
  transformed into a repository query. A resolver decision is bounded to one
  exact eligible name and passes through canonical policy validation.
- The bounded Tier-1 catalog contains metadata but no `SKILL.md` body.
- Assigned skills preload exact bodies; unassigned skills remain on demand.
- Manual-only operational skills stay out of implicit resolution but remain
  addressable through `$skill-name` or `/skill:<name>`.
- Activated skill instructions remain exact through compaction.
- Skill activation advertises task-resource paths but never eagerly loads their
  contents; control-plane metadata and eval fixtures stay outside task context.
- Loading a skill atomically validates and activates every declared built-in
  tool dependency; durable activations rehydrate the same runtime contract.
- Observation handling is declared by tool metadata rather than tool-name or
  feature-specific branches. Revision-aware tools return a receipt instead of
  rereading an unchanged source range; no fixed investigation quota can block
  a legitimate evidence chain.
- Shell output is journalled once, model-visible observations are bounded, and
  repeated `process` polls never replay already consumed bytes.
- Application shutdown terminates every tracked command and Preview process
  group before the sidecar exits.
- Work and Coding project old tool results only at the model boundary; durable
  history, multimodal results, and exact skill bodies remain unchanged.
- Live tool events and reloaded ToolMessages expose the same artifact metadata,
  including for `!command` execution.
- Symlinked bundles cannot be updated or deleted through Settings CRUD.
- Runtime preference edits never rewrite `SKILL.md`, `agents/evoflux.yaml`,
  fallback `agents/openai.yaml`, or `.evoflux.json`, including for built-in and
  symlinked bundles.
- Same-name skill variants in different repositories have isolated runtime
  preferences, and reset always targets the opaque variant identity.
- An invalid higher-precedence bundle remains visible and repairable in the
  Settings management projection but never replaces a valid runtime fallback.
- Work cannot list or load a Coding-only bundled skill, and vice versa.
- Persisted Work and Coding sessions cannot change mode on resume.
