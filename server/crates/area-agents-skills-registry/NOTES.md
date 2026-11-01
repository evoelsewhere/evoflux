# area-agents-skills-registry NOTES

Python source: `app/api/routes/agents.py`, `app/api/routes/skills.py`,
`app/api/schemas/{agents,skills}.py`, `app/services/agent_fs.py`,
`app/services/skills_service.py`, `app/core/agent_settings.py`,
`app/core/skill_settings.py`, `app/agent/skills/{registry,spec,models}.py`, plus the
parts of `app/conductor/{provenance,agent_runtime}.py`, `app/agent/loader.py`
(`load_team_from_dir`, `backfill_placeholder_agent_models`) and
`app/agent/config.py` (`parse_agent_definition`) that the routes call. Unit
`agents-skills` (`/api/agents/**`, `/api/skills/**`; pin breaker
`adapter:agents-skills`, service `agents_validation`, see `server/routing.toml`).
Contract tests: `contract-tests/agents-skills-registry/` (231 cases: 228 pass and 3 skip on Windows, the two symlink cases and the POSIX file-mode case, against
Python v3.1.1; snapshots under `snapshots/`).

The board row and `check_paths.py` name the lane `agents-skills-registry`, so the crate
is `area-agents-skills-registry` and the tests live in
`contract-tests/agents-skills-registry/` (the task brief said `area-agents-skills` /
`contract-tests/agents-skills/`; the harness maps a test folder to its unit by the
board lane name, so the board name wins). The board row also lists
`app/services/agent_service.py`; that module is chat attachment dispatch (used by
`routes/team/*`, the scheduler and `coding_purge_service`) and is not used by any
route of this unit. It belongs to `agent-loop-chat`; only `agent_fs.py` and
`skills_service.py` are services of this lane.

