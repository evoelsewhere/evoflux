# Skill runtime refactor — from a server-routed pipeline to a model-driven registry

Status: PROPOSED
Date: 2026-09-22
Reference implementation studied: `MiMo-Code` (`packages/opencode/src/skill/**`,
`src/tool/skill*.ts`, `src/session/system.ts`, `src/session/prompt.ts`,
`docs/compose/spec/skill-*.md`)

---

## 0. Executive summary

EvoFlux's skill runtime is correct, safe, and well-tested — and it is built
around a decision that no longer pays for itself: **the harness routes, the
model obeys.** Every user turn without an explicit directive spends one extra
LLM round-trip (`SkillResolutionHook` → `resolution.py`) to pick at most one
skill, and the chosen skill is then injected as a fabricated tool-call pair
that three other producers also fabricate, after which every consumer
reverse-parses message history to work out what is actually loaded.

MiMo-Code solves the same problem with **zero extra model calls, one injection
point, three named accessors, and a config-driven root policy.** The model sees
a catalog in the system prompt and calls `skill` itself; a deterministic BM25
`skill_search` handles the "I don't know the name" case; a single mention scan
owns every body injection.

This plan adopts MiMo's *control flow* while keeping the parts where EvoFlux is
genuinely ahead — bounded DoS-safe discovery, per-skill diagnostics, sandboxed
`read_resource`, declarative runtime tool dependencies, and the user settings
overlay. It is not a port. It is a reorientation.

**This is a complete replacement, not a migration.** No phase ships a
compatibility shim, a legacy flag, a dual-read format, or a deprecation window.
The old path is deleted in the same change that lands the new one; the
compatibility surface EvoFlux has already accumulated (§2.1 H13) is deleted with
it. Anything that cannot be cut over is a design defect to fix before merge, not
a reason to keep two paths alive.

Headline outcomes:

| | Today | After |
|---|---|---|
| Extra LLM calls per user turn | 1 (resolver pre-pass) | 0 |
| Skills activatable per message | 1 | N (budgeted, with an orchestration reminder) |
| Body injection producers | 4 | 1 |
| Places the "is this skill usable" predicate is written | 5 | 1 |
| Adding a bundled skill | edit `BUNDLED_SKILL_MODES` in Python | drop a directory |
| Adding a discovery root | edit `standard_skill_roots()` in Python | config / env |
| Skill grammar definitions | 2 (Python + TypeScript) | 1 (generated) |
| Parallel skill trees | 2 (`builtin_skills/`, `asdd_skills/`) | 1 |
| Compatibility aliases / legacy code paths | ~14 | 0 |
| Files the harness has a schema for, per skill | 3 (`SKILL.md`, `.evoflux.json`, `agents/*.yaml`) | 1 (`SKILL.md`) |

---

## 1. How MiMo-Code actually works

Read this section as the design target, not as a feature list. The interesting
thing about MiMo's skill system is what it *refuses* to do.

### 1.1 The registry is one service with three accessors

`skill/index.ts` exposes exactly:

```ts
get(name)                  // one skill
all()                      // no filtering — user surface, command registry
available(agent?)          // authorization filter only
modelInvocable(agent?)     // available() minus disable_model_invocation
reload()                   // invalidate every discovery tier
```

`Skill.Info` is deliberately tiny: `{ name, description, aliases?, location,
content, disable_model_invocation?, bundled? }`. Frontmatter parsing reads four
keys and ignores everything else, so a skill folder stays portable with Claude
Code and agentskills.io in both directions.

The filter predicates exist **once**. `docs/compose/spec/skill-invocation-control.md`
records precisely three model-facing call sites moving from `available` to
`modelInvocable`, and a comment at `session/system.ts:191` that says *do not
switch this to modelInvocable* on the user-facing one. That is a contract, not
a convention.

### 1.2 Two axes that never overlap

The spec's own behaviour matrix:

| frontmatter | model sees it | model may invoke | user `/name` works |
|---|---|---|---|
| (default) | yes | yes | yes |
| `disable-model-invocation: true` | no | no | **yes** |
| any + `permission.skill: deny` | no | no | **no** |

- `permission.skill` is **authorization**: pattern-based per agent
  (`"*": "allow"`, `"internal-*": "deny"`, `"experimental-*": "ask"`),
  evaluated in one function. `deny` means unusable by anyone.
- `disable-model-invocation` is **model reachability**, carried by the skill's
  own frontmatter so it travels with the bundle.

