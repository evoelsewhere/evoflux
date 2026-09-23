# EvoFlux application harness

## Contract

EvoFlux has one agent harness and exactly two application modes:

| Mode | Workspace | Default outcome |
|---|---|---|
| Work | Session workspace/sandbox | Research, artifacts, browser and general execution |
| Coding | Persisted repository or project | Source changes, verification, LSP and git workflows |

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

Work and Coding agent directories may each contain multiple `role: lead`
definitions. A member may declare `lead: <name>`; omission binds it only to the
mode's deterministic default lead. Top-level sessions persist the selected lead
and runtime team construction never includes another lead's members.

Seed and materialised built-in Markdown files contain identity/model settings
and user overrides only. They do not duplicate code-owned capability lists.
Filesystem materialisation belongs to application bootstrap; loaders,
validation, and GET routes are pure.

## Skills and tools

Agent Skills follow Anthropic's filesystem-based architecture; the complete
contract (format, discovery roots and precedence, validation, activation
paths, runtime integration and authoring rules) is
[Agent Skills](agent-skills.md). In summary:

- `app/agent/hooks/skills.py` discovers the catalog per run, makes every
  active Skill directory readable through the sandbox, appends the
  `<available_skills>` metadata block (name, description, absolute
  `SKILL.md` location) to the system prompt, inserts `read` calls for
  `$skill-name` mentions, and preloads an agent's `skills:` into its prompt.
- The model activates a Skill by reading its `SKILL.md` with `read`, reads
  references on demand, and runs bundled scripts with `shell`.
- `SKILL.md` frontmatter is the whole bundle contract; there are no sidecar
  files and no Work/Coding scope. The only user preference is the on/off
  list in `skill-settings.json`, which is atomically replaced and never
  rewrites a bundle.

Bundled Skills are held to the best-practices checklist by
`scripts/validate_skills.py` and `tests/agent/skills/test_builtin_skills.py`.
Their evaluation scenarios live in `tests/fixtures/skill-evals/`, outside the
shipped bundles.

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
with repository indexing.

For session-backed team runs, `SessionPrefixSnapshotHook` pins the finalized
system prompt and ordered tool contract per `(session, profile)`. Later turns
reuse the persisted prefix; a model/agent/permission profile change creates a
new snapshot and a tool-contract change rotates the existing one. Turn-varying
memory recall remains an append-only hidden model-context message, so it does
not rewrite the system prefix or user-visible transcript.

Team delegation routing is generated from the actual blueprint names and
descriptions. Adding a custom specialist never requires a hard-coded routing
branch.

A Skill activation is an ordinary successful full `read` of a `SKILL.md`,
whether the model issued it or the harness inserted it for `$skill-name`. The
newest read of each `SKILL.md` survives conversation compaction within a
bounded durable-skill budget; reads of other bundle files may be summarized.
If an old activation falls outside that budget, the model simply reads the
file again.

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
projects multimodal parts, and never projects a read of a `SKILL.md`. This prevents
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
- The system prompt carries only Skill name, description and `SKILL.md`
  location; no harness stage selects a Skill on the model's behalf.
- Assigned skills preload exact bodies; unassigned skills remain on demand.
- `disable-model-invocation` skills stay out of the catalog but remain
  addressable through `$skill-name`.
- Activated skill instructions remain exact through compaction.
- Skill resources are read only when the model reads them; every active Skill
  directory is readable, never writable, through the sandbox.
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
- Turning a Skill on or off never rewrites any bundle file.
- An invalid higher-precedence bundle remains visible and repairable in
  Settings but never replaces a valid lower-precedence Skill at runtime.
- Persisted Work and Coding sessions cannot change mode on resume.