**Status:** La (this crate's stub, NOTES, contract tests). The crate is not mounted
(`units.rs` is untouched): a mounted empty router would answer 404 for a unit still
owned by Python. Lb sizing and dependencies are at the end.

## Endpoints

Every route needs auth: `401 {"detail":"Unauthorized — EvoFlux access key required."}`
for a missing or wrong token, before body validation. `422` bodies from FastAPI
validation are `{"detail":[{"type","loc","msg","input"...}]}`; every other error is
`{"detail": "<message>"}` (messages pinned in the tests). All paths in responses are
absolute.

### `/api/skills`

`?workspace=<path>` (repeatable) is accepted by every route. Each value is
`Path(v).expanduser().resolve()` (relative paths resolve against the **process cwd**),
must be an existing directory (`422 Workspace does not exist or is not a directory:
<resolved>`, checked before anything else, in list order), duplicates are dropped.

| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `GET /api/skills` | `workspace*` | `200 {"skills":[SkillSummary]}` every discovered winner, valid or not, sorted by name (plain string order) | `422` workspace |
| `GET /api/skills/{name}` | `workspace*` | `200 SkillDetail` | `404 Skill '<n>' not found.`; `413 SKILL.md exceeds the 524288-byte limit.`; a name with `/` never routes (`404 {"detail":"Not Found"}`) |
| `POST /api/skills` | `{"name","content","files":[{"path","content","encoding":"utf-8"\|"base64"}]≤200}` | `201 SkillDetail` | `422` (name, then content, strict) `422`-list for schema; `409` exists / dir not empty / not a directory / symlink; `400` bad resource path, duplicate path, bad base64, >2 MiB file, bundle limits |
| `PUT /api/skills/{name}` | `{"content","files"≤200,"deleted_files"≤200}` | `200 SkillDetail` | `404`; `403` read-only (builtin, plugin, symlinked, Conductor); `422` content; `400` bundle |
| `PATCH /api/skills/{name}` | `{"enabled": bool}` | `200 SkillDetail` | `404`; `409 Could not save the enabled state of Skill '<n>': <reason>` (corrupt `skill-settings.json`, >5000 disabled) |
| `DELETE /api/skills/{name}` | `workspace*` | `200 {"name"}` | `404`; `403` read-only; `400 Could not delete Skill` |

`SkillSummary` = `name, description, location (abs SKILL.md), source
(project|user|plugin|builtin), plugin_id, enabled, model_invocable
(= not disable-model-invocation), user_invocable, license, compatibility,
allowed_tools, metadata{str:str}, valid, diagnostics[{code,message,severity}],
shadowed_paths[], editable, symlinked, resource_count, provider`. `SkillDetail`
adds `content` (CRLF/CR folded to LF, undecodable bytes replaced), `files[{path,size,
media_type,content,encoding,editable}]` (sorted by directory walk: files of a folder
before its sub-folders, each sorted by name; max 200; text ≤512 KiB each and 2 MiB in
total is inlined, others are metadata only with `editable:false`; symlinks skipped;
nested `SKILL.md` listed read-only) and `bundle_truncated` (`resource_count > len(files)`).

Validation order on create: `name_problems(name)` (any problem, warnings included, is
`422`: pattern, >64 chars, `claude`/`anthropic`), then strict `SKILL.md` validation
(errors only; `body-too-long` and `exceeds-read-window` stay warnings), then the
conflict checks, then the staged write (resource paths, decoding, limits, a second
strict validation of the staged bytes). Several blocking messages are joined with
`"; "`. **`name: off`/`on`/`yes`/`no`/`true`/`null` in the frontmatter is read by PyYAML
as a boolean/null, so the Skill has no name (`missing-name`)**; Rust needs a YAML 1.1
loader for the frontmatter or must reproduce this (test `test_a_yaml_1_1_scalar_name_is_not_a_name`).

### `/api/agents`

Agent names are `<name>` (Work) or `coding/<name>` (Coding); nothing else is allowed.
`{name:path}` routes take the rest of the URL, so the literal prefixes
`registry`, `model`, `runtime-model/…` and `runtime-settings/…` are matched first.

| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `GET /api/agents` | – | `200 {"agents":[AgentSummary]}` sorted by string over `[*work, *"coding/"+stem]`; invalid files stay in the list (`valid:false`, `error`); `editable = provider is None` | – |
| `GET /api/agents/registry` | `workspace*` | `200 {"tools","skills","providers","models"}` (below) | `422` workspace |
| `GET /api/agents/{name:path}` | – | `200 AgentDetail {name,path,content,config,error,editable,provider,runtime_model_editable,bundle_model,model_override,extra_*}`; an unparsable file is `200` with `config:null,error` | `404 Agent '<n>' not found.`; `400` invalid path/name; non-UTF-8 file → bare `500 Internal Server Error` (text) |
| `POST /api/agents` | `{"name","content"}` | `201 AgentDetail` (content as stored, `config` = `model_dump(exclude_none)`, no provenance fields set) | `422` parse / `Frontmatter name '<x>' must match the request name '<y>'.` / team validation (rolled back); `409 Agent '<n>' already exists.`; `400` path |
| `PUT /api/agents/{name:path}` | `{"name","content"}` | `200 AgentDetail` | `422 URL name '<u>' does not match body name '<b>'.` (first); `403` Conductor-managed; `404`; `422` parse; `422 Frontmatter name '<x>' does not match URL name '<n>'.`; team validation `422` (previous text restored); `400` |
| `DELETE /api/agents/{name:path}` | – | `200 {"name"}` | `403` managed; `404`; `400`; `422` team no longer valid (file restored) |
| `PATCH /api/agents/model` | `{"names":[str],"model":str}` | `200 {"results":[{name,ok,error}]}` in request order, one row per name (duplicates included); a bad name is a row, not an HTTP error | `422` schema |
| `PATCH /api/agents/runtime-model/{name:path}` | `{"model": str\|null}` (key required) | `200 AgentDetail` | `400`/`404`, `409 Agent '<n>' is not managed by Conductor.`, `422 Model '<m>' is not configured or selectable.`, `422` store error |
| `PATCH /api/agents/runtime-settings/{name:path}` | `{"model"?,"extra_tools"?,"extra_skills"?,"extra_mcp"?}` each list ≤200 | `200 AgentDetail` | as above plus `422 unknown tools: a, b; unknown skills: c` (sorted) |

`GET /registry`: `tools` sorted by name `{name,description,tiers|null (sorted),lead_only}`
from `_default_tool_registry()` (the tools unit); `skills` = valid Skills only
`{name,description,enabled,model_invocable,user_invocable}` sorted; `providers` =
sorted catalog ids; `models` = `ModelCatalogEntry` per discovered model of every
**configured** provider, sorted by `(provider, model)`, filtered by the saved
visible-models list when one exists. Discovery is cached per provider for 60 s in the
module dict `_registry_model_cache` (see caches).

Team validation (after every create/update/delete): `load_team_from_dir(<dir>)` where
`<dir>` is `agents/` for Work names and `agents/coding/` for `coding/…` names (for a
create, always `agents/`). It parses **every** `*.md` in the directory, so one broken
file anywhere in that directory makes every write there `422 Failed to parse N agent
file(s) in '<dir>':\n  <file>: <error>` and the write is rolled back. It requires
at least one `role: lead` (`No agent with 'role: lead' found in '<dir>'. At least one
lead is required.`) and rejects unknown `lead:` owners
(`Member 'x' in 'x.md' references unknown lead 'y'.`). It does **not** reject a
second lead, unknown tool names, unknown skills, or a missing frontmatter `name`
(filled from the file name).

## Files read and written

All under the config dir `EVOFLUX_CONFIG_DIR` unless noted. Tests use temp dirs only.

| Path | R/W | By | Format and bytes |
|---|---|---|---|
| `agents/<name>.md`, `agents/coding/<name>.md` | R/W/D | agent routes, `agent_fs` | UTF-8 text, written as received after `strip_agent_temperature`: any `temperature:` line **in the frontmatter** is dropped (match `^temperature[ \t]*:`, other bytes kept verbatim, closing `---` and body untouched). Written through a temp file `.<name>.md.<rand>.tmp` in the same folder, `chmod` to the old mode (new files `0o644`), `replace`. Python opens it in **text mode** (platform newlines, finding B2). |
| `agents/**/*.md` (all) | R | team validation, `GET /agents`, `PATCH /model` placeholder fill | parsed with `yaml.safe_load` + `AgentConfig` (`app/agent/config.py`) |
| `agents/**/*.md` | W | `backfill_placeholder_agent_models` after `PATCH /model` (any success) and `PUT` of a `role: lead` agent | every file under `agents/` and `agents/coding/` containing `__PROVIDER_MODEL__` anywhere (also in the prompt body) is rewritten with the lead's model (the other mode's lead when its own has none), except Conductor-managed targets |
| `skills/<name>/SKILL.md` + bundle files | R/W/D | skill routes | `SKILL.md` text (strict-validated) written with `newline=""` (exact bytes); resources written as bytes; `0o644`/old mode; each file via temp + replace |
| `skills/.<name>.staging-<rand>/`, `skills/.<name>.backup-<hex>` | W/D | create/update | whole bundle is built in a sibling staging dir (copy of the old bundle for updates), validated, then `target → backup`, `staging → target`, backup removed; any failure restores the backup; both are gone after the request |
| `<project>/.evoflux/skills`, `.agents/skills`, `.claude/skills` for the workspace and its ancestors up to the Git root (none if there is no `.git` above: only the workspace) | R/W/D | `?workspace=` | same as `skills/` (finding S1) |
| `~/.agents/skills`, `~/.claude/skills` | R/W/D | discovery roots, `source:"user"`, editable | same as `skills/`; **`HOME` is a skills root for edits too** |
| `app/agent/builtin_skills/**` (repo) and enabled plugin `<install>/skills/**` | R | discovery | read-only (`403`) |
| `skill-settings.json` | R/W | `PATCH`, delete | `{"version": 2, "disabled": [sorted names]}` via `json.dumps(indent=2) + "\n"`, `chmod 0600`, atomic; the file is **removed** when nothing is disabled; unreadable/wrong-version files are ignored on read, replaced on write; a corrupt file makes `PATCH` fail with `409` and is not touched. Lock file `.skill-settings.json.lock` (never removed). `flock` only where `fcntl` exists (not on Windows: in-process lock only, finding B8). |
| `agent-settings.json` | R/W | runtime-model/settings, bulk model for managed agents | `{"agents": {"agent_<sha256("<project_id>\0<resource_id>\0<agent>")[:32]>": {project_id, resource_id, name, model?, extra_tools, extra_skills, extra_mcp}}, "version": 1}`, `json.dumps(indent=2, sort_keys=True) + "\n"`, `chmod 0600`; removed when the last record goes; a reset keeps a record that still has additions. Lock `.agent-settings.json.lock`. Legacy ids (`sha256("<project>\0<resource>")`) are read-only fallbacks. Limits: 1 MiB, 5000 records, 200 additions of ≤128 chars. |
| `settings.yaml` (`conductor.project_id`, `project_name`, `project_display_name`) and `<STATE>/conductor/managed-resources-v2.json` | R | `managed_resource_providers()` on every request | decide `provider`/`editable`; Conductor writes them (`conductor` unit); tests seed them directly |
| `.env`, `settings.yaml` provider data | R | registry model discovery (`routes/settings.py` helpers) | owned by `settings-providers` |

