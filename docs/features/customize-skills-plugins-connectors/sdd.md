# Customize: skills, connectors (MCP), plugins and hooks

| | |
| --- | --- |
| Status | Implemented (phases 1–5) |
| Area | engine, crates `evo-mcp` `evo-plugins` `evo-hooks`, desktop |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | none |

Status: phase 1 is built (skills and commands, the `skill` tool, `/name`,
the `/` menu, Customize → Skills and Subagents); phase 2a is built
(connectors: the MCP client and shared pool, tools in every chat, Customize
→ Connectors, MCP prompts in `/`) and phase 2b (sign-in for remote servers,
project `.mcp.json` with approval, `@server:uri` resources, per-chat
switches) are built; phase 3 (hooks) and phase 4 (plugins and marketplaces)
are built; phase 5 (tool search, skill usage, the listing budget, shell
lines in skills) is built, `.mcpb` bundles and `context: fork` are not. Paths
are relative to the repository root.

Formats follow open specifications where one exists: the Agent Skills
specification (agentskills.io) for skills, the Model Context Protocol
(modelcontextprotocol.io) for connectors. Everything else is evo's own and
lives in evo's folders (`.evo/`, `~/.evo/`), plus the cross-client Agent
Skills folder `.agents/skills`.

## Phase 1 as built

- `crates/evo-engine/src/customize.rs`: `.agents/skills` (project: the
  working folder and the repository root; user: `~/.agents/skills`) added to
  the skill folders (`resource_dirs.rs`); command files from `.evo/commands`
  and `~/.evo/agent/commands` become skills named after their path
  (`a/b.md` → `a:b`, a skill of the same name wins, the description falls
  back to the first line); `skillOverrides` in `~/.evo/agent/settings.json`
  (`off`, `user-invocable-only`, `name-only`) applied after loading;
  `describe()` behind RPC `list_customizations`.
- `crates/evo-engine/src/skill_tool.rs`: the `skill` tool (`{name,
  arguments?}`); the system-prompt `<available_skills>` listing stays.
- `crates/evo-harness/src/skills.rs` + `agent_harness.rs`: `/name args`
  expands a known skill or command (a bare name finds a unique `ns:name`),
  else a prompt template; `/skill:name` still works. Substitutions:
  `$ARGUMENTS`, `$ARGUMENTS[N]` (0-based), `${SKILL_DIR}`, `\$`, and `$N` in
  command files only (SKILL.md bodies often hold shell snippets).
- `crates/evo-engine/src/agents.rs`: tool names in agent files may be
  PascalCase (`Read` → `read`, `Grep`/`Glob` → `bash`, …); short model family
  aliases (`sonnet`, `opus`, …) mean "the chat's model".
- RPC: `list_customizations`, `set_skill_override {name, state}` (then
  reloads), `reload_resources` — all in the `Command` payload schema
  (`rpc/protocol.rs`).
- Desktop: `features/chat/command-menu.tsx` (the `/` menu: built-ins
  `/clear`, `/compact`, `/fork`, `/customize`, then skills, commands,
  templates; word-prefix matching ignoring `:_-`; ↑↓, Tab completes, Enter
  runs or inserts when the command takes arguments, Esc), the accent token
  and argument hint in `prompt-input.tsx`, the `/name` token in the user's
  bubble, saved `<skill …>` prompts shown as typed (`transcript.ts`
  `typedPrompt`), the "Skill · name" tool row (`tool.tsx`),
  `features/customize/customize-page.tsx` + `stores/customize-store.ts`
  (sidebar → Customize: Skills with a switch and "Who can use it", Agents;
  Connectors, Plugins, Hooks marked Soon). A change is sent to the other idle
  engines as `reload_resources`.

## Phase 2a as built

