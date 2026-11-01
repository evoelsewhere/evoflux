# area-plugins-marketplace NOTES

Python source: `app/api/routes/plugins.py`, `app/api/schemas/plugins.py`,
`app/plugin_platform/{marketplaces,installer,registry,review,trust,validator,workspace,
credentials,models,builtins,extensions}.py`, plus the parts of
`app/plugin_platform/{runtime,skills}.py` and `app/conductor/provenance.py` the routes
call. Unit `plugins-mcp` (`/api/plugins/**` and `/api/mcp/**`; pin breaker
`adapter:plugins-mcp`, services `mcp` and `plugin_mcp`, see `server/routing.toml`). The
`/api/mcp/**` half is lane `mcp-management` (`../area-mcp-management/NOTES.md`); both
lanes share `plugin_mcp_runtime`, described here under *Processes*.
Contract tests: `contract-tests/plugins-marketplace/` (277 cases: 271 pass and 6 skip on
Windows against Python v3.1.1 with `TARGET=python`: three symlink cases, the POSIX file-mode
case, the zip backslash-name case and the `prepare` download case; snapshots under
`snapshots/`).

**Status:** La (this crate's stub, NOTES, contract tests). The crate is not mounted
(`units.rs` is untouched): a mounted empty router would answer 404 for a unit still
owned by Python. Lb sizing and dependencies are at the end.

## Security summary

These routes **install code and start processes**. Whoever holds the access key can: copy
or link any server-side folder as a plugin, enable it (its `mcp.json` command then runs as
the backend's user), rewrite the files of any linked plugin and have them re-executed,
write a new plugin or an archive to any path, and edit any folder that has a `plugin.json`.
Python enforces **no path confinement** beyond "not inside the bundled plugin tree" and
the structural checks below. Findings (S = security, F = information leak, B = bug) are
pinned by tests and listed under *Findings*; Rust must reproduce the behaviour first and
tighten it only through an owner decision recorded in `KNOWN_DIFFERENCES.md`. **Needs a
security review at Lb** (process start, file writes, path input, credentials).

## Endpoints

Every route needs auth: `401 {"detail":"Unauthorized — EvoFlux access key required."}`
for a missing or wrong token, before validation and before any work (test
`test_auth_routes.py`, 56 parametrized cases plus a no-side-effects case). FastAPI
`422` bodies are `{"detail":[{"type","loc","msg","input"…}]}`; every other error is
`{"detail":"<message>"}`. Domain errors map as `_http_error`: `KeyError` → `404 Plugin
installation not found.`, any `OSError`/`ValueError` → `422 <str(exc)>` (so an OS error
text and a bare path such as `"nope.txt"` become the detail); marketplace routes map as
`_marketplace_http_error`: `KeyError` → `404` (message minus quotes), `ValueError`
containing "already added" → `409`, other `ValueError` → `422`, anything else → `502
Marketplace operation failed.` (never produced by the tested paths).

Static routes are registered before `/{installation_id}` ones, in this order:
`/previews/{id}/files`, `/{id}/files`, `/marketplaces…`, `""`, `/inspect`, `/install`,
`/upload`, `/{id}/update`, `/{id}/update-upload`, `/create`, `/pack`, `/workspace/*`,
`/{id}/credentials`, `/{id}`, `/{id}/enabled`, `DELETE /{id}`. Rust must keep the
static-before-dynamic order (`GET /api/plugins/marketplaces/x/files` is `404`, test
`test_marketplace_routes_are_not_shadowed…`).

| Route | Request | Success | Errors (all pinned) |
|---|---|---|---|
| `GET /api/plugins` | – | `200 {plugins:[{installation,inspection,credentials,capabilities,provider}], mcp_servers:[PluginMcpRuntimeStatus]}`; user installs sorted by `(name,id)`, bundled ones last; inspections are redacted; `capabilities` all true except builtin/Conductor (all false) and `can_update` only for `installed` | – |
| `GET /api/plugins/inspect` | `?path=` (min 1) | `200 PluginInspection` of **any** directory (`expanduser`, absolute, not resolved against a root); a missing folder is `200` with `valid:false` and `plugin-root-invalid` | `422` empty/missing `path` |
| `POST /api/plugins/install` | `{path,mode:"install"\|"link",enabled:false}` (extra forbidden) | `201 {installation,inspection}` | `422` (package invalid, duplicate source, symlinks, bad source type, unreadable registry) |
| `POST /api/plugins/upload` | multipart `archive` (+`?enabled=`) | `201` | `422` extension not `.evoplugin`/`.zip` (checked before reading), archive errors, size |
| `POST /api/plugins/{id}/update` | `{path}` | `200` | `404`; `422` linked, name mismatch, invalid |
| `POST /api/plugins/{id}/update-upload` | multipart `archive` | `200` | as above |
| `POST /api/plugins/create` | `{destination,name,description,version,author,license,skill_name}` | `201 {path}` | `409` destination inside the bundled tree (before anything else); `422` exists / invalid (rolled back) |
| `POST /api/plugins/pack` | `{path,output?}` | `200 {path}` | `409` bundled; `422` invalid, output exists, output inside the plugin |
| `GET /api/plugins/workspace/tree` | `?root=` | `200 [{path,name,kind,size}]` | `422` |
| `GET /api/plugins/workspace/file` | `?root=&path=` | `200 {root,path,content}` | `422` |
| `PUT /api/plugins/workspace/file` | `{root,path,content}` | `200 {ok,inspection}` | `409` bundled; `422` |
| `POST /api/plugins/workspace/entry` | `{root,path,kind:file\|directory}` | `201 {ok,inspection}` | `409`; `422` |
| `DELETE /api/plugins/workspace/entry` | JSON body `{root,path}` | `200 {ok,inspection}` | `409`; `422` |
| `GET /api/plugins/marketplaces` | – | `200 [MarketplaceSource]` sorted by `(name.casefold(), id)` | `500` on a corrupt `marketplaces.json` (B3) |
| `POST /api/plugins/marketplaces` | `{kind:agent_plugins\|claude_code,name≤120,url≤2048}` | `201 MarketplaceSource` (no fetch) | `422` URL rules, blank name; `409` duplicate |
| `DELETE /api/plugins/marketplaces/{id}` | – | `200 MarketplaceSource` | `404 Marketplace not found: <id>` |
| `POST /api/plugins/marketplaces/{id}/sync` | – | `200 MarketplaceSource` (fetches) | `404`; `422` malformed id / URL refused / fetch failed (stored in `last_error`, 500 chars) |
| `GET /api/plugins/marketplaces/plugins` | `?q≤200&marketplace_id≤16` | `200 [MarketplacePlugin]` from the **cache only**, sorted `(name.casefold(), marketplace_id)`; `q` matches `name description author` case-insensitively | `422` limits; `500` on a corrupt cache (B3) |
| `POST /api/plugins/marketplaces/{id}/plugins/{name}/prepare` | – | `200 {preview_id,plugin,supported_components,unsupported_components,warnings,inspection}` (downloads) | `404` source/plugin; `422` not portable, unsupported source, ambiguous name, validation |
| `POST /api/plugins/marketplaces/install` | `{preview_id:^[a-f0-9]{32}$,allow_partial}` | `200 {installation,inspection}` (installed **disabled**) | `404 Marketplace preview expired or does not exist.`; `422` unsupported components without consent, changed preview |
| `GET /api/plugins/previews/{id}/files` | `?path=` | as `/{id}/files` for a prepared preview | `404 Plugin preview not found.` |
| `GET /api/plugins/{id}/files` | `?path=` | `200 {files:[…],truncated,readme}` or `{path,content,truncated}` | `404`; `400 Invalid package file path.` / `Binary files are not reviewable.` / `MCP configuration cannot be safely reviewed.` |
| `GET\|PUT\|DELETE /api/plugins/{id}/credentials` | PUT `{values:{key:str\|bool\|null}}` | `200 PluginCredentialState` | `404`; `422` (messages in tests) |
| `GET /api/plugins/{id}` | – | `200 {installation,inspection}` | `404` |
| `PATCH /api/plugins/{id}/enabled` | `{enabled}` | `200` | `404`; builtin ids `422 Bundled Agent Plugins are always enabled.` |
| `DELETE /api/plugins/{id}` | `?remove_data=false` | `200 {installation,inspection}` (the removed record) | `404`; `422` unowned install path |

Notes on shapes: timestamps are `datetime.now(UTC).isoformat()` for installations
(`2026-…T…:…:….ffffff+00:00`) and pydantic's `…Z` form for marketplace sources;
installation ids are `uuid4().hex`; marketplace ids `uuid4().hex[:16]`; preview ids
`uuid4().hex`. Responses carry null for every unset optional field (no omission).

## Files read and written

Roots: `plugin_platform_root = $EVOFLUX_DATA_DIR/agent-plugins`, staging
`$EVOFLUX_CACHE_DIR/agent-plugins/staging`.

| Path | Who | How |
|---|---|---|
| `<root>/registry.json` | register/enable/update/uninstall; read on **every** request that lists plugins, by the skills registry on every discovery and by the 1 s runtime watcher | `{"version":1,"installations":[…]}` (`indent=2`, `sort_keys`, trailing newline), written to `.registry.*.tmp` in the same folder, `fsync`, `os.replace`. Reads fall back to an empty registry when unreadable or >2 MiB (**writes re-read strictly and fail `422 Could not read plugin registry …`**, test `test_corrupt_registry…`); persisted `builtin` records are dropped on read |
| `<root>/installed/<id>/<version-or-digest16>/` | install/update | package copied from the staging dir with `shutil.copytree`, `os.replace` into place. Update replaces `<id>/<version>`; uninstall moves `<id>` to `.uninstall-<id>-<uuid>` then deletes it (`ignore_errors`). The delete/replace is guarded to stay under `installed/<id>/` (`Refusing to … unowned/mismatched install path`) |
| `<root>/data/<id>/` | runtime `PLUGIN_DATA` (created when a stdio server starts), `credentials.json` | removed only with `?remove_data=true` (guarded to stay under `data/`) |
| `<root>/data/<id>/credentials.json` | credentials routes | JSON object `{key: str\|bool}` (`indent=2`, `sort_keys`, newline), temp file + `fsync` + `os.replace`, mode `0600`; ≤256 KiB; **plaintext** |
| `<root>/marketplaces.json` | marketplace routes | `{"version":1,"sources":[…]}` same writer as the registry, ≤2 MiB |
| `<root>/marketplace-cache/<source-id>.json` | sync writes; search/prepare read | `{"version":1,"plugins":[…]}`; removed with the source |
| `<cache>/agent-plugins/staging/{install,update,upload,update-upload}-*/…` | install/update/upload | temp dirs, removed in `finally` (tests assert none are left) |
| `<cache>/agent-plugins/staging/marketplace-previews/<preview-id>/{artifact.evoplugin,source,package}` | prepare | kept until the preview is installed or expires (15 min, cleaned lazily on the next marketplace call) |
| **Any server path** | `install`/`update` (read), `inspect` (read), `create` (writes a tree), `pack` (writes a zip, creates missing parents), `workspace/*` (read/write/create/delete) | see *Request fields* |
| `<plugin>/mcp.json`, `<plugin>/plugin.json`, `<plugin>/skills/*/SKILL.md` | read by every inspection | bounded (`plugin.json` 512 KiB, `mcp.json` 2 MiB, `SKILL.md` per `spec.MAX_SKILL_FILE_BYTES`, ≤2000 entries, ≤200 MiB) |

Other writers of `registry.json`: the CLI (`app/cli/commands/plugin.py`) and Conductor
(`app/conductor/governed_reconciler.py` via the installer and registry helpers). Other
readers: `app/api/routes/team/problems.py` (plugin diagnostics), the skills registry,
`plugin_mcp_runtime`. A Rust port must keep the file format byte-identical and keep
writing atomically, because the Python sidecar and the CLI read the same files during
the migration.

Windows note: Python writes `registry.json`, `marketplaces.json`, the marketplace cache,
`credentials.json` and the scaffolded `plugin.json`/`SKILL.md` in **text mode**, so they
come out with CRLF on Windows. The tests normalise `\r\n` to `\n` and pin the POSIX
bytes; Rust writes LF everywhere.

## Processes

The routes themselves start no process. Enabling, updating or editing a plugin makes the
shared `plugin_mcp_runtime` (`app/plugin_platform/runtime.py`, an `MCPRuntime` with its
own config watcher disabled) start or stop these:

| Process | Started by | Started how | Supervised | Stopped |
|---|---|---|---|---|
| Plugin stdio MCP server, one per valid enabled `mcp.json` entry | `plugin_mcp_runtime.refresh()` at app start (`service=plugin_mcp`, skipped when that service is disabled), after every plugin mutation (`_after_mutation`: `refresh(force=True)`), and by the 1 s watcher when the registry, any `plugin.json`/`mcp.json`/`credentials.json` mtime+size, or a linked package's tree signature changes | MCP SDK `stdio_client(StdioServerParameters(command, args, env, cwd))` inside one asyncio task per server. `command` is resolved with `shutil.which` against the **user's login-shell PATH** (see below) unless `env.PATH` is set; `./x` commands are made absolute under the plugin root; child env is **only** `PATH` + the manifest `env` (with `${PLUGIN_ROOT}`/`${PLUGIN_DATA}` expanded once) + credential env + `PLUGIN_ROOT`/`PLUGIN_DATA` (these two always win) + the SDK's default allow-list (`PATH`, `HOME`/`USERPROFILE`, `TEMP`, `SYSTEMROOT`, …). The backend's `EVOFLUX_*`, `PYTHONPATH` and `DATABASE_URL` do **not** reach it (tested). `cwd` defaults to the plugin root; `${PLUGIN_ROOT}`/`${PLUGIN_DATA}`/`./` forms are resolved and must stay inside | One runner task per server: initialise → `tools/list` → state `ready` → wait for `shutdown`. **There is no automatic restart:** a crash leaves the status as it was until the next refresh. Failures set `state:"error"` (`error` is the formatted exception, OS-dependent text) and do not fail the request. `stdio` start errors, a missing executable and a closed remote port are tested as `error` | `stop_installation(id)` (before update/uninstall, so Windows can delete the folder), `refresh()` removing a runner (disable/uninstall/mcp.json edit: `shutdown` event, 10 s grace, then task cancel), `plugin_mcp_runtime.stop()` at shutdown. Killing the child is the SDK's job (stdin close, then terminate) |
| Plugin remote MCP server (`streamable-http`) | same | `httpx2` client, `follow_redirects=False`, 30 s/300 s timeouts, headers from `mcp.json` taken literally (no `${…}` expansion). **Enabling a plugin with an `https://` server opens an outbound connection immediately.** `sse` entries are valid but skipped | same runner | same |
| User login shell (once per backend process) | first stdio launch | `shell_runtime.build_argv(shell, 'printf "…%s\n" "$PATH"')`, stdout captured, timeout, killed on timeout; result cached for the process lifetime and re-read once if the command is not found | – | exits itself |

Lifecycle details the port must keep: the runtime builds its config from `list_effective_installations(enabled_only=True)`; invalid packages are skipped, but for **linked** plugins a package that turns invalid (for example a half-saved `mcp.json`) keeps the **last good** servers running (`_last_good`, tested); runtime names are `plugin_<id[:8]>_<slug(server)[:40]>_<sha256(server)[:8]>` and tool names `mcp_<runtime-name>_<tool>`; two plugins can declare the same server name (grant resolution then picks the lowest installation id and logs a warning).

Python-only / not portable: nothing in **this** unit imports or runs Python plugin
modules. `app/plugin_platform` is deliberately separate from `app/agent/plugins`
(in-process `.py` hook plugins), and the in-process loader belongs to lane `plugin-host`
(design §11, the Python plugin host subprocess). What does stay Python-specific:
(1) plugin **content** may be Python (an MCP server launched with `python`, skill
scripts run by the `skill-scripts` lane); the host only starts it as a child process,
so Rust can supervise it identically; (2) the SDK that drives stdio/HTTP MCP sessions is
the Python `mcp` package, so until lane `mcp-client` ports the runtime the Rust routes
need the `adapter:plugins-mcp` bridge to call `plugin_mcp_runtime` (`refresh`,
`stop_installation`, `list_status`); (3) `zipfile`, `shutil`, `PurePosixPath`,
`Path.resolve()` and `ipaddress` semantics pinned below.

## In-memory registries other units read

| Registry | Readers | Notes |
|---|---|---|
| `plugin_mcp_runtime` (singleton `PluginMCPRuntime`) | chat loop tool list `app/agent/loader.py:446` (`get_tools_dict`), per-plugin tools `agent_loop/core.py:488` and `hooks/conductor_telemetry.py` (`get_tools_for_installation`), MCP grants `loader.py:521` (`get_mcp_tools_for_server`, `all_mcp_server_names`, `resolve_plugin_server_name`), `/api/mcp/*` (`list_status`, `call_app_tool`) | rebuilt by `refresh`; Rust must keep the same names and the portable server-name alias |
| Plugin skill roots `plugin_skill_roots()` | `app/agent/skills/registry.py:105` on each discovery | reads `registry.json` + `inspect_plugin` of every enabled plugin; `_after_mutation` calls `team_manager.invalidate_skill_cache()` so a change is visible to `/api/skills` at once (tested both ways: enable, disable, uninstall). Skills show as `source:"plugin"`, `plugin_id:<installation id>`, `editable:false` |
| `_PREVIEWS` (prepared marketplace packages, TTL 15 min) | `previews/{id}/files`, `install` | process-local; lost on restart |
| `list_builtin_installations()` (`lru_cache`) | list/get/enable/uninstall | the bundled tree is `app/agent/builtin_plugins/`, **empty at v3.1.1** (only `__init__.py`), so the list has no bundled entry; ids would be `sha256("evoflux:builtin-plugin:<name>")[:32]` |
| Conductor provenance (`managed_resource_provider_by_id`) | `provider` field of the list | `null` unless a Conductor resource owns the installation |

## Request fields that become a command, argument, env var or path

| Field (route) | What Python does with it |
|---|---|
| `path` (`install`, `mode=install`) | `Path(path).expanduser().absolute()`; a directory is copied (`copytree`) after inspection (must be valid, no symlinks, ≤2000 entries / 200 MiB); `.evoplugin`/`.zip` is extracted; anything else `422`. Refused only inside the bundled tree. `source_ref`/`origin.source_ref` = the resolved path |
| `path` (`install`, `mode=link`) | `expanduser().resolve()`; **no copy**: the registry points at the folder, whose `mcp.json` is executed when enabled, and whose later edits are executed too (watcher) |
| `path` (`{id}/update`) | as install, for an `installed` plugin; name must match |
| `archive` + `filename` (`upload`, `update-upload`) | streamed to `staging/…/upload.evoplugin` (≤50 MiB, counted while reading), then as an archive. `filename` is **only** checked for its extension and stored verbatim in `source_ref`/`origin` as `upload:<filename>` |
| archive entry names | `_safe_archive_name`: reject `\`, leading `/`, empty, `..`, any `:` in a part; **`.` and empty segments are not rejected, they are dropped** by `PurePosixPath` (B1); duplicates compared case-insensitively; symlinks refused; ≤2000 entries; expanded ≤200 MiB; any entry >1 MiB with ratio >200 refused; `plugin.json` must be at the archive root; modes folded to `0755`/`0644` |
| `path` (`inspect`) | `Path(path).expanduser().absolute()` then read-only inspection of that folder |
| `destination` (`create`) | `Path(destination).expanduser().absolute()` (relative paths resolve against the backend's **cwd**); must not exist; `mkdir(parents=True)` — **missing parents are created**; writes `plugin.json` and an optional `skills/<skill_name>/SKILL.md`; rolls the tree back with `rmtree` if the result does not validate. `409` only inside the bundled tree |
| `name`, `description`, `version`, `author`, `license`, `skill_name` (`create`) | written through `json.dumps` into `plugin.json`; `skill_name` becomes a **directory name** (`skills/<skill_name>`) before validation (read from `installer.create_plugin`, not tested: a value with `/` creates nested folders until validation fails and rolls back) and is placed in the SKILL.md frontmatter via `json.dumps` for the description |
| `path`, `output` (`pack`) | `path`: `expanduser().resolve()`; `output`: `expanduser().absolute()`, must not exist, must not be inside the plugin (compared **unresolved**), parents created, zip written deterministically (1980 timestamps, sorted, ignoring `.git`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.DS_Store`, `*.pyc`, `*.pyo`). `409` for either inside the bundled tree |
| `root` (all `workspace/*`) | `Path(root).expanduser().resolve(strict=True)`; must be a directory with a **regular** `plugin.json`. It does **not** have to be an installed or linked plugin (S2) |
| `path` (`workspace/*`) | forward slashes only; no `..`, no absolute; `.`/empty segments dropped; the result must resolve inside `root` and no existing component may be a symlink; files ≤1 MiB, UTF-8 only; writes via temp file + `os.replace`, keeping a `0755` executable bit; delete refuses non-empty directories and the root `plugin.json` |
| `content` (`workspace/file PUT`) | written byte-exact (UTF-8); inside an `mcp.json` of a linked/installed plugin it **is** the command line of the server that is restarted right after (`_after_mutation`) |
| `.command`, `.args`, `.env`, `.cwd`, `.url`, `.headers` of `mcp.json` | not request fields, but reachable through `install`/`link`/`workspace` writes: `command` is a bare name (looked up on PATH, or `env.PATH`) or `./`-relative inside the root; `args` pass through with `${PLUGIN_ROOT}`/`${PLUGIN_DATA}` expanded; `env` keys other than `PLUGIN_ROOT`/`PLUGIN_DATA` are free (including `PATH`, `LD_PRELOAD`, `PYTHONPATH`, `NODE_OPTIONS`, S3); `cwd` must be `./…`, `${PLUGIN_ROOT}…` or `${PLUGIN_DATA}…` and stay inside; `url` is `http(s)`, no userinfo/fragment, `http` only for loopback; header names/values are syntax-checked |
| `values` (`credentials PUT`) | keys must be declared by the plugin; written to `credentials.json`; at start-up each becomes **an environment variable named by the plugin's `env`** (`^[A-Z_][A-Z0-9_]{0,127}$`, not `PATH`/`PLUGIN_ROOT`/`PLUGIN_DATA`); booleans become `"true"`/`"false"`; `url` fields are validated (`http(s)`, host, no userinfo/fragment); `********` for a secret means "keep" |
| `url` (`marketplaces POST`) | `validate_marketplace_url`: `https` only, hostname, no userinfo/fragment, not `localhost`/`*.localhost`/`*.local`/`*.internal`, an IP literal must be global; stored as `urlsplit(url).geturl()`. **Fetch time** (`sync`, `prepare`): DNS is resolved and every address must be global, ≤3 redirects each re-validated, 15 s timeout, ≤8 MiB catalog / ≤50 MiB package; connection uses a second, separate resolution (TOCTOU, S4) |
| `{marketplace_id}`, `{plugin_name}` (`prepare`) | id must match `^[a-f0-9]{16}$` (a **different** error from "unknown", `422` vs `404`); the plugin name selects a cached entry by `name` or `id`; its `source_url`/`source_path`/`source_ref` become a download URL: `agent_plugins` artifacts use the cached `source_url` verbatim (re-validated, SHA-256 and size checked against the catalog); `claude_code` entries build `https://codeload.github.com/<owner>/<repo>/zip/<ref>` after strict owner/repo/ref character checks, then extract only the named sub-path with the archive rules above |
| `preview_id` (`marketplaces/install`) | `^[a-f0-9]{32}$`, looked up in `_PREVIEWS`; the package is re-inspected and its digest compared before `install_plugin(..., enabled=False)` |
| `installation_id` (path) | not validated; compared with registry ids, so it never becomes a path unless it matches an installation |
| `q` (`marketplaces/plugins`) | substring match only |

Marketplace packages are normalised (Claude format → Agent Plugins): `${CLAUDE_PLUGIN_ROOT}`
/`${CLAUDE_PLUGIN_DATA}` are rewritten, literal secrets in env are refused, `${VAR}`
placeholders must match their key and become credential fields, http server URLs and
headers must not contain `${`. Only skills and MCP survive; agents, commands, hooks,
LSP servers and output styles are reported as `unsupported_components`.

## Findings (suspected bugs and risks; Python is not fixed, tests pin the behaviour)

- **S1 — enable/edit is code execution.** `POST /install` (`mode=link`) plus `PUT
  /workspace/file` on `mcp.json` changes what a running plugin executes within about a
  second; `install` + `PATCH enabled` runs any `command` found on the user's PATH.
  Pinned: `test_editing_mcp_json_through_the_workspace_changes_what_is_executed`,
  `test_an_external_edit_to_a_linked_package_is_picked_up_by_the_watcher`.
- **S2 — no path confinement.** `workspace/*` `root`, `inspect`, `install`, `update`,
  `create` and `pack` take arbitrary server paths; only the bundled plugin tree is
  protected. Pinned: `test_the_root_is_any_directory_with_a_manifest`,
  `test_inspect_any_directory_on_the_machine`,
  `test_create_destination_may_be_any_path_and_parents_are_created`,
  `test_pack_output_may_be_any_path_and_creates_parents`.
- **S3 — only three env names are reserved.** A plugin may declare `LD_PRELOAD`,
  `PYTHONPATH`, `NODE_OPTIONS`, … as a credential env name, and `mcp.json` `env` may
  set `PATH` and anything else; the host passes them to the child. Pinned:
  `test_other_reserved_environment_names_are_allowed`.
- **S4 — marketplace URL screening has gaps.** Decimal/hex IPv4 forms (`https://2130706433/`)
  are not recognised as addresses by `ipaddress.ip_address`, so `POST /marketplaces`
  accepts and stores them (the fetch-time DNS check is what stops them); the fetch
  resolves the name twice (rebinding window). Pinned:
  `test_add_url_that_is_a_decimal_or_short_ip_is_not_screened`.
- **F1 — the trust review is not redacted.** `redact_inspection` rewrites only
  `mcp_servers`; `trust.remote_hosts[].url` keeps `?token=…` and
  `trust.executable_commands[].args` keeps `--token <value>` in `inspect`, `install`,
  `get` and list responses. Pinned: `test_inspect_trust_review_is_not_redacted`.
- **F2 — secrets at rest.** `credentials.json` is plaintext (`0600` on POSIX, default ACL
  on Windows). Never returned in clear (masked as `********`; tested).
- **B1 — archive names with `.` or empty segments are normalised, not rejected**
  (`a/./b.txt`, `a//b.txt` extract as `a/b.txt`). Pinned in
  `test_upload_normalizes_dot_and_empty_segments_instead_of_rejecting`.
- **B2 — workspace edits leave the recorded digest stale.** Writing into an *installed*
  (managed) package changes it in place, `registry.json` keeps the install-time
  `content_sha256`. Pinned: `test_editing_an_installed_plugin_leaves_its_recorded_digest_stale`.
- **B3 — corrupt marketplace files are `500`.** `GET /marketplaces` and
  `GET /marketplaces/plugins` do not catch the `ValueError` from
  `_read_marketplaces`/`_read_catalog` (the other marketplace routes map it to `422`).
  Pinned (status only): `test_search_with_a_corrupt_cache_is_a_500`,
  `test_listing_with_a_corrupt_registry_is_a_500`.
- **B4 — host-flavour path checks.** Absolute/drive checks use the host's path rules
  (`Path`/`PurePosixPath`), so `/etc/x`, `c:/x` and `\` behave differently on Windows
  and POSIX (the contract tests only pin the portable cases; the zip `\\` case is
  skipped on Windows because `zipfile` folds it).
- **B5 — error detail is the raw exception text.** `FileNotFoundError` becomes the bare
  relative path, other `OSError`s carry host paths and OS wording (`WinError`, `errno`);
  `PluginInstallError` texts embed absolute paths. Tests compare these only where
  portable; Rust cannot match OS wording and should list that in `KNOWN_DIFFERENCES.md`.
- **B6 — `pack` compares the output path unresolved** with the resolved plugin root, so
  an output reached through a symlink or `..` spelling inside the plugin is not
  recognised as inside it.
- **B7 — no automatic restart or health re-check of a crashed stdio server** (read from
  `runner.py`: the session task only waits for `shutdown`; status stays `ready` until a
  refresh; not exercised by a test).
- **B8 — an enabled remote plugin server connects at once**, including over the internet
  (HTTPS) at app start; there is no consent step after install.

## Test map

All under `contract-tests/plugins-marketplace/`; helpers in `plugin_helpers.py`,
fixtures in `conftest.py`, a stdlib stdio MCP server in `fake_mcp_server.py` (answers
`initialize`, `tools/list` with one `echo` tool, `tools/call`, and records `argv`, `cwd`,
`env`, `pid` to `$PLUGIN_DATA/started.json`). Every test uses the harness's temp
data/config/cache/home directories and the provider-free backend; **no network call is
made**: plugins with a remote server are never enabled unless they point at a closed
loopback port, and marketplace sources that would be fetched are seeded on disk.

| File | Covers |
|---|---|
| `test_auth_routes.py` | 401 on all 28 routes (missing and wrong token), a rejected write changes nothing |
| `test_install_lifecycle.py` | inspect (redaction, trust leak F1, any folder), install/link/enable/update/uninstall, registry bytes, duplicates, symlinks, corrupt registry, listing shape and order |
| `test_archives_create_pack.py` | upload and update-upload (extension, traversal, duplicates, symlinks, bombs, modes), `create`, `pack` (determinism, ignores, output rules, bundled tree 409), round trip |
| `test_workspace.py` | tree/read/write/create/delete, every path rule, limits, symlinks, any-root (S2), stale digest (B2) |
| `test_review_files.py` | listing, readme, sensitive-name hiding, redaction by regex and structure, truncation, limits |
| `test_credentials.py` | state, masking, file bytes, validation messages, legacy namespace, invalid definitions, reserved env (S3), corrupt store |
| `test_marketplaces.py` | add/list/delete, URL rules (17 cases), duplicates, sync failure without network, cache search, prepare/install error paths, 500s (B3); `prepare` success is **skipped** (public HTTPS only, no seam) |
| `test_processes.py` | start with expansion, env isolation, status shape, disable/uninstall/update stop the process, force restart, hot reload, last-good, credentials env, invalid definitions, sse skip, missing executable, closed remote port, skills registry feed |

Snapshots: `inspect_valid.json`, `create_tree.json`.

Not covered by contract tests (needs Rust unit tests at Lb): the download paths of
`prepare` (artifact digest/size checks, GitHub archive extraction, Claude→Agent Plugins
normalisation, 15-minute preview expiry), `sync` success and catalog parsing for both
catalog kinds, the DNS/redirect rules of `_fetch_bytes`, the 50 MiB upload cap, the
2 MiB registry cap, Windows locking behaviour of `stop_installation`.

## Lb sizing and dependencies

Python: about 760 lines of routes plus about 3 700 lines under `app/plugin_platform`
(`marketplaces` 1 270, `validator` 790, `installer` 580, `credentials` 290, `registry`
250, `review` 230, `models` 220, `workspace` 200, `trust` 130, `builtins` 75).
**Size L (about 5 000 Rust lines with tests).** Suggested split: Lb1 = platform
(models, validator, registry, installer, workspace, review, trust, credentials, the
non-network routes), Lb2 = marketplaces (fetch with DNS screening, catalog parsers,
archive extraction, Claude normalisation, preview store).

Dependencies:
- **`area-agents-skills-registry`**: `validate_skill_text` (YAML 1.1 front-matter loader)
  to inspect `skills/*/SKILL.md`, and the plugin skill roots hand-off.
- **Plugin MCP runtime** (`plugin_mcp_runtime`, lanes `skills-plugins-runtime` and
  `mcp-client`, unit `agent-runtime`): `refresh(force)`, `stop_installation`,
  `list_status`. Until those lanes are ported, Lb needs the `adapter:plugins-mcp`
  Python bridge (pin breaker) — or the routes stay Python and only the pure parts move.
- **Conductor provenance** (`managed_resource_provider_by_id`, lane `conductor`) for
  `provider`/`managed_*`; a stub returning `null` is faithful when Conductor is unused.
- **Skill cache invalidation** (`team_manager.invalidate_skill_cache`, lane
  `agent-loop-chat`) after every mutation.
- **Settings paths** (`EVOFLUX_DATA_DIR`, `EVOFLUX_CACHE_DIR`; `area-settings-providers`
  or `core`), the shared auth layer, the bundled-plugin folder (empty today).
- New crates: `zip` (with symlink/ratio/size controls), `sha2`, `uuid`, `serde_json`
  with sorted keys, `tempfile`, multipart upload, an HTTPS client with a custom
  resolver (public-address pinning), a path-flavour policy decision for B4.