The spec is explicit that this split came from a bug: one rule was serving two
questions, so hiding a skill also disabled the user's slash invocation. Also
notable — the failure mode they designed *against*: a skill advertised in the
catalog but unloadable makes the model retry and then tell the user the skill
does not exist. Their error strings redirect (`tool/skill.ts:52-57`: "Only the
user can start it by typing /name. Do not retry this tool") rather than
dead-end.

### 1.3 Discovery is tiered, cached, and config-driven

```
discoverStableSkills   (process-wide, Duration.infinity)
  ├─ extract builtin bundle → {DATA}/builtin_skills/{version}/skills/
  ├─ extract compose bundle → {DATA}/compose/{version}/skills/
  └─ scan home brand roots  (~/.claude, ~/.codex, ~/.opencode, ~/.agents)

discoverSkills         (per instance: directory + worktree)
  ├─ fsys.up({targets, start: directory, stop: worktree})   ← project walk
  ├─ config.directories()                                    ← .mimocode
  ├─ cfg.skills.paths[]                                      ← user config
  └─ cfg.skills.urls[]   → Discovery.pull() → index.json → cache

loadSkills             (parse matched SKILL.md, last-wins, bundled never
                        overwrites non-bundled)
```

Three properties matter here:

1. **Roots are a predicate, not a list.** `externalSkillDirs()` filters
   `[".claude", ".codex", ".opencode", ".agents"]` through four env flags —
   `.agents` on unless `MIMOCODE_DISABLE_AGENTS_SKILLS`, the brand roots off
   unless `MIMOCODE_ENABLE_*_SKILLS`. `skill-external-root-defaults.md` makes
   that predicate the "sole source of truth".
2. **Dotted path segments never match** (`dot: false` on external scans). This
   is how Codex's private `skills/.system/` cache and Claude's `.trash/` stay
   out of the catalog. Cheap, general, no special-casing.
3. **Bundled skills are extracted to disk**, versioned by installation version,
   with a `.extracted` marker whose content is
   `{version, skills: [...enabled]}` so a retired builtin is *deleted* from the
   previous extraction rather than lingering. A user skill with the same name
   always wins (`if (isBundled && !existing.bundled) return`).

Invalidation is explicit: `reload()` drops all three tiers, and it fires from a
write/edit path test — `/\.mimocode\/(tools?|skills?)\//`. Nothing re-stats a
tree per hook.

### 1.4 The model surfaces

**System prompt catalog.** `SystemPrompt.skills(agent)` renders
`Skill.fmt(list, {verbose: true})`:

```xml
<available_skills>
  <skill>
    <name>git-release</name>
    <description>…</description>
    <location>file:///…/SKILL.md</location>
  </skill>
</available_skills>
```

Always sorted by `localeCompare`. No query ranking, no budget truncation. The
comment at `system.ts:184` is worth quoting: the verbose form goes in the
system prompt and the *less* verbose form in the tool description, because
"the agents seem to ingest the information about skills a bit better" that way.

**`skill` tool.** Parameters are `{ name }`. Its description is a static
five-line `skill.txt` — it does **not** embed the catalog. Not-found errors
list `modelInvocable` names only, so a typo cannot leak a hidden skill.

**`skill_search` tool.** Deterministic, provider-free ranking over
`modelInvocable`:

- exact match on name / `aliases` / localized aliases → score 1.0
- otherwise BM25 over `name + aliases + description`, fused with query coverage
- every knob is a `Flag` constant: `K1 1.5`, `LENGTH_NORMALIZATION 0.75`,
  `IDF_SMOOTHING 0.5`, `BM25_SCORE_WEIGHT 0.55`, `QUERY_COVERAGE_WEIGHT 0.35`,
  `AUTO_LOAD_THRESHOLD 0.85`, `MAX_RESULTS 3`
- above threshold → load it inline; below → return candidates and let the model
  decide

Tokenization handles Han script with a bigram fallback and strips the four
query-structure labels (`action`, `input`, `output`, `audience`) that its own
prompt asks for, so the template does not dilute domain terms.

**Activation render** (`skill-content.ts`) is four lines of substance: the
body, a `file://` base directory, a *sampled* file list (ripgrep, limit 10),
and a note that relative paths resolve against the base directory. There is no
size cap, no resource-read tool — a skill's files are read with the ordinary
read/bash tools.

### 1.5 The user surface, and the single-injector rule

Every skill is automatically a slash command (`command/index.ts:264`, from
`Skill.all()` — unfiltered, so a `disable-model-invocation` skill still
autocompletes). The TUI resolves localized aliases client-side (`/深度研究` →
`/deep-research`) before the text leaves the client.

Then — and this is the part EvoFlux most needs — **there is exactly one skill
body injector**: the mention scan inside `insertReminders`
(`session/prompt.ts:1516`). `docs/compose/spec/skill-multi-injection.md`
records why: there used to be two (a command path and a free-text scan), the
command path's `alreadyWrapped` guard was message-level, and so `/a … /b`
silently dropped `b`. The fix was to *delete the second injector*, not to
reconcile them.

The scan itself:

```ts
const mentionRe = /(?:^|\s)\/([A-Za-z][A-Za-z0-9_:-]*)(?=[^A-Za-z0-9_:-]|$)/g
```

over non-synthetic text with code fences stripped; deduped, order-preserving,
`MAX_AUTOLOAD = 3` with overflow pushed to a "load it through the skill tool"
hint; idempotent because already-injected parts are recognized by their
`^<system-reminder>\n<skill_content name="…">` prefix.

At two or more mentions it appends an **orchestration reminder** telling the
model to read every SKILL.md before planning, classify the composition
(pipeline / parallel / constraint overlay), define the intermediate artifact
contract if it is a pipeline, and declare a precedence rule when two skills
give conflicting instructions on the same dimension. That reminder is the
whole multi-skill story, and it costs one string.

### 1.6 What MiMo deliberately does *not* do

- No mode/scope concept on skills at all.
- No per-turn LLM routing.
- No catalog budget or truncation.
- No query-dependent catalog ordering (it would break prefix caching).
- No harness-side validation beyond "frontmatter parsed and has name +
  description" — a bad skill is silently skipped with a log line.
- No skill-resource read tool; no sandbox mounting.
- `user-invocable: false` was considered and **rejected** for being an unused
  second axis that would reintroduce the ambiguity the feature removed.

---

## 2. What EvoFlux does today

```
app/agent/skills/
  discovery.py    868   roots, bounded walk, frontmatter, records, precedence, cache
  catalog.py      327   budgeted render + RRF query ranking + stable re-sort
  resolution.py   203   ← an extra LLM call, every turn
  activation.py   372   wrap body, manifest, sandbox mount, synthetic pair, tool contract
  models.py       118   SkillRecord (25 fields)
  validation.py    68
app/core/
  skill_scope.py  103   .evoflux.json sidecar (modes)
  skill_settings.py 355 user override overlay keyed by opaque hash
app/agent/hooks/
  configured_skills.py     102   preload agent `skills:` bodies
  explicit_skill_selection.py 139 /skill:name or $name → activate
  skill_resolution.py      120   LLM pre-pass → activate
  skill_runtime_contract.py 52   rehydrate declared tool deps
  skill_catalog.py         156   render catalog into system prompt (+ finalizer)
app/agent/builtin_skills/catalog.py   hardcoded name→modes dict
app/agent/tools/builtin/skill.py 382  the tool facade
app/plugin_platform/skills.py    96   plugin skill merge
app/api/routes/skills.py       1079   CRUD + runtime settings
app/asdd_skills/                      a second, unregistered skill tree
web/src/components/InputBar.skills.ts  the grammar, again, in TypeScript
```

Tests: ~3,255 lines across `tests/agent/skills/*`, `tests/agent/tools/test_skill_loader.py`,
`tests/agent/hooks/test_explicit_skill_selection.py`, plus `tests/api/routes/test_skills.py`.

### 2.1 Hardcoding — concrete findings

**H1 — `BUNDLED_SKILL_MODES`** (`app/agent/builtin_skills/catalog.py:12`).
A hand-maintained `dict[str, tuple[mode,...]]` naming all 21 bundled skills.
Adding a builtin skill requires a Python edit in a different package from the
skill, and the dict silently defaults to both modes on a typo.

**H2 — `standard_skill_roots()`** (`discovery.py:181`). Ten fixed root patterns,
no config, no env, no opt-in. Compare MiMo's four-flag predicate plus
`skills.paths` / `skills.urls`. There is no way for a user to add a skills
directory without editing EvoFlux.

**H3 — `_source_for_root()`** (`discovery.py:319`). An if-chain of path-equality
tests producing magic strings — `"global-agents"`, `"project-claude"`,
`"global-EvoFlux"`, `"admin-codex"`. Those same strings are re-hardcoded in
`skill_settings._PATH_SCOPED_SOURCES` (`:35`) and again in
`api/routes/skills.py:_skill_source`. Three files must agree by hand.

**H4 — `_RESOURCE_DIR_NAMES`** (`discovery.py:55`). A fixed set of folder names
traversal refuses to descend into — convention frozen as code, and it is
load-bearing right now, not hypothetically. `data-analytics` ships **17**
nested `SKILL.md` files under `references/workflows/**`, each with its own
frontmatter. They stay out of the catalog for exactly one reason: `references`
happens to be in that set. Rename the folder to `workflows/`, or add a hub whose
subfolder is `docs/`, and seventeen sub-workflows become seventeen catalog
entries. The rule protecting the catalog is a spelling coincidence.

**H5 — two binary modes.** `SkillMode = Literal["work", "coding"]`, and the
idiom `"coding" if mode == "coding" else "work"` appears in
`skill_catalog.py:38`, `configured_skills.py:36`, `skill_resolution.py:26`,
`skill_runtime_contract.py:25`, `explicit_skill_selection.py:44`,
`skill.py:126/141`, `discovery.py:801`, `resolution.py:70/85`,
`catalog.py` (via caller) — ten-plus sites. A third scope is a cross-cutting
rewrite.

**H6 — catalog prompt text** (`catalog.py:19-31`). A fixed nine-rule English
block on every turn, including `- Never turn the user's request into a
code_context query.` — another subsystem's concern leaking into the skill
prompt, permanently, for every model.

**H7 — `_ROUTING_STOPWORDS`** (`catalog.py:67`). An English + Vietnamese
wordlist inline in the ranking path. No CJK handling (MiMo does bigrams), no
extension point, no relationship to the user's actual locale.

**H8 — magic numbers, none configurable.** `MAX_ACTIVATED_SKILL_BYTES = 95_000`,
`MAX_CONFIGURED_SKILL_BYTES = 96_000`, `MIN_SKILL_CONFIDENCE = 0.72`,
`MAX_RESOLUTION_CANDIDATES = 64`, `CATALOG_CONTEXT_RATIO = 0.02`,
`UNKNOWN_CONTEXT_CATALOG_CHARS = 8_000`, `MAX_DISCOVERY_DEPTH = 6`,
`RECOMMENDED_SKILL_LINES = 500`, `manifest_limit = 200`, the round-robin
allocation chunk `24`, `MAX_AGENT_METADATA_BYTES`, `MAX_DEPENDENCY_RECORDS`.
MiMo puts every equivalent knob in `Flag` with an env override and a default.

**H9 — the 95 KB activation hard-fail** (`activation.py:246`). A skill over the
limit does not load at all; the error tells the author to restructure their
bundle. The harness is dictating authoring style at runtime, and the number is
not tunable.

**H10 — the grammar is written twice.** `explicit_skill_selection.py:17-27`
(Python) and `web/src/components/InputBar.skills.ts:24-37` (TypeScript), the
latter with a docstring explicitly promising to mirror the former. Two sources
of truth for one contract.

**H11 — one skill per message, first content line only.**
`ExplicitSkillSelectionHook._selector()` walks past quote lines, inspects the
**first real content line**, and returns `None` if that line carries no
directive. `/skill:a … $b` is impossible; a directive on line 3 is inert.

**H12 — `asdd_skills/` is a parallel universe.** Seven `SKILL.md` directories
with `TEMPLATE.md` and `references/`, read directly by `asdd_store` and
`asdd_setup_service`, invisible to discovery, permissions, settings, the
catalog, and the `skill` tool.

**H13 — an accumulated compatibility surface with no owner.** Fourteen
constructs exist solely to keep an older shape reachable, each carrying its own
comment explaining why it may not be deleted:

| Construct | Location |
|---|---|
| `_parse_frontmatter`, `_render_tokens`, `_iter_skill_paths`, `_skills_dir_signature`, `_discover_skills_cached` | `tools/builtin/skill.py:88` — "compatibility aliases for … extension imports" |
| `discover_skills()` returning `as_legacy_dict()` shape | `tools/builtin/skill.py:115`, `models.py:80` |
| `skills_for_mode()` over the dict shape | `tools/builtin/skill.py:123` |
| the `_state is None` branch in `load_skill` | `tools/builtin/skill.py:357` — "preserve the historical direct-Python-call contract" |
| `read_skill_instructions()` | `activation.py:292` — "for compatibility callers outside tool execution" |
| `MAX_CONFIGURED_SKILL_CHARS` alias | `configured_skills.py:21` |
| `catalog_budget_chars` name/field | `catalog.py:55` — "historical function/field name is retained" |
| `_LEGACY_NAME_RE` + `legacy-name` diagnostic | `discovery.py:51`, `:655` |
| nested `parent/child` names + `nested-legacy-skill` diagnostic | `discovery.py:661-673` |
| "legacy compatibility roots are retained" | `discovery.py:200` |

Every one of these is a second way to do something the refactor gives exactly
one way to do. They are in scope for deletion (P9), not for carrying forward.

**H14 — EvoFlux invented a sidecar contract that no standard and no other
client has.** The portable format is one file: `SKILL.md`. agentskills.io makes
it the only mandatory file; Claude Code and MiMo read nothing else; both
explicitly **ignore unknown frontmatter keys**, and MiMo proves it in its own
bundle — 7 of its 24 skills ship `license`, 3 ship `version`, 3 ship
`platforms`, and its schema silently strips all of them.

`agents/openai.yaml` and `evals/` are not EvoFlux inventions either — they are
Codex-plugin conventions, vendored along with the `data-analytics` package.
MiMo vendored the **same** files: 5 of its bundles contain `agents/openai.yaml`
and 2 contain `evals/`. The difference is decisive:

> **MiMo has no code that reads them.** They sit in the directory like
> `scripts/` or `references/` — ordinary bundle files with no schema, no
> validation, no record fields, no traversal special-case.
>
> **EvoFlux built a runtime contract around them**: `_read_agent_metadata`
> (163 lines), `AGENT_INTERFACE_FIELD_LIMITS`, `MAX_AGENT_METADATA_BYTES`,
> `MAX_DEPENDENCY_RECORDS`, ~10 diagnostic codes, 8 `SkillRecord` fields, a
> second sidecar (`.evoflux.json`) for scope, exclusions at
> `discovery.py:833` and `activation.py:313` to hide `agents/` and `evals/`
> from the manifest, and a validator that **requires** them.

The question is not "which sidecar do we keep" — it is why there is a sidecar
contract at all. Auditing what each field actually does:

| Field | Skills using it | Consumer | Verdict |
|---|---|---|---|
| `interface.display_name`, `short_description` | 21 | settings list, `AgentForm`, identity ranking | **live** |
| `interface.default_prompt` | 21 | `useSlashCommandRegistry.ts:170`, composer | **live** |
| `interface.icon_small`, `icon_large`, `brand_color` | **0** | nothing | **dead** — yet they own 3 of the 6 `AGENT_INTERFACE_FIELD_LIMITS` entries and their own diagnostics |
| `policy.allow_implicit_invocation` | 6 (all `false`) | record | **duplicate** of frontmatter `disable-model-invocation`, which **no** bundled skill sets |
| `dependencies.tools[].type`, `.value` | 5 (all `builtin` / `code_context`) | `_resolve_builtin_dependencies` | **no-op** — see A9 |
| `dependencies.tools[].description`, `.transport`, `.command`, `.url` | some | parsed, length-checked, normalized, stored | **dead** — only `type` and `value` are ever read |
| `agents/openai.yaml` fallback | 1 (`learn-everything`) | `_read_agent_metadata` | 17 of the 18 files on disk sit under `data-analytics/references/workflows/**`, which traversal never reaches — decoration |

Net: 163 lines of parser plus its validation exist to deliver **three** live
values — `display_name`, `short_description`, `default_prompt` — while
duplicating a portable frontmatter key, validating three fields nobody sets,
normalizing four fields nobody reads, carrying a dependency block that does
nothing (A9), and forcing two directory special-cases.

All three fit in `SKILL.md` frontmatter, which is where the standard puts skill
metadata and where other clients harmlessly ignore it.

`evals/trigger-cases.json` is the same story with a different ending: it is
correctly never read at runtime, so it is not a runtime contract — but it is
also not skill content. It is a **test fixture living inside a shipped
package**, which is why the manifest needs a rule to hide it and why the
validator has an opinion about it. Test fixtures belong with tests.

### 2.2 Architectural findings

**A1 — the resolver pre-pass.** `SkillResolutionHook.before_agent` fires
`provider.chat()` on every user turn that has no explicit directive, serializing
up to 64 skill descriptions, to select **at most one** skill above confidence
0.72. Cost: one model round-trip of added latency before the first token of
every turn, plus tokens. Two long comments in `resolution.py` (the
`_RESOLUTION_CACHE_KEY` block and the `_request_payload` field-order block)
exist purely to claw back cache affinity for a call the architecture created.
MiMo reaches the same outcome with the catalog in the system prompt and a
deterministic search tool — zero extra calls, and N skills instead of one.

**A2 — four injectors, one reverse-engineered truth.**
`ConfiguredSkillsHook`, `ExplicitSkillSelectionHook`, `SkillResolutionHook`, and
the `skill` tool all call `inject_skill_activation`. All four then re-derive
"what is loaded" by calling `_loaded_skills_from_messages`, which walks
`messages_for_llm`, pairs `tool_call.id` to `tool_call_id`, JSON-decodes the
arguments, and string-matches the activation wrapper. EvoFlux is one ordering
change away from exactly the bug MiMo documented in `skill-multi-injection.md`
— and unlike MiMo, it has four paths to keep in sync rather than two.

**A3 — catalog ranking fights prompt caching, and the fix is a workaround.**
`catalog.py:_render_stable` exists *only* to undo damage its own ranking
causes; its docstring records a measured collapse from 83k cached tokens to 4k.
But ranking still runs and still changes the *included set* under budget
pressure, which still rewrites the prompt at position 0. `SkillCatalogHook` then
carries a `cache_stable` flag so runtime agents opt out of ranking entirely —
which means the ranking code path is dead for the main use case and live only
for standalone callers. MiMo's answer is simply: always `localeCompare`;
ranking belongs in `skill_search`, where a different answer costs nothing.

**A4 — visibility is expressed four ways.** `allow_implicit_invocation`
(from frontmatter `disable-model-invocation`, from `agents/evoflux.yaml`
`policy.allow_implicit_invocation`, and from `skill-settings.json`),
`user_invocable`, `modes`, and the agent's `skills:` preload list. None is
pattern-based; none is per-agent; and authorization is not separable from
reachability. MiMo needed exactly two axes and rejected a third as ambiguity.

**A5 — the eligibility predicate is written five times.**
`record.valid and record.allow_implicit_invocation and mode in record.modes and
description.strip()` appears with small variations in `catalog.py:236`,
`resolution.py:70`, `skill.py:146`, `explicit_skill_selection.py:45`, and
`configured_skills.py:56`. MiMo has `available()` and `modelInvocable()`.

**A6 — caching re-stats the tree per hook, per turn.**
`discover_skill_records` calls `skills_tree_signature(root)` for every root to
build the `lru_cache` key — a full bounded walk that stats every `SKILL.md`,
`evoflux.yaml`, `openai.yaml` and `.evoflux.json`. Five hooks call
`discover_skill_records_runtime` per turn. MiMo caches at service scope and
invalidates on a file-write path test.

**A7 — no remote or registry skills.** MiMo pulls `skills.urls` →
`index.json` → `{cache}/skills/<name>/`. EvoFlux's answer is a bundled
`skill-installer` *skill* — a workflow standing in for a mechanism.

**A8 — no aliases, no localized invocation.** Exact name only, with
`difflib.get_close_matches` as a guess-the-typo fallback.

**A9 — the runtime tool-dependency contract fires on nothing.** A whole
subsystem — `dependencies.tools` parsing with `MAX_DEPENDENCY_RECORDS` and four
field validators, a `SkillRecord` field, `_resolve_builtin_dependencies`,
`apply_skill_runtime_contract`, `SkillDependencyError`, the atomic
validate-load-commit dance in `activate_skill_with_runtime`, and
`SkillRuntimeContractHook` running on **every turn for every loaded skill** —
resolves at runtime to nothing. Tracing it end to end:

| Claimed effect | Reality |
|---|---|
| activates deferred tools a skill needs | `deferred = required & deferred_tool_catalog`. All five skills that declare a dependency declare exactly `code_context`, and `code_context.py:299` is `deferred=False`. The intersection is **always empty**. |
| grants plugin MCP tools | **Independent.** `apply_skill_runtime_contract` keys that off `record.source.startswith("plugin:")`, never off `dependencies.tools`. |
| records the contract for inspection | `state.metadata["skill_runtime_contracts"]` is written at `activation.py:72` and **read nowhere** — in `app/` or `web/`. |
| carries rich dependency metadata | `description`, `transport`, `command`, `url` are validated, normalized, stored, never read. Non-`builtin` types are dropped on the floor. |

What is left is one live behaviour: `SkillDependencyError` **refuses to load a
skill** when a declared builtin tool is missing from the grant. That is not a
feature — a coding skill whose preferred navigation tool is absent should
degrade to grep and read, not vanish. MiMo has no such gate, and its spec lists
Claude Code's `allowed-tools` among the upstream fields it deliberately did not
implement.

Renaming the block to `allowed-tools` would also have been wrong on its own
terms: in Claude Code that key **restricts** which tools a skill may use, while
EvoFlux's block **requires** them. Importing a standard key with inverted
meaning is worse than either keeping or dropping it.

Delete the declared-dependency mechanism entirely (P4). Keep the plugin grant,
which was never part of it.

### 2.3 What EvoFlux does better, and must not lose

This is not a one-way comparison. The following have no MiMo equivalent and are
**invariants** for the refactor:

- **Bounded, DoS-safe discovery.** `MAX_DISCOVERY_DEPTH`,
  `MAX_DISCOVERY_DIRECTORIES`, `MAX_DISCOVERY_ENTRIES`, the streaming
  `_bounded_directory_entries` that caps while consuming `scandir` rather than
  materializing a wide directory, symlink-cycle detection via resolved-target
  set. MiMo just globs.
- **Per-skill diagnostics with severities.** `SkillDiagnostic`, `valid`,
  `shadowed_paths`, `alternates`, and 20-odd diagnostic codes surfaced to the
  settings UI. MiMo's `add()` does `if (!parsed.success) return` — the skill
  vanishes with no user-visible reason.
- **`skill(action="read_resource")`** with traversal rejection, symlink
  rejection, UTF-8 bounds, and a read-only sandbox mount
  (`_grant_skill_read_access`). MiMo has no resource-read tool — it prints
  absolute paths and lets the ordinary read tool work. It is **not** true that
  MiMo has no access mechanism, though: `agent/agent.ts:106-107` feeds
  `skill.dirs()` into the default `external_directory` permission as an
  allow-list, so every skill directory is readable up front. Same intent, a
  different axis (permission, granted eagerly) and a different guarantee
  (evoflux's is scoped to activation and enforced by the sandbox). Keep the
  evoflux mechanism; adopt the accessor it needs (§7.2 G1).
- **Plugin MCP grants on activation.** Loading a skill that came from a plugin
  grants that plugin's MCP tools for the rest of the run
  (`apply_skill_runtime_contract` → `_grant_plugin_mcp_tools`). This keys off
  `record.source`, not off any declared dependency, and it must survive restore
  and compaction — which is the whole job of the hook that currently carries it.
  (The *declared* tool-dependency mechanism beside it is **not** an invariant;
  see A9.)
- **The settings overlay**, addressable by an opaque ID that survives
  installation-path changes for bundled/admin roots but is path-scoped for
  project roots — so an upgrade keeps the user's preference and two repos with
  a same-named skill do not collide.
- **Plugin skill precedence** merged above builtins and below project/user.

The refactor's job is to put MiMo's control flow *inside* this envelope.

---

## 3. Target architecture

```
                     ┌──────────────────────────────────────┐
  roots policy  ───► │  SkillRegistry  (one service)        │
  (config+env)       │    get / all / available /           │
                     │    model_invocable / reload          │
                     └───────────────┬──────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
  system-prompt catalog        skill / skill_search        SkillInjectionHook
  (sorted, stable bytes)       (model-initiated)           (the ONLY injector)
                                                            ▲
                                                            │
                                    user text: /name, /skill:name, $name
                                    agent config: skills:
```

Five rules the new design is built on; the first four are traceable to a MiMo
spec, the fifth is what makes this a refactor rather than an accretion:

1. **One injector.** (`skill-multi-injection.md`) Anything that wants a skill
   body in context registers a *mention*; one hook resolves mentions to bodies,
   applies the budget, writes the parts, and emits the orchestration reminder.
2. **Two axes.** (`skill-invocation-control.md`) `permission.skill` =
   authorization; `model_invocable` = reachability. Nothing else hides a skill.
3. **Roots are a predicate.** (`skill-external-root-defaults.md`) Config + env,
   non-dot matching, layered last-wins, documented clash order.
4. **Stable bytes.** The catalog is sorted by name, always. Ranking lives in a
   tool, never in the prompt.
5. **One way, no second way.** Each phase deletes what it replaces, in the same
   change. No shim, no alias kept "for extensions", no env flag selecting the
   old behaviour, no format read in two spellings. A construct that exists only
   so an older caller keeps working is the defect, and the caller is what gets
   updated.

---

## 4. Plan

Ten phases. P0–P2 are the refactor proper and are strictly ordered; P3–P8 are
independent once P0 lands and can be parallelized. P9 is the proof that nothing
was left behind — it is a checklist, not deferred work, because each of its rows
is deleted by the phase that makes it redundant.

Every phase lands its replacement and removes what it replaces in the same
change. A phase that leaves both paths reachable has not shipped.

### P0 — One registry, one root policy

**Deliverable:** `app/agent/skills/registry.py` — a `SkillRegistry` with
`get(name)`, `all()`, `available(agent)`, `model_invocable(agent)`,
`for_scope(scope)`, `dirs()`, `reload()`. Every eligibility predicate in the
codebase moves here and is deleted from its five current homes (A5).
`dirs()` mirrors MiMo's `Skill.dirs()` and is what the sandbox grant and any
directory allow-list read, instead of each caller deriving paths from records.

**Root policy.** Replace `standard_skill_roots()` (H2) with a
`SkillRootPolicy` that yields typed `SkillRoot(path, source, scope, editable,
writable, bundled)` objects (H3 — `_source_for_root` is deleted; source is
*declared* by the policy that created the root, not inferred from the path
afterwards). Composition, in precedence order:

| Layer | Default | Control |
|---|---|---|
| project `.evoflux/skills` (walk to git root) | on | — |
| project `.agents/skills` | on | `EVOFLUX_DISABLE_AGENTS_SKILLS` |
| project `.claude` / `.opencode` / `.codex` | **off** | `EVOFLUX_ENABLE_{CLAUDE,OPENCODE,CODEX}_SKILLS` |
| plugin skills | on | plugin enablement |
| `settings.SKILLS_DIR` (user global) | on | — |
| home `.agents/skills` | on | `EVOFLUX_DISABLE_AGENTS_SKILLS` |
| home brand roots | **off** | as above |
| `skills.paths[]` from config | — | config |
| `skills.urls[]` from config | — | config (see P7) |
| bundled | on | `EVOFLUX_DISABLE_BUILTIN_SKILLS` |

Flipping the brand roots to opt-in matches MiMo's shipped default and fixes a
latent problem EvoFlux has today: `~/.claude/skills/.trash/**` and any dotted
segment are currently discoverable. **Adopt non-dot matching** — skip any path
component starting with `.` during the skill walk. This is a behaviour change
and belongs in the changelog.

**Traversal becomes structural, not name-based.** Delete `_RESOURCE_DIR_NAMES`
(H4) and replace it with the rule the Agent Skills shape already implies: a
skill is a **direct child** of a skills root, so only `<root>/<name>/SKILL.md`
is a skill and every deeper `SKILL.md` is a bundle resource. It makes
`data-analytics`'s 17 nested workflow files resources by construction rather
than by folder-name luck, removes `MAX_DISCOVERY_DEPTH` from the hot path, and
makes a hub free to name its subfolders anything. Nested project layouts that
need grouping get it from multiple roots, not from recursive descent.

This is **stricter than MiMo**, deliberately. MiMo applies the single-level
rule only to its builtin bundle (`BUNDLED_SKILL_PATTERN = "skills/*/SKILL.md"`,
with a test named *"registers top-level builtins without exposing their
workflows"*) and keeps `skills/**/SKILL.md` for user and brand roots so people
can group their own skills in folders. EvoFlux cannot afford that split once
P5 lands: making builtins copy-and-editable is the whole point of P5, and the
moment a user copies `data-analytics` into their own root, a `**` rule turns
its 17 workflows into 17 catalog entries. One rule everywhere is the price of
copyable hubs. Grouping is still available through `skills.paths`.

**Caching.** Move from `lru_cache` + per-call tree signature (A6) to registry
state with explicit `reload()`, invoked from the existing file-write path when
the written path is under any active root. Keep one cheap signature check as a
safety net for out-of-band edits, gated behind a TTL, not per call.

**A `skills list --json` CLI** over `registry.all()` (§7.2 G7), mirroring
MiMo's `debug skill`. An hour of work, and it makes every later phase's
acceptance check something you can run rather than reason about.

**Tests to update:** `tests/agent/tools/test_skill_loader.py` (the bulk of the
1,848 lines is discovery), new `tests/agent/skills/test_registry.py`,
`tests/agent/skills/test_root_policy.py`.

### P1 — Delete the resolver pre-pass; add `skill_search`

**Delete:** `app/agent/skills/resolution.py`, `app/agent/hooks/skill_resolution.py`,
`tests/agent/skills/test_resolution.py`. Remove the `skill_resolver` phase from
`record_turn_usage`.

**Add:** a `skill_search` tool, ported from `skill/search.ts` in spirit:

- exact match on `name` / `aliases` → top score
- BM25 over `name + aliases + description`, fused with query coverage
- constants in `app/core/config.py` with env override, defaults matching MiMo's
  (`k1=1.5`, `b=0.75`, idf smoothing `0.5`, bm25 weight `0.55`, coverage weight
  `0.35`, auto-load threshold `0.85`, max results `3`)
- tokenization: Unicode word split, NFKD diacritic folding (keep — it earns its
  place for Vietnamese), plus a **CJK bigram fallback** which the current
  `_tokens` lacks (H7). The stopword list moves to config, seeded from the
  current constant.
- above threshold → activate inline and return the body with the ranked payload;
  below → return candidates, let the model choose and call `skill`

**Rationale.** Selection moves from a server-side LLM decision to the model's
own decision, informed by the same metadata, at zero extra latency. The
confidence floor becomes a search threshold on a deterministic score rather
than a self-reported number from a second model.

**Gate:** this is the highest-risk phase for routing quality, so it gets the
strongest evidence requirement — not an escape hatch. A failing eval is fixed by
tuning `skill_search` (thresholds, weights, tokenization) or by sharpening the
descriptions it ranks — **never** by reinstating the resolver behind a flag. The
resolver is deleted in this change, not after it.

**The existing trigger fixtures become the gate.** All 21 bundled skills ship
an `evals/trigger-cases.json` (~40 KB of
`{query, should_trigger, expected_workflow, near_miss}` cases), and
`scripts/validate_skills.py:356` already enforces that the file exists with
balanced positive and near-miss cases. What nothing does is **run** them. P1
adds a runner that replays every case through `skill_search` and asserts the
ranking; the merge gate is no regression against the same corpus scored through
the resolver. That turns a lint artifact into the evidence this phase is safe,
at zero authoring cost — the cases are already written.

The fixtures themselves relocate to `tests/fixtures/skill-routing/` in P4,
where a test fixture belongs; P1 reads them from whichever location is current
when it lands.

This is also the answer to "is the model worse at selecting than a dedicated
resolver call": it stops being an opinion.

### P2 — One injector

**Add** `app/agent/hooks/skill_injection.py` with a single
`SkillInjectionHook`, and delete the injection logic from
`ConfiguredSkillsHook`, `ExplicitSkillSelectionHook`, and the resolver path
(A2). Producers become *mention sources*:

```python
mentions = [
    *configured_mentions(agent_cfg, turn_index),   # agent `skills:`, first turn
    *text_mentions(user_text),                     # /name, /skill:name, $name
]
```

**Grammar.** One scanner over the whole message (H11), fences stripped, deduped,
order-preserving — MiMo's `mentionRe` semantics, extended for EvoFlux's
`/skill:` and `$` forms. A directive on any line counts; multiple directives
count.

**Budget and reminder.** `MAX_AUTOLOAD` (config, default 3) with the remainder
emitted as a "load these through the skill tool" hint, and at ≥2 mentions the
orchestration reminder — port MiMo's five-point wording (read every SKILL.md
before planning; classify pipeline / parallel / constraint overlay; define the
intermediate artifact contract; declare precedence on conflicting dimensions;
emit a phase→skill→artifact workflow). This single string is what makes
multi-skill work useful rather than merely possible.

**Idempotency.** Promote `loaded_skills` to a first-class `AgentState` field
written by the injector. `_loaded_skills_from_messages` survives only as a
restore/compaction rehydrator, called once per run, not as the truth source
five callers consult.

**Grammar, once.** Generate the TypeScript grammar constants from the Python
definition at build time (or serve them from `/api/skills/grammar` and have the
composer fetch them), deleting the hand-mirrored regexes in
`web/src/components/InputBar.skills.ts` (H10).

**Tests:** rewrite `tests/agent/hooks/test_explicit_skill_selection.py` as
`test_skill_injection.py`, with the multi-mention, overflow, idempotency, and
orchestration-reminder cases MiMo's `prompt-skill-command-multi.test.ts` covers.

### P3 — Two axes; pattern permissions

- Add `permission.skill` as a pattern map, per agent, with `allow` / `ask` /
  `deny`, evaluated once in the registry. Reuse whatever permission evaluator
  the tool layer already has; do not write a second matcher.
- Collapse the three sources of `allow_implicit_invocation` (frontmatter
  `disable-model-invocation` → `agents/evoflux.yaml` `policy` →
  `skill-settings.json`) into **one** resolved `model_invocable` boolean on the
  record, with that precedence documented. Authorization is `permission.skill`
  and nothing else touches it (A4).
- Adopt MiMo's redirect-don't-dead-end error strings: a model loading a
  non-reachable skill is told the user must invoke it and that retrying will not
  help; a not-found error lists only reachable names.
- Keep `user_invocable` (EvoFlux already ships it and the UI exposes it) —
  unlike MiMo, EvoFlux has a settings surface where it is meaningful.
- **The user surface never filters by reachability** (§7.2 G6). Composer
  autocomplete, the `/skill:` and `$name` resolver, the settings list and the
  skills API all read `all()` filtered by authorization and `user_invocable`
  only. A `disable-model-invocation` skill still autocompletes and still
  activates when the user asks for it by name. This is the exact regression
  MiMo's `skill-invocation-control.md` was written to fix — one rule serving two
  questions — so it is an acceptance condition, not a convention: a test asserts
  that such a skill is absent from the catalog and from `skill_search`, and
  present in autocomplete and in a user directive.

### P4 — Scopes instead of a mode `Literal`, and no sidecar at all

- `SkillMode = Literal["work","coding"]` → an open `scopes: frozenset[str]` on
  the record, with `work` / `coding` as the two shipped values. The
  `"coding" if mode == "coding" else "work"` idiom disappears from ten-plus
  sites (H5); callers pass the active scope to `registry.for_scope(...)`.
- Scope moves into `SKILL.md` frontmatter as `x-evoflux.scopes`. `.evoflux.json`
  and `app/core/skill_scope.py`'s file I/O are deleted, not dual-read: a
  one-shot rewrite converts every bundled skill and the user's `SKILLS_DIR` in
  the same commit. A skill with no scope declared falls open to all scopes,
  exactly as today, so a third-party bundle stays usable without conversion.
- **Delete `BUNDLED_SKILL_MODES`** (H1). Each bundled skill declares its own
  scope in its own frontmatter. Adding a builtin becomes a directory drop,
  which is also a precondition for P5 and P6.
- Drop the nested `parent/child` name extension and its `nested-legacy-skill`
  and `legacy-name` diagnostics (H13). Portable Agent Skills naming
  (`^[a-z0-9]+(-[a-z0-9]+)*$`, matching the leaf directory) becomes the only
  accepted form; `_LEGACY_NAME_RE` is deleted and a non-conforming skill is an
  error naming the required shape. No in-repo skill uses the nested form — it is
  dead compatibility, reachable only by a third-party bundle.

**Delete the sidecar contract entirely** (H14). Not merge two into one — go to
**zero**. `SKILL.md` becomes the whole contract, exactly as agentskills.io,
Claude Code and MiMo have it. A skill directory after this phase contains
`SKILL.md` and whatever `scripts/`, `references/`, `assets/` its workflow
actually uses, and nothing the harness has a schema for:

```yaml
---
name: coding-change
description: "Implement, refactor, migrate, or shape a contract with proof …"
x-evoflux:
  scopes: [work, coding]
  display_name: "Change Code"
  short_description: "Implement, refactor, migrate, or shape a contract with proof"
  default_prompt: "Use $coding-change to make this change and verify its observable contract."
---
```

`name` and `description` are the standard. `x-evoflux` is a single namespaced
block for the four values that are genuinely EvoFlux-specific; other clients
drop unknown keys, which MiMo demonstrates in its own bundle (`license` /
`version` / `platforms`, shipped and ignored). Portability is *better* than
today: an EvoFlux skill copied into Claude Code or MiMo now works with no
stripping, whereas today its scope and policy silently vanish with the
sidecars.

Deleted in this phase:

- **`.evoflux.json`** and `app/core/skill_scope.py`'s file I/O →
  `x-evoflux.scopes`.
- **`agents/evoflux.yaml`, `agents/openai.yaml`, and the whole `agents/`
  convention** → `_read_agent_metadata` (163 lines), `EVOFLUX_AGENT_METADATA`,
  `PORTABLE_AGENT_METADATA`, `MAX_AGENT_METADATA_BYTES`,
  `AGENT_INTERFACE_FIELD_LIMITS`, `MAX_DEPENDENCY_RECORDS`, and their ~10
  diagnostic codes. With the directory gone, the `agents` special-cases at
  `discovery.py:833` and `activation.py:313` and in `_RESOURCE_DIR_NAMES` go
  too.
- **`icon_small`, `icon_large`, `brand_color`** → zero skills set them; three
  `SkillRecord` fields, three field limits, their diagnostics, and their API
  and TypeScript types. Icons later are a new feature, not a preserved husk.
- **`policy.allow_implicit_invocation`** → the portable frontmatter key
  `disable-model-invocation` that P3 makes authoritative. Six bundled skills
  set the proprietary form (`mcp-installer`, `memory-search`,
  `plugin-development`, `plugin-installer`, `self-healing`, `skill-installer`);
  **none** sets the portable one. Convert all six.
- **The whole declared tool-dependency mechanism** (A9) — `dependencies.tools`,
  `MAX_DEPENDENCY_RECORDS`, the `SkillRecord.dependencies` field,
  `_resolve_builtin_dependencies`, `SkillDependencyError`, the write-only
  `skill_runtime_contracts` metadata, and the validate-load-commit split in
  `activate_skill_with_runtime` (which collapses back to `activate_skill`). It
  is not replaced by a frontmatter key: it resolves to an empty set on every
  skill that uses it, and its one live effect — refusing to load a skill whose
  preferred tool is absent — is behaviour we do not want.
  `SkillRuntimeContractHook` survives at roughly fifteen lines, renamed to what
  it actually does: re-grant a plugin skill's MCP tools after restore or
  compaction.
- **`evals/`** → moved out of the bundle to `tests/fixtures/skill-routing/<name>.json`.
  A test fixture shipped inside a distributed package is why the manifest
  needed a rule to hide it and why `validate_skills.py` had an opinion about
  it; both disappear when it lives with the tests. `validate_skills.py` stops
  *requiring* eval cases; the P1 routing eval reads the fixture directory
  directly.

After P4 the resource manifest has **no exclusion list at all** beyond
`SKILL.md` itself — every remaining file in a skill directory is task content,
by construction.

### P5 — Bundled skills extract to disk

Adopt MiMo's model: bundled skills are written to
`{EVOFLUX_DATA}/builtin_skills/{version}/skills/<name>/` on first use, with a
marker whose content is `{version, skills: [...]}` so a retired builtin is
removed from the previous extraction rather than lingering. A non-bundled skill
of the same name always wins, explicitly (`if bundled and not existing.bundled:
skip`).

Three problems this fixes at once: bundled skills stop being read-only package
internals; `_grant_skill_read_access` no longer needs to special-case them; and
a user can copy-and-edit a builtin, which is the single most-requested shape for
a skill system.

**Extraction-time availability gating** (§7.2 G4). Extraction is already the
place that decides which bundled skills exist on disk, so two MiMo mechanisms
land here at no per-turn cost:

- `x-evoflux.requires-command: <name>` in frontmatter — the skill is not
  extracted when the command is absent, mirroring MiMo's
  `isBuiltinSkillInstalled` (`which claude`, `which codex`). A skill that
  teaches the model to drive a CLI the machine does not have is worse than
  absent: it is a catalog entry that produces a failing plan.
- a category disable flag for the four `*-official` document skills, mirroring
  `OFFICIAL_SKILL_NAMES` + `MIMOCODE_DISABLE_OFFICIAL_SKILLS`, for operators who
  do not want office-format tooling offered at all.

Both feed the extraction marker's `{version, skills: [...]}` content, so
changing either re-extracts and removes the now-disabled directories — the
retirement path already being built in this phase.

### P6 — Fold `asdd_skills/` into the registry

Register `app/asdd_skills/` as a bundled root with scope `asdd` (H12). The seven
phase skills become ordinary skills: discoverable, permissioned, settable,
activatable through the same tool, with the same diagnostics.
`asdd_store.read_asdd_template` becomes a thin adapter over
`skill(action="read_resource")` or `resolve_resource_path`, so `TEMPLATE.md`
and `references/` stop being a private file protocol.

### P7 — Remote skills, aliases, and the config surface

- **`skills.urls`**: `index.json` manifest → download to `{CACHE}/skills/<name>/`
  → scan as an ordinary root, MiMo's `Discovery.pull` shape (A7). Entries
  missing `SKILL.md` are skipped with a warning. This is the mechanism
  `skill-installer` is currently standing in for.
- **`aliases`** frontmatter, consumed by `skill_search` exact matching and by
  the composer's slash resolution (A8). `difflib.get_close_matches` is deleted:
  a not-found error lists the reachable names and points at `skill_search`,
  which is the mechanism that actually answers "I don't know the exact name".
  Guessing at a typo was the workaround for having no search.
- **A locale dictionary for bundled skills** (§7.2 G3) — the gap the reverse
  audit rates highest. MiMo carries `localized-alias.ts` + `i18n/skill.ts`,
  resolves `/深度研究` → `/deep-research` **client-side before the message is
  sent**, and enforces by test that every bundled skill has a unique localized
  slash alias and a description in every TUI locale. EvoFlux serves
  Vietnamese-speaking users and has none of it: a skill is reachable only by
  its English kebab-case name. Add the same three pieces —
  a per-locale `{slash_aliases, description}` dictionary for bundled skills,
  composer-side resolution so the backend grammar stays ASCII and P2's single
  scanner is unaffected, and a uniqueness test per locale. Author-supplied
  `aliases` in frontmatter stay orthogonal: they are per-skill synonyms, not
  translations.
- **Every constant from H8 moves to `app/core/config.py`** with an env override
  and a documented default, in one table in `documents/reference/`. The 95 KB
  activation limit (H9) becomes a configurable ceiling that *warns and
  truncates with a pointer to the resource manifest* rather than hard-failing —
  a skill that is too long should degrade, not disappear.
- The catalog's `_INTRO` / `_RULES` block (H6) becomes a template with the
  EvoFlux-specific `code_context` line moved to wherever `code_context` is
  described.

### P8 — Catalog simplification

With P1 in place, `catalog.py` loses its reason to rank:

- delete `_query_ranked_names`, `_overlap_rank`, `_ROUTING_STOPWORDS`, and the
  `query` parameter — that logic moves to `skill_search` where a per-turn
  answer costs nothing (A3)
- delete `_render_stable` (it exists only to undo ranking) — render in name
  order, always
- keep the budget and the round-robin description allocation; they are real and
  the `coding-skill-consolidation` analysis shows they bind
- `SkillCatalogHook` loses `cache_stable`; there is only one behaviour
- `format_available_skills`'s two rendering modes collapse into one renderer
  shared with the hook

### P9 — Delete the compatibility surface

The fourteen constructs in H13 are removed and their callers updated. This is
not cleanup deferred to "later" — each item is deleted by the phase that makes
it redundant, and P9 is the checklist that proves none survived:

| Deleted | By | Callers updated to |
|---|---|---|
| `_parse_frontmatter`, `_render_tokens`, `_iter_skill_paths`, `_skills_dir_signature`, `_discover_skills_cached` | P0 | the registry / `app.agent.skills.*` directly |
| `discover_skills()`, `as_legacy_dict()`, `skills_for_mode()` | P0 | `SkillRecord` and `registry.for_scope()`; `api/routes/skills.py` and `api/routes/team/chat.py` serialize from the record |
| the `_state is None` branch in `load_skill` | P2 | tests construct an `AgentState`; the tool has one contract |
| `read_skill_instructions()` | P2 | `activate_skill` |
| `MAX_CONFIGURED_SKILL_CHARS` | P2 | `MAX_CONFIGURED_SKILL_BYTES`, then config |
| `catalog_budget_chars` misnomer | P8 | renamed to its actual unit |
| `_LEGACY_NAME_RE`, `legacy-name`, `nested-legacy-skill` | P4 | one portable name rule |
| `.evoflux.json`, `agents/evoflux.yaml`, `agents/openai.yaml`, `_read_agent_metadata`, `EVOFLUX_AGENT_METADATA`, `PORTABLE_AGENT_METADATA`, `MAX_AGENT_METADATA_BYTES`, `AGENT_INTERFACE_FIELD_LIMITS`, `MAX_DEPENDENCY_RECORDS` | P4 | `SKILL.md` frontmatter — no sidecar |
| `icon_small`, `icon_large`, `brand_color` + their limits and diagnostics | P4 | nothing — zero skills set them |
| `policy.allow_implicit_invocation` | P4 | frontmatter `disable-model-invocation` |
| `dependencies.tools`, `MAX_DEPENDENCY_RECORDS`, `SkillRecord.dependencies`, `_resolve_builtin_dependencies`, `SkillDependencyError`, `skill_runtime_contracts`, `activate_skill_with_runtime` | P4 | nothing — A9 shows it is a no-op; the plugin grant it was confused with stays |
| the `agents/` and `evals/` special-cases in `list_skill_resources` and `resolve_resource_path` | P4 | neither directory exists in a bundle |
| the `:` alternative in `_SLASH_DIRECTIVE_RE` / `_DOLLAR_DIRECTIVE_RE` / the TS grammar, and `_resolve_name`'s `a:b`→`a/b` mapping (§7.2 G8) | P2 + P4, together | one portable name form; the grammar stops advertising a shape the registry rejects |
| `_RESOURCE_DIR_NAMES` | P0 | direct-child traversal |
| `_source_for_root`, `_PATH_SCOPED_SOURCES`, `api._skill_source` | P0 | `SkillRoot.source` declared by the policy |

The `app.agent.skills.__init__` docstring's claim that "the legacy
`app.agent.tools.builtin.skill` module remains the public tool facade so saved
agent configurations and third-party imports keep working" stops being true and
is deleted with it. `tools/builtin/skill.py` becomes what its name says: the
tool, and nothing else.

---

## 5. Sequencing and risk

```
P0 registry + roots ──┬── P1 delete resolver / add skill_search ──┬── P8 catalog ──┐
                      │                                           │                │
                      ├── P2 one injector ────────────────────────┘                ├── P9 compat surface gone
                      ├── P3 two axes                                              │
                      ├── P4 scopes ──── P5 bundled extraction ──── P6 asdd fold ──┤
                      └── P7 remote + aliases + config ───────────────────────────-┘
```

Each phase is a single change that lands the new path and deletes the old one.
No phase is "done" while both exist, so the mitigations below are about getting
the cutover right, not about softening it.

| Phase | Risk | Why | Mitigation |
|---|---|---|---|
| P0 | medium | touches every consumer | the registry is written and its callers converted in one change; a `grep` for each deleted symbol is the completion check |
| P1 | **high** | routing quality is the product | routing eval is a merge gate; a regression is fixed in `skill_search` tuning or in the descriptions, never by reinstating the resolver |
| P2 | medium | history-shape change | the four producers already emit byte-identical pairs, so the change is *who* emits, not *what*; the injector is landed and the other three gutted together |
| P3 | low | one evaluator, one resolved boolean | — |
| P4 | medium | wide but mechanical; it removes the sidecar contract and rewrites all 21 bundles | one-shot frontmatter rewrite in the same commit; a skill that declares nothing falls open to all scopes, so an unconverted third-party bundle keeps working; `scripts/validate_skills.py`, `skill-creator`, `skill-installer` and the `settings.skills.new` scaffold are updated in lockstep so a new skill cannot be born in the old shape |
| P5 | medium | on-disk layout | versioned path + `{version, skills}` marker makes extraction self-healing and retirement automatic; a failed extraction is an error surfaced to the user, not a silent fallback to the packaged path |
| P6 | low | isolated | `asdd_store` is rewritten onto `resolve_resource_path`; its private file protocol is removed, not wrapped |
| P7 | low | new surface | `skills.urls` is empty by default |
| P8 | low | pure deletion, unblocked by P1 | — |
| P9 | low | checklist | every row has a named replacement and a `grep` acceptance check |

**Behaviour changes to record in `CHANGELOG.md`** — all of these are breaking,
and all land in the same release:

- brand roots (`.claude`, `.opencode`, `.codex`) become opt-in
- dotted path segments are no longer scanned
- only `<root>/<name>/SKILL.md` is a skill; deeper `SKILL.md` files are resources
- skill names must be portable (`lowercase-hyphenated`, matching the directory);
  nested `parent/child` names are rejected
- **a skill is one file plus its resources.** `SKILL.md` frontmatter is the
  entire harness contract; `.evoflux.json`, `agents/evoflux.yaml` and
  `agents/openai.yaml` are no longer read and `agents/` has no meaning
- skills no longer declare tool dependencies; a skill whose preferred tool is
  absent loads and degrades instead of refusing to load. Plugin skills still
  grant their plugin's MCP tools on activation
- `disable-model-invocation` in frontmatter is the only way to make a skill
  model-unreachable; `policy.allow_implicit_invocation` is gone
- `icon_small`, `icon_large` and `brand_color` are removed from the skill API
- eval fixtures move from `<skill>/evals/` to `tests/fixtures/skill-routing/`;
  `validate_skills.py` no longer requires them inside a bundle
- the per-turn skill resolver is gone; the model selects
- more than one skill can be activated by one message
- a skill over the activation ceiling truncates with a pointer rather than
  failing to load
- `app.agent.tools.builtin.skill` no longer re-exports discovery internals;
  third-party imports move to `app.agent.skills`

---

## 6. Acceptance criteria

1. `grep -rn 'coding" if mode' app/` returns nothing.
2. `BUNDLED_SKILL_MODES`, `_source_for_root`, `_PATH_SCOPED_SOURCES`,
   `standard_skill_roots`, `_RESOURCE_DIR_NAMES`, `_LEGACY_NAME_RE`,
   `resolution.py`, `skill_resolution.py`, `_query_ranked_names`,
   `_overlap_rank`, `_ROUTING_STOPWORDS`, `_render_stable` are all deleted.
3. The eligibility predicate appears exactly once in `app/`.
4. `inject_skill_activation` has exactly one caller.
5. A user turn issues no LLM call other than the agent's own.
6. `/skill:a … $b … /c` activates three skills and emits the orchestration
   reminder; a fourth overflows to a hint.
7. A skills root can be added by config with no code change; a bundled skill can
   be added by dropping a directory.
8. The system-prompt catalog is byte-identical between two turns whose skill set
   is unchanged.
9. `~/.claude/skills/.trash/x/SKILL.md` is not discoverable, and
   `data-analytics/references/workflows/*/SKILL.md` produces no catalog entry
   for a reason that survives renaming `references/`.
10. A skill named identically in a user root and the bundle resolves to the
    user's, and the settings overlay still addresses each separately.
11. Every invariant in §2.3 has a passing test.
12. **No compatibility surface remains.** Every H13 row is gone:
    `grep -rn 'as_legacy_dict\|skills_for_mode\|discover_skills(\|read_skill_instructions\|MAX_CONFIGURED_SKILL_CHARS\|_discover_skills_cached\|_iter_skill_paths\|_skills_dir_signature\|_parse_frontmatter\|_render_tokens' app/ web/`
    returns nothing, and no module under `app/agent/skills/` or
    `app/agent/hooks/skill*` contains the words `legacy`, `compatibility`, or
    `historical` describing a retained code path.
13. No env flag selects an older behaviour: there is no
    `EVOFLUX_SKILL_RESOLVER`, no dual-read of `modes`, and no
    `EVOFLUX_*_LEGACY_*` key anywhere in the skill runtime.
14. **A skill has no sidecar.**
    `find app -name '.evoflux.json' -o -name 'openai.yaml' -o -path '*/agents/*' -o -path '*/evals/*'`
    returns nothing under any skill root, and
    `grep -rn "icon_small\|brand_color\|allow_implicit_invocation\|_read_agent_metadata" app/ web/src/`
    returns nothing.
15. A skill bundle copied into Claude Code or MiMo-Code loads with its
    description intact and no file stripped — round-trip portability is tested,
    not assumed.
16. Every routing fixture is executed by the P1 eval and the suite passes; the
    fixtures live in `tests/`, and no skill directory contains one.
17. No skill declares tool dependencies.
    `grep -rn "dependencies\|SkillDependencyError\|skill_runtime_contracts" app/agent/skills/`
    returns nothing, and a coding skill loads normally in an agent whose grant
    excludes `code_context`. A plugin skill still grants its plugin's MCP tools
    on activation, and still does so after a session restore.

---

## 7. Reverse audit — does the refactored system map 1:1 onto MiMo-Code?

Walking MiMo's skill surface component by component and asking what the plan
produces for each. **Verdict legend:** `=` parity, `≈` same contract, different
mechanism (justified), `≠` deliberate divergence, `!` gap the plan does not
cover.

### 7.1 Component map

| MiMo-Code | Plan produces | |
|---|---|---|
| `Skill.get / all / available / modelInvocable / reload` | same five, `registry.py` (P0) | `=` |
| `Skill.dirs()` → `external_directory` allow-list (`agent.ts:107`) | `registry.dirs()` (P0) feeding the sandbox grant | `≈` permission vs sandbox; evoflux's is activation-scoped |
| `permission.skill` patterns, `allow`/`ask`/`deny` | P3, same evaluator | `=` |
| `disable-model-invocation` frontmatter | P3, becomes the only reachability axis | `=` |
| `user-invocable` (considered, **rejected** by MiMo) | kept — evoflux has a settings UI that exposes it | `≠` justified |
| `externalSkillDirs()` 4-flag predicate | P0 `SkillRootPolicy`, same four-flag shape | `=` |
| `dot: false` on external scans | P0 non-dot matching | `=` |
| `BUNDLED_SKILL_PATTERN` single-level, `**` elsewhere | P0 single-level **everywhere** | `≠` justified by P5 (see P0) |
| builtin bundle extract + version marker + retired cleanup | P5, same shape | `=` |
| compose bundle as a second extracted root | no equivalent — evoflux has no compose | n/a |
| `skills.paths` / `skills.urls` config | P0 / P7 | `=` |
| `Discovery.pull` → `index.json` → cache | P7 | `=` |
| `searchSkills` BM25 + exact alias, Flag-tuned | P1 `skill_search`, same constants | `=` |
| `skill_search` auto-load above threshold + `ctx.ask` | P1 | `=` |
| `skill` tool, `{name}` only, static description | P1/P2 — evoflux keeps `action=list\|load\|read_resource` | `≠` `read_resource` is a §2.3 invariant |
| redirect-don't-dead-end error strings | P3 | `=` |
| `renderSkillContent`: body + base dir + **sampled** file list | evoflux: body + dir + **exhaustive** manifest (≤200) + revision hash | `≠` manifest feeds `read_resource` |
| no activation size cap | configurable ceiling that truncates (P7) | `≠` justified |
| `SystemPrompt.skills` → catalog in system prompt | `SkillCatalogHook` + finalizer | `=` |
| `Skill.fmt(verbose)` emits `<name> <description> <location>` | evoflux emits `- name: description`, **no location** | `!` G2 |
| catalog always `localeCompare`-sorted, no budget | P8 sorts by name; **budget kept** | `≠` open question §8 |
| single injector = mention scan | P2 | `=` |
| `mentionRe`, fences stripped, dedup, order-preserving | P2 | `=` |
| `MAX_AUTOLOAD = 3` + overflow hint | P2, configurable | `=` |
| multi-skill orchestration reminder | P2, wording ported | `=` |
| idempotency via `<skill_content name=…>` prefix scan | P2, plus `loaded_skills` promoted to state | `≈` stronger |
| every skill auto-registered as a slash command from `all()` | P2 grammar; evoflux keeps `seed/commands` separate | `!` G6 |
| localized slash aliases + per-locale descriptions (`localized-alias.ts`, `i18n/skill.ts`) | P7 has `aliases` frontmatter only | `!` G3 |
| `matchDocumentSkills` attachment → skill reminder | §8 open question | `!` G5 |
| `isBuiltinSkillInstalled` — gate a builtin on `which <cmd>` | nothing | `!` G4 |
| `OFFICIAL_SKILL_NAMES` + `DISABLE_OFFICIAL_SKILLS` | nothing | `!` G4 |
| `reload()` on `/\.mimocode\/(tools?\|skills?)\//` write | P0, same trigger | `=` |
| `GET /skill` endpoint from `all()` | `api/routes/skills.py` (much larger: CRUD + settings) | `≈` superset |
| TUI `DialogSkill` picker | evoflux composer + settings UI | `≈` |
| `debug skill` CLI | nothing | `!` G7, trivial |
| `isSkillCatalogReminder` legacy-catalog suppression | not needed — evoflux's catalog was never in user messages | n/a |
| skill body eagerly held in `Info.content` at discovery | Tier-1 metadata only; body read at activation | `≠` see 7.3 |
| no diagnostics — a bad skill silently vanishes | diagnostics kept (§2.3) | `≠` justified |
| no scopes/modes | scopes kept (P4) | `≠` justified |
| no plugin skills | plugin precedence kept | `≠` justified |
| no declared tool dependencies (`allowed-tools` deliberately not implemented) | deleted too (P4, A9) | `=` |
| no plugin system | plugin MCP grant on activation kept (§2.3) | `≠` justified |
| no settings overlay | overlay kept (§2.3) | `≠` justified |

### 7.2 Gaps the audit found — these amend the plan

**G1 — `registry.dirs()` was missing.** MiMo's `Skill.dirs()` is a first-class
accessor consumed by the permission layer. The plan listed five accessors and
not this one, and §2.3 wrongly asserted MiMo has no directory-access
mechanism. Both corrected: `dirs()` is now in P0 and is what the sandbox grant
reads.

**G2 — the catalog omits the skill's location.** MiMo's verbose catalog gives
the model a `file://` path per skill, so it can read `SKILL.md` directly
without going through the tool. EvoFlux emits `- name: description`. Adding a
locator is cheap and strictly more useful — **but** it inflates the catalog
under a budget evoflux has and MiMo does not, so it is coupled to the budget
question. *Decision needed* (§8).

**G3 — no localization layer for invocation.** MiMo carries
`localized-alias.ts` + `i18n/skill.ts`, resolves `/深度研究` → `/deep-research`
client-side before the message is sent, and enforces by test that *every*
bundled skill has a unique Chinese slash alias and a description in every TUI
locale. The plan's `aliases` frontmatter (P7) covers user-authored synonyms but
not a locale-indexed dictionary. For a Vietnamese-speaking user base this is
the most consequential gap in this list. **Add to P7**: a locale dictionary for
bundled skills, resolved in the composer before send (so the backend grammar
stays ASCII), plus the same uniqueness test.

**G4 — no availability gating for bundled skills.** MiMo does two things
evoflux has no equivalent of: `isBuiltinSkillInstalled` hides a skill whose
external CLI is not installed (`which claude`, `which codex`), and
`OFFICIAL_SKILL_NAMES` + `MIMOCODE_DISABLE_OFFICIAL_SKILLS` lets an operator
drop a whole category. EvoFlux ships the same four `*-official` document skills
and has neither. **Add to P5** (it already owns the extraction/enablement
step): an `x-evoflux.requires-command` frontmatter key that omits a skill when
the command is absent, and a category disable flag. Both are extraction-time
filters, not runtime ones, so they cost nothing per turn.

**G5 — `matchDocumentSkills` is unresolved.** MiMo maps attachment mime and
filename to its office-format skills and emits a recommendation reminder.
EvoFlux has the same four skills and no trigger. It was already an §8 open
question; the audit does not change that, except to note MiMo's own recorded
defect — their table consults neither `available` nor `modelInvocable`, so a
gated skill would leak. If evoflux adds it, it routes through
`registry.model_invocable`.

**G6 — skill-as-command is only half-adopted.** MiMo has one registry: every
skill is automatically a slash command (from unfiltered `all()`, so even a
model-unreachable skill still autocompletes and is user-invocable). The plan
unifies the *grammar* in P2 but leaves `seed/commands` as a separate system.
That is defensible — evoflux's commands do things skills do not — but P3 must
state the rule explicitly: **the command/autocomplete surface reads `all()`
filtered by `user_invocable` and authorization only, never by
`model_invocable`.** Otherwise evoflux reproduces the exact bug MiMo's
`skill-invocation-control.md` was written to fix. **Added as a P3 acceptance
condition.**

**G7 — no `debug skill` CLI.** Trivial; a `evoflux skills list --json` over
`registry.all()` is an hour of work and makes every other phase easier to
verify. **Add to P0.**

**G8 — colon-namespaced names collide with P4's naming rule.** MiMo supports
`compose:ask` and its mention regex accepts `[A-Za-z][A-Za-z0-9_:-]*`.
EvoFlux's composer grammar *already* accepts `a:b`
(`_SLASH_DIRECTIVE_RE`), and `_resolve_name` maps `a:b` → `a/b` to reach a
nested skill. P4 deletes nested names and enforces
`^[a-z0-9]+(-[a-z0-9]+)*$`, which makes that mapping dead code the grammar
still advertises. **P2 and P4 must land the grammar change together**: drop the
`:` alternative from `_SLASH_DIRECTIVE_RE`, `_DOLLAR_DIRECTIVE_RE`, the
generated TypeScript, and `_resolve_name`. Recorded as a P9 row.

### 7.3 Two divergences worth naming explicitly

**Discovery loads metadata only.** MiMo holds every skill's full `content` in
memory from discovery onward; `Info.content` is populated by `add()` and the
`skill` tool just reads it back. EvoFlux is deliberately Tier-1: `SkillRecord`
has no `body`, and `SKILL.md` is read at activation. MiMo's approach is simpler
and makes `all()` self-sufficient; evoflux's is the right call given
`MAX_SKILL_FILE_BYTES = 512 KB` × an unbounded catalog and the bounded-discovery
posture in §2.3. **Keep evoflux's.** The consequence to accept: activation does
one file read that MiMo does not, and `skill_search` ranks over metadata only —
which is what MiMo does anyway.

**Activation is a synthetic tool-call pair, not a tool output.** MiMo's mention
scan writes a plain synthetic *text* part. EvoFlux fabricates an assistant
`tool_calls` message plus a `ToolMessage`, which is what makes activation
visible in the transcript, replayable through the lifecycle, and rehydratable
after compaction. It is also the reason `_loaded_skills_from_messages` exists.
P2 keeps the pair and removes the need to reverse-parse it by promoting
`loaded_skills` to state. **Keep evoflux's** — but note it is the one place
where evoflux's history shape is strictly more complex than MiMo's, so if P2
runs into trouble, collapsing to a synthetic text part is the escape that stays
within MiMo's architecture.

### 7.4 Verdict

Not 1:1, and it should not be. The **control flow** maps cleanly: registry
accessors, the two axes, the root predicate, the single injector, the search
tool, the reload trigger, the bundle extraction — all `=`. Every `≠` is a
capability §2.3 lists as an invariant, plus two shape choices (Tier-1 bodies,
tool-call-pair activation) that the audit confirms are load-bearing for
evoflux.

The honest summary: **after the refactor, EvoFlux is MiMo's skill architecture
plus a safety and management envelope MiMo does not have.** The eight gaps are
the difference between "the same design" and "the same product"; G3 and G6 are
the two that would actually be felt, and both are now amendments to P7 and P3.

---

## 8. Open questions

- **Should the catalog carry a locator?** (§7.2 G2) MiMo's verbose catalog gives
  the model a `file://` path per skill, so it can read `SKILL.md` directly
  instead of going through the tool. EvoFlux emits `- name: description`.
  Strictly more useful, but it is the single largest per-entry cost under a
  budget MiMo does not have — so this is the same decision as the next
  question, and should be taken with it, after P1's measurements.
- **Does the catalog budget survive?** MiMo has none. EvoFlux's
  `coding-skill-consolidation-2026-09-15.md` measured a real overflow at 128k,
  so the budget binds today — but it binds because the catalog carries 16
  coding entries. If P1 lands and `skill_search` becomes the discovery path for
  the long tail, the catalog could shrink to the implicit-only set and the
  budget could go away. Decide after P1, with measurements.
- **Should `skills:` on an agent still preload bodies?** MiMo has no equivalent;
  a skill is either in the catalog or invoked. Preloading is a real capability
  for narrow single-purpose agents, but it is also the mechanism the
  `builtin-skill-context-audit` identified as causing instruction competition.
  Proposal: keep it, route it through the injector, and count it against the
  same `MAX_AUTOLOAD` budget so it cannot silently dominate.
- **Do we want MiMo's `matchDocumentSkills`?** Attachment mime/filename →
  recommend the office-format skills. EvoFlux has the same four `*-official`
  bundles and no trigger. Cheap to add in P7; note MiMo's own recorded gap —
  their table consults neither `available` nor `modelInvocable`, so do it right
  the first time.