- `crates/evo-mcp`: `config.rs` (the `mcpServers` file `~/.evo/agent/mcp.json`:
  `command`/`args`/`env`/`cwd` or `type` + `url`/`headers`, `${VAR}` and
  `${VAR:-default}`, evo's `disabled` and `toolPermissions`, unknown keys
  kept), `client.rs` (one connection on `rmcp` 3.9: stdio with `.cmd`
  resolution and no console window on Windows, streamable HTTP and SSE;
  `ClientLifecycleMode::Auto` = the 2026-07-28 stateless protocol with the
  `initialize` handshake as fallback; stderr into the server log; a 401/403
  is "needs-auth"), `pool.rs` (every server connected once: status, tools,
  prompts, a 200-line log; tool names `mcp__<server>__<tool>` cut to 64;
  default permission `allow` for tools annotated read-only, else `ask`;
  results over 100k characters cut). Tests: config, pool, and a real
  round trip against an in-process `rmcp` server; `examples/echo_server.rs`
  (a local stdio server) and `examples/probe.rs` (connect and list).
- Shell `src-tauri/src/mcp.rs`: the pool as app state, started at launch,
  `mcp://changed` on every change, commands `mcp_state`, `mcp_upsert`,
  `mcp_remove`, `mcp_set_enabled`, `mcp_reconnect`, `mcp_set_permission`,
  `mcp_chat_tools`, `mcp_call`, `mcp_get_prompt`; connections close on exit.
- Desktop: `lib/mcp.ts`, `stores/connectors-store.ts`; the engine store adds
  the connectors' tools to every chat's external tools and re-sends them on
  every change; a call to a tool set to "ask" shows the approval prompt in
  the composer (Allow once / Always allow / Deny; "Always allow" saves
  `allow`); `features/customize/connectors-section.tsx` (list with status,
  switch per connector, detail with error, properties, server instructions,
  tools with Allow / Ask / Block, prompts, server log; Add/Edit dialog with
  Command, URL and JSON modes); MCP prompts in the `/` menu as
  `/server:prompt <args>` (the server fills the prompt in, the text is sent);
  tool rows as "Called server · tool".

## Phase 2b as built

- Sign-in (`crates/evo-mcp/src/auth.rs`): OAuth 2.1 on `rmcp`'s `auth`
  feature (metadata discovery, registered / metadata-document / dynamic
  client registration, PKCE, code exchange, refresh through `AuthClient`).
  The browser returns to a one-time `http://127.0.0.1:<port>/callback`;
  tokens per connector in `mcp-auth.json` next to the connectors file (like
  provider credentials in `auth.json`); a URL connector with saved tokens
  connects through `AuthClient`. Shell `mcp_sign_in` (opens the page with the
  opener plugin) / `mcp_sign_out`; Customize shows Sign in (primary when the
  server answered 401/403) and Sign out. Not yet tried against a real
  provider.
- Project servers (`pool.rs`): the nearest `.mcp.json` from a chat's folder
  up to the repository root. Each server is pending until you approve it;
  decisions (and tool permissions) live in the connectors file under
  `projectServers[<root>][<name>]`. Approved servers load as pool entries
  `name#root` (label `name`), connect, and are offered only to chats in that
  project; your own connector of the same name wins. Shell
  `mcp_project_state`, `mcp_open_project` (each chat's tools load opens its
  project), `mcp_set_project_approval`; Customize → Connectors shows the
  project's servers with Approve / Deny and a switch.
- Resources: `resources/list` on connect, `resources/read`
  (`mcp_read_resource`); Customize lists them; `@server:uri` in a message
  is read and attached as `<resource server uri>` blocks when it is sent.