### The YAML emitter

`PATCH /api/agents/model` is the one place this unit **emits** YAML:
`yaml.safe_dump(meta, sort_keys=False)` over the parsed frontmatter with `model`
replaced (added at the end if absent), `.strip()`ped, wrapped in
`---\n{yaml}\n---\n{body}`. Observable rules, all pinned by
`test_bulk_model_rewrites_the_frontmatter_with_pyyaml_safe_dump`: comments are lost;
flow sequences become block sequences at the parent's indent (`tools:\n- read`);
key order is preserved; scalars are re-resolved (`yes`→`true`, `007`→`7`, empty →
`null`, `'1.0'` stays quoted, `'a: b'` single-quoted); non-ASCII is escaped inside
double quotes (`\xE9`, `—`), **no `allow_unicode`**; plain/quoted scalars wider
than 80 columns fold (`\` line continuations in double quotes); multi-line strings
become single-quoted with blank lines. The body is `group(2)` of
`^\s*---\r?\n(.*?)\r?\n---\r?\n?(.*)` (DOTALL) as read by `read_text` (CRLF folded). The
workspace has `yaml-rust2` only; its emitter quotes and folds differently
(`area-imports` NOTES blocker 4 is the same need). Lb needs a hand-written emitter for
the value shapes frontmatter uses, or a YAML crate that reproduces PyYAML's
`safe_dump` (width 80, escapes, quoting rules) byte for byte.

## In-memory registries and caches that other code reads

| Cache | Owner | Key and invalidation | Readers |
|---|---|---|---|
| `_discover_cached` `lru_cache(32)` | `agent/skills/registry.py` | key = roots + for every root the sorted `(dir name, SKILL.md mtime_ns, size)` + the `skill-settings.json` fingerprint `(mtime_ns, size, blake2b)`; `invalidate_skill_cache()` clears it | the **chat loop** (`agent/hooks/skills.py` per run via `discover_skills(sandbox_workspace_roots())`, activation, `team/chat.py`, `team/webbridge.py` `$` picker), **import's skill conflict check** (`import_service.py:349`, see `area-imports/NOTES.md` blocker 3), `app_search_service`, Conductor (`governed_reconciler.py:1079`), `/api/agents/registry`, **plugins** (`plugin_platform/skills.py::plugin_skill_roots` is a root provider; `routes/plugins.py::_after_mutation` calls `team_manager.invalidate_skill_cache()`) |
| `_disabled_cached` `lru_cache(8)` | `core/skill_settings.py` | path + content fingerprint; cleared by `set_skill_enabled` | discovery (sets `Skill.enabled`) |
| `_read_cached` `lru_cache(8)` | `core/agent_settings.py` | path + content fingerprint; cleared on write | `apply_managed_agent_runtime_model` (loader, drift, member build), routes |
| `_registry_model_cache` dict | `routes/agents.py` | provider id → `(monotonic, [model ids])`, TTL 60 s, **never invalidated**; an empty/failed discovery serves the last good list and caches nothing | `is_registered_model_id` (**chat start** `team/chat.py:442,1317` refuses a model not in it), `get_registry` (also called by `team/webbridge.py`), runtime-model routes |
| `_validate_agents_cache` | `routes/health.py` | 30 s TTL, not cleared by agent writes | `/api/health`, diagnostics |
| built `Agent`/blueprint caches | `team_manager`, `routes/team/chat.py` | stamped with the agent `.md` mtime (`drift.py`) | edits apply on the next turn; a **new** agent file appears after `refresh_blueprints` (see `area-imports` NOTES Q3) |

Skill writes call `team_manager.invalidate_skill_cache()` after the file operation
(`skills_service.py` lines 469, 496, 511, 536); the cache key already contains the
`SKILL.md` mtime and size, so a missed invalidation costs nothing except an edit that
keeps both identical. Bundle (resource) edits are not in the key because bodies are read
from disk at activation. The filesystem tools also clear it when a write lands under
`SKILLS_DIR` (`tools/builtin/filesystem/_config_watch.py`). Agent routes never invalidate
anything: the readers above stamp by mtime. A Rust writer must keep both properties
(CUTOVER_UNITS: "replace invalidation with versioned reads or a Rust event stream");
until the unit flips, a Python reader never sees a Rust write as stale beyond what a
Python write is today, **except** the 60 s model cache and the `lru_cache`s themselves,
which live in the Python process and cannot be cleared from Rust (the signature keys
make that safe for skills and agent settings; the model cache is TTL only).

## Skills that run scripts (`skill-scripts` lane)

`app/agent/builtin_skills/**` ships 171 files: `SKILL.md` plus `references/`,
`assets/`, and Python scripts (`docx-official`, `pptx-official`, `pdf-official`,
`xlsx-official`, `office-annotation-edit`, `super-research`, `mcp-installer`). This
unit never executes them: it lists the skill, returns its bundle files (read-only,
`source:"builtin"`) and stores `allowed-tools` as text. Execution is the model running
the shell/python tool on `<skill dir>/scripts/...` after reading `SKILL.md`, so it is
the `skill-scripts` lane (`area-skill-scripts`, board row `skill-scripts`, owner
`app/agent/builtin_skills/**`) plus tool permissions and the sandbox, not this port.
What this unit does contribute to that path:

* the builtin directory is found by `Path(__file__).parents[1] / "builtin_skills"`, so
  the packaged layout must keep those files next to the sidecar or Rust must be given
  the path (`SkillRoot builtin`);
* user and project bundles written here may contain `scripts/` that the agent later
  runs; files are written `0o644` (never executable), exactly as sent, and
  `allowed-tools` is advisory text, not enforcement;
* `location` and `files[].path` are what the model reads, so their format (absolute
  `SKILL.md` path, POSIX relative resource paths) is contract.

## Path and name inputs that become file paths (security review)

| Input | Becomes | Check in Python | Result (pinned) |
|---|---|---|---|
| agent `name` (URL and body), including `coding/<n>` | `agents/<n>.md` | `_validate_agent_name`: no `\`, ≤2 `/`-parts, a 2-part name must start with `coding`, each part `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$`, then `.resolve()` must stay under `agents/` | `..`, `../x`, `coding/..`, absolute and nested names are `400`; no file is created outside |
| skill `name` on create | `skills/<name>/` | `name_problems` (`^[a-z0-9]+(-[a-z0-9]+)*$`) before any path is built | `422`, nothing written |
| skill `name` on update/delete/patch | looked up in the discovered catalog; the **directory** comes from discovery, never from the name | catalog lookup | a name that is not discovered is `404`; `/` in it does not route |
| resource `path`, `deleted_files[]` | `<bundle>/<path>` | `PurePosixPath`: no `\`, not absolute, no `""`/`.`/`..` part, final name not `SKILL.md`, then `.resolve()` under the bundle | `../x`, `a/..`, `/x`, `a\b`, `SKILL.md`, `sub/SKILL.md` are `400`. **`./a` and `d//b` are normalized by `PurePosixPath` to `a` and `d/b` and accepted** |
| `?workspace=` | root of `.evoflux/.agents/.claude` skill folders (and their Git ancestors) read, edited, deleted | existence as a directory only | **S1** |
| frontmatter `name` of an on-disk skill | catalog key only | none | a folder `bad-dir` with `name: other-name` is served as `other-name`; its directory name still decides the write path |
| agent `model`/`extra_*` strings | JSON/YAML values, hashed into the settings id | length and `provider:model` shape | not paths |

Symlinks: discovery follows symlinked skill folders and roots, and Settings refuses to
edit or delete them (`403 … read-only because it is symlinked`); inside an editable
bundle `assert_skill_bundle_limits` rejects any symlink (`400 Symlinked files and
directories are not allowed in editable skill bundles.`) and the listing skips them.
The tests for these two run where the OS allows `os.symlink` and are skipped on this
Windows machine (no privilege): **the symlink behaviour is read from the code, not
observed**, and is the first thing to run on Linux CI.

## Suspected bugs and findings (Python is not fixed; tests pin today's behaviour)

Security:

* **S1: `?workspace=` is an unauthenticated-by-scope file primitive.** Any existing
  directory is accepted. `GET /skills/{name}` returns the content and bundle files
  (up to 2 MiB inline) of `<dir>/.claude/skills/*` and, walking up to the Git root,
  of every ancestor's `.evoflux|.agents|.claude/skills`; `PUT`/`DELETE` modify or
  `rmtree` them; the response carries absolute paths. No check against the sandbox
  or the active Coding project, which the product rule says every Coding session
  must stay inside. Because other agent tools (Claude Code, Codex) read those same
  folders, a planted `SKILL.md` with `scripts/` becomes instructions for them.
  Needs the owner's decision: confine to authorized workspaces (a known difference)
  or leave. The Rust chat already refuses a session workspace outside
  `EVOFLUX_WORKSPACE_ROOTS` (`KNOWN_DIFFERENCES.md`); Python's `/api/skills` and
  `/api/agents/registry` never read that setting, so Lb should apply the same rule
  to `workspace` rather than invent a second one. Pinned by `test_any_existing_directory_is_accepted_as_a_workspace`,
  `test_a_workspace_names_where_project_skills_are_written_and_deleted`.
* **S2: unreadable/invalid-UTF-8 agent files crash routes.** `read_text(encoding=
  "utf-8")` raises `UnicodeDecodeError` (a `ValueError`) that no route catches:
  `GET /agents/{n}`, `PATCH /model` and `PUT`'s previous-text read answer a bare
  `500 Internal Server Error`, and the placeholder fill after any lead update or
  model change raises on the same file (the write already happened). The list route
  is safe (it catches `Exception`).
* **S3: absolute paths are returned** (`path`, `location`, `shadowed_paths`, error
  messages) to any authenticated caller; the sidecar token is the only gate.

Behaviour (all pinned):

* **B1: a dot in an agent name renames the file.** `_agent_file` uses
  `Path.with_suffix(".md")`: `foo.bar` is stored as `foo.md`; `foo.baz` then conflicts
  (`409`), `GET /agents/foo.bar` and `foo.md` read the same file, and a stored
  `dot.name.md` is listed as `dot.name` but reported `invalid` ("Agent 'dot.name' not
  found.") because the stem is mapped to `dot.md` on read. `GET /agents/explorer.md`
  returns `name: "explorer.md"`.
* **B2: Windows newline translation.** `agent_fs._atomic_write` and both settings
  files use text mode without `newline=""`, so on Windows every `\n` is written as
  `\r\n` (and an input `\r\n` as `\r\r\n`). `SKILL.md` and resources are exact bytes.
  The contract tests compare through `lf()` so the same expectation holds on POSIX;
  Rust should write exact `\n`, which then differs from Python-on-Windows only
  (Windows is a desktop target, so decide whether that goes in `KNOWN_DIFFERENCES.md`).
  Reads use `read_text`, which folds CRLF, so `PATCH /model` normalizes CRLF files to LF.
* **B3: the "one lead / known tools / valid models" promise is not enforced.** The
  route docstring says writes are validated against known tools and valid models;
  in fact unknown tools, unknown skills, a second lead, and a missing `name` are all
  accepted, and `PATCH /model` takes any `provider:model` for unmanaged agents
  without consulting the registry (managed agents do consult it).
* **B4: one broken agent file blocks every write to its directory** (`422` with the
  whole directory's parse errors), and a write that would break the team is applied
  and then reverted, so a concurrent reader can see the broken file for a moment (the
  same window exists for create-then-delete).
* **B5: placeholder fill is a blind `str.replace`** of `__PROVIDER_MODEL__` over the
  whole file text, so a prompt that mentions the token is rewritten too.
* **B6: `name: off`-style YAML 1.1 scalars** make a skill nameless (above). The same
  `yaml.safe_load` rules apply to agent frontmatter.
* **B7: bulk-model error text starts with `: `** for pydantic errors with an empty
  location (`: Value error, Agent 'x': invalid model …`), and the same text is the
  `422 detail` on create. Pinned verbatim.
* **B8: no cross-process lock on Windows** for the two settings files (`fcntl` is
  missing, the lock degrades to the in-process lock); a leftover `.*.lock` file stays
  in the config dir.
* **B9: temp files are left behind** when `os.replace` fails in `agent_fs._atomic_write`
  (`.<name>.md.<rand>.tmp`); `skill_settings` cleans up, `agent_fs` does not.
* **B10: `GET /agents/registry` is reachable only through its literal route**, so an
  agent named `registry` (or `model`) cannot be fetched by name; the list shows it.
* **B11: the registry model list is stale for up to 60 s** after a provider's models
  change, and `is_registered_model_id` (used by chat start) reads the same cache.

## Pins check

`pin_breakers = ["adapter:agents-skills"]`. The unit cannot flip to Rust without an
adapter that (a) lets Python keep reading `skills/` and `agents/` caches (they are
fingerprinted by file metadata, so file-level writes from Rust are enough), (b) keeps
the Python-side `_registry_model_cache` and `provider` plugin state from serving a model
that Rust just removed (TTL only), and (c) serves provenance
(`managed_resource_providers`) which is the `conductor` unit's state file and
`settings.yaml`. Plugin skill roots come from the Python plugin registry
(`plugin_skill_roots`), so until `plugins-mcp` moves, Rust must obtain the root list
from the adapter or read the plugin installation store itself.

## Test map

All in `contract-tests/agents-skills-registry/`. Python test files for this lane:
`tests/api/test_skills_api.py`, `tests/services/test_skills_service.py`,
`tests/agent/skills/*`, `tests/core/test_skill_settings.py`,
`tests/core/test_agent_settings.py` and `tests/api/test_agents_api.py` (not re-run
here; the contract tests above cover the same observable behaviour).

| File | Covers |
|---|---|
| `test_skills_catalog.py` | list/detail shape, ordering, roots and precedence, shadowing, Git-root walk, workspace validation, bundle preview limits, invalid and oversize skills, YAML 1.1 names, disabled flags, live external edits |
| `test_skills_write.py` | create/update/patch/delete status codes and bodies, byte-exact files, staging cleanup, validation order and messages, resource-path traversal, limits, `skill-settings.json` bytes and removal, Conductor ownership, symlinks (skipped without privilege) |
| `test_agents_crud.py` | list/get/create/update/delete, names and traversal, `with_suffix` quirk, temperature stripping, CRLF, team validation and rollback, placeholder fill, seeded-agent snapshots |
| `test_agents_model_runtime.py` | `PATCH /model` including the emitter snapshot, managed agents, `agent-settings.json` bytes and id, runtime model/settings errors, corrupt store |
| `test_agents_registry.py` | registry shape, tool and provider snapshots, skills filter, models from a mock provider, visible-models, the 60 s cache |
| `test_auth_routes.py` | `401` on all 16 routes before validation, rejected writes change nothing |

## Lb: size and dependencies

**Size: large, about 3,000 lines of non-test Rust, and it slices cleanly into two
lanes.** The routes are thin; the weight is the skill/agent file model.

1. *Skills slice (about 1,300 lines):* SKILL.md parser and validator (`spec.py` 361
   lines: frontmatter regex, YAML load, diagnostics, strict mode), discovery
   (`registry.py` 301: roots, Git-ancestor walk, 2,000-entry caps, precedence and
   shadowing, signature cache), `skills_service` (555: staged atomic bundle swap,
   backup and restore, editable checks, symlink rules), `agent_fs` bundle half
   (resource paths, 200-file/2 MiB preview, limits), `skill_settings` (180), and the
   `/api/skills` routes with the `workspace` rules.
2. *Agents slice (about 1,700 lines):* `agent_fs` agent half, frontmatter parse and
   `AgentConfig` validation, **team validation** (`load_team_from_dir` /
   `resolve_agent_roster`), `effective_config` compile (`compile_agent_config`, tool
   registry, lead-only tool filtering, mode tiers), the placeholder backfill,
   `agent_settings` (382), the `PATCH /model` YAML emitter, and the `registry` route
   (tool catalog, provider catalog, `ModelCatalogEntry` assembled from model metadata,
   capabilities and thinking levels).

**Depends on:** (a) a YAML 1.1 loader for frontmatter and a PyYAML-compatible
`safe_dump` (workspace has `yaml-rust2` only; shared need with `area-imports`
blocker 4 and `settings-providers`); (b) `serde_json` with `indent=2`/`sort_keys`
formatting; (c) `mime_guess`-style table for `mimetypes.guess_type` (the contract
pins `text/x-python`, `text/markdown`, `application/json`, `image/png`,
`application/octet-stream`); (d) the `settings-providers` Lb (provider catalog,
visible models, `_provider_is_configured`, `_cached_provider_models`, model
discovery) and `area-providers` metadata/capabilities/thinking for the registry
`models`, and the tools unit's registry for `tools` and `_default_tool_registry`;
(e) the `conductor` state (`managed_resource_providers`, `ManagedResourceStore`) and
`plugins-mcp` (`plugin_skill_roots`); (f) the `skill-scripts` lane for the builtin
bundle contents and path; (g) the owner's decisions on S1 (workspace confinement) and
B2 (newlines on Windows), plus a `KNOWN_DIFFERENCES.md` entry for each hardening;
(h) the adapter `adapter:agents-skills` described under Pins check. Needs a security
review at Lb (path confinement, file writes, workspace scope).