- Composer + menu (`chat-composer.tsx` `PlusMenu`): Attach files, Commands
  and skills, Connectors (a switch per connector for this chat, stored as
  `chatConnectorsOff` in the UI store; the chat's tools are re-sent) and
  Resources (inserts `@server:uri`).
- Tests: 10 in `evo-mcp` (credential store, the callback listener, project
  approval and scoping).

## Phase 3 as built

- `crates/evo-hooks`: `config.rs` reads `hooks` from user settings and a
  trusted project's `.evo/settings.json` (lenient `//` comments,
  `disableAllHooks`, problems reported instead of failing), matchers (`*` or
  empty, a `|`/`,` list of exact names, else a regex; tool names also match
  their PascalCase form, `Bash` covers `bash` and `powershell`), duplicate
  handlers run once. `run.rs` runs `command` handlers (shell form through
  Git Bash or PowerShell on Windows, `sh` elsewhere; exec form with `args`;
  no console window; the event as JSON on stdin; `EVO_PROJECT_DIR`) and
  `http` handlers (POST the event; `${VAR}` in headers), in parallel, with
  timeouts (600 s commands, 60 s HTTP, 30 s for prompt hooks); exit 0 / 2 /
  other and the JSON output combine into one outcome (deny over ask over
  allow). `prompt` and `agent` handlers are reported as skipped. 6 tests run
  real processes.
- `crates/evo-engine/src/hooks.rs`: the session's hooks (loaded at start,
  re-read on `reload_resources` / `list_hooks`), a log of the last 100 runs.
  `SessionStart` (context waits for the first prompt), `UserPromptSubmit`
  (in the RPC prompt path, `modes.rs` `rpc_prompt_hooks`: block → the prompt
  fails with "Blocked by a hook: …"; context rides after the prompt in a
  `<hook-context>` block, hidden again in the transcript by `typedPrompt`),
  `PreToolUse` (wraps `before_tool_call` in front of the extension approval
  hook: deny → the call fails with the reason, ask → the approval prompt in
  the composer, allow, `updatedInput`), `PostToolUse` /
  `PostToolUseFailure` (`after_tool_call`: feedback and context appended to
  the result, messages in `details.hooks`), `Stop` after a prompt run (in the
  background; continuing the run is not supported yet), `SessionEnd` on
  shutdown (1.5 s). The tool-call hooks are installed when a session starts
  with hooks for those events, so hooks added for them apply to chats started
  afterwards. RPC `list_hooks`, `set_hooks_disabled`.
- Desktop: Customize → Hooks (`features/customize/hooks-section.tsx`): on/off
  for all hooks, problems, hooks by event with matcher, what runs and
  whose, buttons to open the settings files, the recent runs (result, reason,
  duration), and an example.
- Checked end to end with the real engine: a `UserPromptSubmit` hook that
  exits 2 blocked a prompt before any model call, and `list_hooks` showed the
  run.

## Phase 4 as built

- `crates/evo-plugins`: `manifest.rs` loads a plugin folder (optional
  `.evo-plugin/plugin.json`, else `.claude-plugin/plugin.json`, else
  `plugin.json`; default layout `skills/`,
  `commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `bin/`; listed
  `skills`/`hooks`/`mcpServers` add, listed `commands`/`agents` replace;
  paths must stay inside the plugin; a root `SKILL.md` makes it one skill;
  `${PLUGIN_ROOT}`, `${PLUGIN_DATA}` (also `${CLAUDE_PLUGIN_ROOT}`,
  `${CLAUDE_PLUGIN_DATA}`), `${user_config.KEY}` filled in in hooks
  and servers). `marketplace.rs`: sources `owner/repo[#ref]` (GitHub), any
  git URL `[#ref]` (`https`, `http`, `ssh`, `git@`, `git`, `file`), or a
  folder; catalog `.evo-plugin/marketplace.json`,
  `.claude-plugin/marketplace.json` or `marketplace.json`;
  plugin sources: a path in the marketplace (`metadata.pluginRoot` for bare
  names), `github`, `url`/`git`, `git-subdir` (a `sha`/`ref` pins). `store.rs`
  in `<agent dir>/plugins`: `marketplaces.json` + clones, installed copies in
  `cache/<marketplace>/<plugin>/<version>` (manifest version, else the
  entry's, else the commit), `data/<id>`, `installed.json` (version, path,
  on/off, settings); install, install a folder in place (`name@local`),
  update (fetch the marketplace again, reinstall; keeps on/off and
  settings), uninstall, enable, settings. Git runs without a window and
  never prompts. 5 tests, including real clones over `file://`.
- Engine (`plugins.rs`): the plugins that are on add skills and commands
  named `plugin:name` (`/plugin:name`; a unique bare `/name` finds them),
  subagents `plugin:name`, their hooks (source `plugin:<name>`), and `bin/`
  first on PATH for the shell tools; re-read on `reload_resources`.
  `list_customizations` names the plugin of each skill and subagent.
- Shell (`src-tauri/src/plugins.rs`): `plugins_state` (installed with what
  each adds, marketplaces, the catalog) and commands to add, fetch and
  remove marketplaces and to install, install a folder, update, uninstall,
  switch and configure plugins. After each change the pool gets the enabled
  plugins' servers (`set_plugin_servers`: keys `plugin:<plugin>:<server>`,
  tools `mcp__plugin_<plugin>_<server>__<tool>`, permissions saved under
  `pluginServers` in the connectors file) and `plugins://changed` makes every
  ready chat re-read its resources.
- Desktop: Customize → Plugins (`plugins-section.tsx`): Installed (switch,
  contents, settings form from `userConfig`, update, uninstall, show in
  folder), Discover (the marketplaces' plugins with Install / Reinstall),
  Marketplaces (add by `owner/repo`, git URL with `#ref`, or folder; fetch
  again; remove), Add from folder. Plugin skills and subagents are grouped
  as "Plugin · name" in their sections, plugin hooks are labelled.
- Checked end to end with the real engine: an installed plugin's skill,
  command (with its argument hint), subagent (PascalCase tools mapped) and
  hook (`${PLUGIN_ROOT}` filled in) all appeared.
- Not yet: npm and archive plugin sources, `userConfig` secrets in the OS
  keychain (they are saved with the other settings), project-level plugin
  switches.

## Phase 5 as built

- **Connector tool search** (`apps/desktop/src/lib/mcp.ts`, engine-store):
  past 40 connector tools in a chat, or about 60k characters of names,
  descriptions and schemas, the chat gets two tools instead of all of them:
  `mcp_search_tools {query, limit?}` (words scored against names and
  descriptions, or `select:a,b` for exact names; returns names, descriptions
  and input schemas; its description lists the servers and their tool
  counts) and `mcp_call_tool {name, arguments}`, which runs the named tool
  through the same path as a direct call, so Allow / Ask / Block still apply.
  The transcript labels a call by the tool it ran.
- **Skill usage** (`crates/evo-engine/src/skill_runtime.rs`): each run, by
  the `skill` tool or `/name`, counts in `<agent dir>/skill-usage.json`
  (`{name: {uses, lastUsed}}`, written beside and renamed so engines never
  read half a file). `list_customizations` returns `uses`, `lastUsed`.
- **Listing budget**: descriptions in the model's skill list are cut to 1536
  characters; past `skillListingBudgetChars` (default 8000) the least used
  skills are listed by name only until it fits (`nameOnlyForBudget` in the
  listing). They still run by `/name` and the `skill` tool.
- **Shell lines in skills**: `` !`command` `` inline, or a fenced block
  opened with ```` ```! ````, runs when the skill loads and is replaced by its
  output — Git Bash or PowerShell on Windows, `sh` elsewhere, in the
  session's folder, `${SKILL_DIR}` filled in, 120 s each, output cut at 20k
  characters. Commands come from the skill file before arguments are filled
  in, so text passed to a skill never runs. The `skill` tool runs them; for
  `/name` the engine expands such a skill in the prompt path (other skills
  are still expanded by the harness). `disableSkillShellExecution: true`
  turns it off.
- **RPC** `set_skill_settings {listingBudget?, shellDisabled?}` (a budget of
  0 restores the default); `list_customizations` returns `settings`.
- **Desktop**: Customize → Skills shows uses per skill (list and detail,
  with the last use), "name only, to fit the listing budget", and a Skill
  settings card under the list (budget, run shell lines).
- Not yet: `.mcpb` bundles, `context: fork` for skills.

## Custom instructions (built)

- Customize → Instructions edits the standing instructions the engine
  already puts in every system prompt (`evo_harness::context_files`):
  **Personal** — the instruction file in the agent dir
  (`~/.evo/agent/AGENTS.md`), for every chat; **This project** — the one in
  the chat's folder, read once the folder is trusted; **Also read** — the
  files of the parent folders, shown read-only.
- In each folder the first existing name of `CONTEXT_FILE_CANDIDATES` is the
  file read, so it is the file edited; a folder with none gets `AGENTS.md`.
  Saving empty text removes the file.
- Engine: `crates/evo-engine/src/instructions.rs`; RPC `list_instructions`
  and `save_instructions {scope: personal|project, content}`, which re-reads
  the chat's resources; the desktop then reloads every idle chat, so the
  change applies from the next message.
- Desktop: `features/customize/instructions-section.tsx` — list (Personal,
  the project, parent folders) and an editor with Edit / Preview, Save
  (`Ctrl+S`), Revert, unsaved marks, and a note when the folder is not
  trusted.

## Goal

One place, **Customize**, for everything that shapes what the agent can do —
skills, agent types, connectors, plugins, hooks — and a chat input that
reaches them: `/` opens commands and skills, `@` mentions files, agents and
MCP resources, `+` holds files, commands and per-chat connector switches.

Non-goals: account sync, a hosted directory, managed/enterprise policy
files, LSP servers, output styles, monitors and themes inside plugins (a
plugin that has them still loads; those parts are listed as unsupported).

## Before phase 1 (what we built on)

- **Skills**: `crates/evo-harness/src/skills.rs` loads `SKILL.md` folders
  (name/description/`disable-model-invocation`, name rules as diagnostics)
  from `.evo/skills`, `~/.evo/agent/skills`, `skillDirs`, packages and
  extensions. The catalog goes into the system prompt as
  `<available_skills>`; the model opens `SKILL.md` with its read tool.
  `/skill:<name> args` is expanded on prompt, steer and follow-up
  (`AgentHarness::expand_skill_input`). Project folders follow `trust.rs`.
- **Prompt templates**: `prompt_templates.rs` (`.evo/prompts`, `$1`,
  `$ARGUMENTS`).
- **Commands**: extension action `list_commands` merges built-ins, extension
  commands, templates and skills; RPC `get_commands` returns only extension
  commands.
- **Hooks**: in-process only (`evo-agent` `AgentLoopConfig`): the engine
  installs `before_tool_call` (extensions can deny a call); `after_tool_call`
  is unused. 38 extension `EventTag`s.
- **Plugins**: native cdylib extensions (`evo-plugin-sdk`) and project
  packages (`.evo/packages/<name>` with `skills/`, `prompts/`).
- **Agents**: `crates/evo-engine/src/agents.rs` reads `.evo/agents/*.md` and
  `~/.evo/agent/agents/*.md`.
- **MCP**: none.
- **Desktop-provided tools**: `configure_external_tools` /
  `external_tool_request` / `external_tool_response` carry the browser and
  session tools into every engine; MCP tools will ride on it.

## Formats

**Skills** (Agent Skills specification). A folder with `SKILL.md`: `name`
(1–64, `a-z0-9-`, no edge or double hyphen, equals the folder),
`description` (1–1024), optional `license`, `compatibility`, `metadata`,
`allowed-tools`. evo also reads `when_to_use`, `argument-hint`,
`user-invocable` (default true), `disable-model-invocation` (default false),
`model`. Command files (`.evo/commands/x.md`) are a single-file form of a
skill; subfolders become `a:b`. Progressive disclosure: only name and
description are always in context, the body loads when invoked, files under
the skill load on demand. Body substitutions: `$ARGUMENTS`,
`$ARGUMENTS[N]` / `$N` (0-based), `${SKILL_DIR}`; later `${PROJECT_DIR}`,
`${SESSION_ID}` and `` !`cmd` `` lines that run before the model sees the
skill.

**Connectors** (MCP). Config `{"mcpServers": {name: {command, args, env} |
{type: "http"|"sse", url, headers, oauth}}}` with `${VAR}` /
`${VAR:-default}`. Tools are named `mcp__<server>__<tool>`; prompts become
`/server:prompt`; resources are `@server:uri`. Remote servers sign in with
OAuth 2.1 (PKCE, RFC 9728 discovery, dynamic or metadata-document client
registration, or a given client id). Status: Connected, Needs sign-in,
Failed to connect, Pending approval, Off. Per-tool permission: Always allow /
Needs approval / Blocked. The 2026-07-28 MCP revision drops the
`initialize` handshake (stateless, `server/discover` probe); most servers
still speak 2025-11-25, so the client does both.

**Plugins** (evo's own). A folder with an optional `.evo-plugin/plugin.json`
(`name` required; version, description, author, homepage, repository,
license, keywords, component paths, `userConfig`, `dependencies`,
`defaultEnabled`). Default layout: `skills/`, `commands/`, `agents/`,
`hooks/hooks.json`, `.mcp.json`, `bin/` (added to PATH). Components are
namespaced `plugin:name`; MCP tools `mcp__plugin_<plugin>_<server>__<tool>`.
`${PLUGIN_ROOT}` (the installed version) and `${PLUGIN_DATA}` (kept across
updates) are substituted in hooks, MCP config and bodies. `userConfig`
values go to settings, sensitive ones to the OS keychain, and reach hooks as
`EVO_PLUGIN_OPTION_<KEY>`. Marketplaces are `.evo-plugin/marketplace.json`
(`name`, `owner`, `plugins[]` with sources: relative path, `github`, git
`url`, `git-subdir`, `archive`). Ids are `name@marketplace`;
`enabledPlugins` in user and project settings; installs are cached per
version.

**Hooks** (evo's own). `{"hooks": {Event: [{matcher, hooks: [handler]}]}}`
from settings files, plugins and skill/agent frontmatter. Handlers:
`command` (shell or exec form `args`), `http`, `prompt`; later `mcp_tool`,
`agent`. Matchers: `*`/empty, a `|`-list of exact names, else a regex. JSON
on stdin (`session_id`, `cwd`, `hook_event_name`, per-event fields). Exit 0
= ok (stdout JSON parsed; plain stdout becomes context for prompt-submit and
session-start), exit 2 = block with stderr, other = non-blocking error.
JSON output: `continue`, `stopReason`, `systemMessage`, `suppressOutput`,
`hookSpecificOutput` (`permissionDecision` allow/deny/ask/defer,
`updatedInput`, `additionalContext`), `decision: "block"` for PostToolUse /
Stop. Hooks of an event run in parallel; command hooks time out after 600 s.

## Design

### Where things live

```
crates/evo-customize   (new)  discovery + manifests, shared by engine and shell
  plugins.rs       plugin.json, component resolution, namespacing, variables
  marketplace.rs   marketplace.json, sources (git via the git CLI, archive, path)
  install.rs       ~/.evo/plugins/{cache,data,marketplaces}, installed.json
  hooks_config.rs  hook config parsing + merging from every source
crates/evo-hooks       (new)  runs hooks: command / http / prompt, JSON in/out
crates/evo-mcp         (new)  MCP client on `rmcp`: stdio, streamable HTTP,
                              legacy SSE, OAuth 2.1, config + scopes
crates/evo-engine             skills/commands (customize.rs), the skill tool,
                              `/name` expansion, hook call sites
apps/desktop/src-tauri        MCP pool (one connection per server, shared by
                              every chat), OAuth browser flow
apps/desktop/src              Customize view, composer menus, transcript rows
```

Why MCP sits in the shell, not the engine: the app runs one engine process
per chat. A server started per engine would mean N copies of every stdio
server, N sign-ins and no single status to show. The shell keeps one pool,
shows its status in Connectors, and hands each chat the tools of the
connectors enabled for it through the existing external-tools path.
`evo-mcp` stays a plain library, so the engine can host it too if a headless
mode needs MCP later.

### Files read

| Kind | User | Project | Plugin |
| --- | --- | --- | --- |
| Skills | `~/.evo/agent/skills`, `~/.agents/skills` | `.evo/skills`, `.agents/skills` (working folder and repo root) | `skills/` |
| Commands | `~/.evo/agent/commands` | `.evo/commands`, `.evo/prompts` (templates) | `commands/` |
| Agents | `~/.evo/agent/agents` | `.evo/agents` | `agents/` |
| Hooks | `~/.evo/agent/settings.json` | `.evo/settings.json` | `hooks/hooks.json` |
| MCP | `~/.evo/agent/mcp.json` (connectors added in the app) | `.mcp.json` (asks first) | `.mcp.json`, `mcpServers` |
| Plugins | `~/.evo/plugins` (installed), `enabledPlugins` | `.evo/settings.json` `enabledPlugins` | — |

Precedence on name clashes: project over user over plugin, evo's folders
over `.agents`, a skill over a command. Project-level anything follows the
existing folder trust (`trust.rs`).

### Skills and commands (engine)

Built in phase 1 (above). Still to do: the rest of the frontmatter
(`allowed-tools` pre-approves those tools for that turn, `model` / `effort`
for that turn, `context: fork` runs the skill in a child agent), moving the
catalog into the `skill` tool's description within a budget (1% of the
context window, least-used first), `` !`cmd` `` through the sandbox policy
(2-minute limit, off for untrusted folders), and file watching.

### Connectors (MCP)

- `evo-mcp` on `rmcp`: stdio, streamable HTTP, SSE (deprecated, kept for old
  servers); tries the 2025-11-25 `initialize`, falls back to the stateless
  2026-07-28 form; `tools/list|call`, `prompts/list|get`,
  `resources/list|read`, `list_changed`. Elicitation shows a desktop dialog.
- Config merge: plugin < user (`~/.evo/agent/mcp.json`) < project
  `.mcp.json` (Pending approval until the user allows it, remembered per
  project). `${VAR}` expansion.
- OAuth 2.1 in the shell: on 401 the connector shows "Needs sign-in";
  Connect opens the system browser (loopback redirect on 127.0.0.1), PKCE,
  RFC 9728 metadata, dynamic registration or the configured client id;
  tokens in the OS keychain (`keyring`), refreshed on expiry.
- Pool in `src-tauri/src/mcp.rs`: start on first use or at launch per
  connector, restart with backoff, status events to the UI, logs per server
  (Settings → Logs).
- Chats: each chat has a set of enabled connectors (default: all connected);
  the composer's `+` → Connectors switches them. The shell sends the enabled
  servers' tools with `configure_external_tools` and runs calls. Per-tool
  permission maps onto the existing approval prompt. Output over 25k tokens
  is cut with a note.
- Many tools: past 40 tools or about 60k characters, they sit behind
  `mcp_search_tools` and `mcp_call_tool` (phase 5, above).

### Hooks

- `evo-hooks` runs `command`, `http` and `prompt` (a one-shot model call
  returning `{ok, reason}`) handlers with the matchers, stdin JSON, exit
  codes, JSON output and timeouts above. Env: `EVO_PROJECT_DIR`,
  `EVO_PLUGIN_ROOT`, `EVO_PLUGIN_DATA`, `EVO_PLUGIN_OPTION_*`.
- Events wired in the engine: SessionStart, UserPromptSubmit, PreToolUse
  (the existing `before_tool_call` gate: deny / ask / allow / `updatedInput`),
  PostToolUse and PostToolUseFailure (`after_tool_call`), Stop and
  SubagentStart / SubagentStop (the `agent` tool), PreCompact / PostCompact,
  SessionEnd. Notification is raised by the desktop.
- What the user sees: a blocked call shows the hook's reason on the tool
  row; `systemMessage` shows as a warning line; hook errors are a muted event
  line; `additionalContext` is never shown. Customize → Hooks lists every
  hook with its source and command, read-only, with "Turn off all hooks".

### Plugins and marketplaces

- `evo-customize::plugins` loads a plugin folder (manifest optional), applies
  component path rules (`commands`/`agents` replace defaults, `skills`/`hooks`
  /`mcpServers` add), namespaces everything `plugin:name`, substitutes
  `${PLUGIN_ROOT}`, `${PLUGIN_DATA}`, `${user_config.X}`, and adds `bin/` to
  the PATH of the engine's shell tool.
- Marketplaces: add by `owner/repo`, git URL, local folder or URL to a
  `marketplace.json`; cloned into `~/.evo/plugins/marketplaces/<name>`;
  "Check for updates" pulls. Plugin sources: relative, github, git url,
  git-subdir, archive.
- Install: copy into `~/.evo/plugins/cache/<marketplace>/<plugin>/<version>`,
  record in `~/.evo/plugins/installed.json`, enable in the chosen scope (user
  `~/.evo/agent/settings.json`, project `.evo/settings.json`). Upload a
  `.zip`. `userConfig` gets a form on install.
- Engines pick up changes on the next turn (no restart); MCP servers from a
  plugin join the pool when it is enabled.

### Desktop

- **Customize view** (built): Skills, Agents, Connectors, Plugins, Hooks; a
  scope filter (All / Personal / Project); a search box; rows grouped by
  source with a switch; a detail pane with the instructions. To come:
  Connectors (status, Connect / Reconnect, tools with permission selects,
  "Add connector" dialog, "Pending approval" project servers), Plugins (Your
  plugins / Discover from added marketplaces / Marketplaces; a plugin page
  with Skills, Commands, Agents, Connectors, Hooks; Disable, Remove,
  Update), Hooks.
- **Composer**: the `/` menu (built); MCP prompts join it in phase 2. `@`
  adds files (exists), agents (`@agent-name`) and MCP resources
  (`@server:uri`). `+` menu: Add files, Commands, Connectors (per-chat
  switches, Manage connectors), Plugins.
- **Transcript**: "Skill · name" rows and the `/name` token (built); hook
  blocks and messages as above; MCP tool rows show the connector's icon and
  name.

## Phases

1. **Skills and commands** — built (see above).
2. **Connectors (MCP).** `evo-mcp`, the shell pool, OAuth, `.mcp.json`
   approval, tools through external tools with per-tool permission, MCP
   prompts in `/`, `@` resources. Customize → Connectors, Add connector,
   the composer `+` menu with per-chat switches.
3. **Hooks.** `evo-hooks`, config from every source, the engine call sites,
   transcript messages, Customize → Hooks.
4. **Plugins and marketplaces.** Loader, namespacing, variables, `bin/`,
   marketplaces, install / enable / update / remove, `userConfig`, upload.
   Customize → Plugins; plugin skills, agents, hooks and MCP flow into
   phases 1–3.
5. **Polish.** MCP tool search for large tool sets, `` !`cmd` `` lines,
   usage counts per skill and the listing budget — built; `context: fork`
   and `.mcpb` bundles — not yet.

Each phase ships on its own; plugins come last because they only bundle the
parts the earlier phases add.

## Open questions

- Hooks run in the engine process with the user's permissions; project hooks
  from an untrusted folder stay off until the folder is trusted.
- Hook matchers written with PascalCase tool names (`Bash`, `Edit`) get the
  same alias table agent files use.
- The 2026-07-28 MCP revision is new; check `rmcp`'s support before phase 2.
