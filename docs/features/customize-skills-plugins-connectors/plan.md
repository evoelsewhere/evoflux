# Customize: skills, connectors (MCP), plugins and hooks — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | none |

## 1. Context and constraints

Paths are relative to the repository root.

Open specifications: the Agent Skills specification (agentskills.io) for
skills, the Model Context Protocol (modelcontextprotocol.io) for connectors.
Everything else is evo's own and lives in evo's folders (`.evo/`, `~/.evo/`),
plus the cross-client Agent Skills folder `.agents/skills`.

What existed before phase 1:

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
  session tools into every engine; connector tools ride on it.

Constraint: the app runs one engine process per chat
([ADR 0003](../../architecture/decisions/0003-engine-runs-as-a-child-process-per-chat.md)),
which decides where the MCP pool lives (3.1, section 4).

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | Skills, hooks, plugin resources and instructions are in the engine. The shell hosts the MCP pool and plugin installs — native, cross-chat resources the ADD assigns to the shell ([ADD 4](../../architecture/README.md#4-process-view)); connector tools reach the engine as external tools and the engine still runs the loop and the permission checks. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-mcp`, `evo-hooks` and `evo-plugins` are plain libraries; `evo-mcp` could be hosted by the engine for a headless mode. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | New RPC commands are in the `Command` payload schema (`crates/evo-engine/src/rpc/protocol.rs`) and ship with their desktop callers. |
| Models come from models.dev; no hardcoded model facts | ok | Short model family aliases in agent files mean "the chat's model"; no model facts are added. |
| Real engine in the app; settings and credentials reload live | ok | Changes reach idle engines as `reload_resources`; plugin and connector changes re-send tools ([ADR 0005](../../architecture/decisions/0005-real-engine-and-live-reload.md)). |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Project skills, hooks and instructions follow folder trust; project `.mcp.json` servers wait for approval; connector tools pass Allow / Ask / Block and the approval prompt; skill arguments never run as shell. Gap: skill shell lines do not yet go through the sandbox policy (FR-45, planned). |
| Desktop UI structure and `DESIGN.md` | ok | Customize sections are features reading `customize-store` and `connectors-store`; engine calls go through the engine store. |

## 3. Design

### 3.1 Overview

```text
crates/evo-mcp       MCP client on rmcp: config, client (stdio, streamable HTTP, SSE),
                     auth (OAuth 2.1), pool (one connection per server)
crates/evo-hooks     hook config + matchers; runs command / http handlers, JSON in/out
crates/evo-plugins   plugin manifests, marketplaces, the install store
crates/evo-engine    skills/commands (customize.rs), skill tool, skill runtime,
                     hook call sites (hooks.rs), plugin resources (plugins.rs),
                     instructions, agents
apps/desktop/src-tauri   MCP pool as app state + OAuth browser flow (mcp.rs),
                         plugin installs (plugins.rs)
apps/desktop/src         Customize page, composer menus, transcript rows
```

Why MCP sits in the shell, not the engine: the app runs one engine process
per chat. A server started per engine would mean N copies of every stdio
server, N sign-ins and no single status to show. The shell keeps one pool,
shows its status in Connectors, and hands each chat the tools of the
connectors enabled for it through the existing external-tools path.
`evo-mcp` stays a plain library, so the engine can host it too if a
headless mode needs MCP later.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| engine | `crates/evo-engine/src/customize.rs`, `resource_dirs.rs` | `.agents/skills` folders added to the skill folders; command files from `.evo/commands` and `~/.evo/agent/commands` become skills named after their path; `skillOverrides` applied after loading; `describe()` behind `list_customizations`. | FR-1, FR-2, FR-3, FR-5, FR-12 |
| engine | `crates/evo-engine/src/skill_tool.rs` | The `skill` tool; the `<available_skills>` listing stays. | FR-6 |
| engine | `crates/evo-engine/src/skill_runtime.rs` | Usage counts, the listing budget, shell lines in skills; expands shell-line skills for `/name` in the prompt path. | FR-13, FR-14, FR-15, FR-16, NFR-3, NFR-6 |
| crate | `crates/evo-harness/src/skills.rs`, `agent_harness.rs` | Skill loading and frontmatter; `/name args` expansion and substitutions. | FR-4, FR-7, FR-8 |
| crate | `crates/evo-harness/src/context_files.rs` | `CONTEXT_FILE_CANDIDATES`: which instruction file a folder has. | FR-40 |
| engine | `crates/evo-engine/src/agents.rs` | PascalCase tool names and model family aliases in agent files. | FR-9 |
| engine | `crates/evo-engine/src/hooks.rs`, `modes.rs` (`rpc_prompt_hooks`) | The session's hooks, the event call sites, the run log; RPC `list_hooks`, `set_hooks_disabled`. | FR-31, FR-32 |
| engine | `crates/evo-engine/src/plugins.rs` | Resources from enabled plugins: skills, commands, subagents, hooks, `bin/` on PATH. | FR-36 |
| engine | `crates/evo-engine/src/instructions.rs` | RPC `list_instructions`, `save_instructions`. | FR-39, FR-40 |
| protocol | `crates/evo-engine/src/rpc/protocol.rs` | The `Command` payload schema for the new RPC commands. | FR-5, FR-16, FR-32, FR-39 |
| crate | `crates/evo-mcp/src/config.rs` | The `mcpServers` file, variables, `disabled`, `toolPermissions`, unknown keys kept. | FR-17 |
| crate | `crates/evo-mcp/src/client.rs` | One connection on `rmcp` 3.9: stdio (with `.cmd` resolution and no console window on Windows), streamable HTTP, and SSE (deprecated, kept for old servers); `ClientLifecycleMode::Auto`; `tools/list\|call`, `prompts/list\|get`, `resources/list\|read`, `list_changed`; stderr into the server log; a 401/403 is "needs-auth". | FR-18, NFR-2 |
| crate | `crates/evo-mcp/src/pool.rs` | Every server connected once: status, tools, prompts, resources, log; tool names; default permissions; result cut; project servers; plugin servers. | FR-18, FR-19, FR-20, FR-21, FR-25, FR-26, FR-36 |
| crate | `crates/evo-mcp/src/auth.rs` | OAuth 2.1, loopback callback, token store. | FR-24 |
| crate | `crates/evo-mcp/examples/echo_server.rs`, `probe.rs` | A local stdio server; connect and list. | — (developer aids) |
| crate | `crates/evo-hooks/src/config.rs` | Reads `hooks` from user settings and a trusted project's `.evo/settings.json` (lenient `//` comments, `disableAllHooks`, problems reported instead of failing); matchers; duplicate handlers run once. | FR-29, NFR-4 |
| crate | `crates/evo-hooks/src/run.rs` | Runs `command` handlers (shell form through Git Bash or PowerShell on Windows, `sh` elsewhere; exec form with `args`; no console window; the event as JSON on stdin; `EVO_PROJECT_DIR`) and `http` handlers, in parallel, with timeouts; combines exit codes and JSON output into one outcome. | FR-30, NFR-2 |
| crate | `crates/evo-plugins/src/manifest.rs` | Loads a plugin folder (manifest optional; default layout; listed `skills`/`hooks`/`mcpServers` add, listed `commands`/`agents` replace; paths must stay inside the plugin; a root `SKILL.md` makes it one skill; variables filled in in hooks and servers). | FR-33, FR-38 |
| crate | `crates/evo-plugins/src/marketplace.rs` | Marketplace and plugin sources; catalogs. | FR-34 |
| crate | `crates/evo-plugins/src/store.rs` | The install store: install, update, uninstall, enable, settings. | FR-35, NFR-2 |
| desktop shell | `apps/desktop/src-tauri/src/mcp.rs` | The pool as app state, started at launch; `mcp://changed`; Tauri commands; sign-in; connections close on exit. | FR-18, FR-22, FR-24, FR-25, FR-26 |
| desktop shell | `apps/desktop/src-tauri/src/plugins.rs` | `plugins_state` and plugin commands; `set_plugin_servers`; `plugins://changed`. | FR-35, FR-36 |
| desktop UI | `apps/desktop/src/lib/mcp.ts`, `stores/connectors-store.ts`, `stores/engine-store.ts` | Connector tools in every chat's external tools, re-sent on change; approvals; tool search. | FR-19, FR-20, FR-28, NFR-5 |
| desktop UI | `apps/desktop/src/features/chat/command-menu.tsx` | The `/` menu. | FR-10, FR-23 |
| desktop UI | `apps/desktop/src/components/ai-elements/prompt-input.tsx`, `features/chat/transcript.ts` (`typedPrompt`), `components/ai-elements/tool.tsx` | Accent token and hint, `/name` in the bubble, saved prompts as typed, tool rows. | FR-11, FR-23, FR-28, FR-31 |
| desktop UI | `apps/desktop/src/features/chat/chat-composer.tsx` (`PlusMenu`), `stores/ui-store.ts` | The `+` menu and per-chat connector switches (`chatConnectorsOff`). | FR-27 |
| desktop UI | `apps/desktop/src/features/customize/customize-page.tsx`, `stores/customize-store.ts` | **Customize** page: Skills, Agents, scope filter, search; skill settings card. | FR-5, FR-12, FR-13, FR-14, FR-16 |
| desktop UI | `apps/desktop/src/features/customize/connectors-section.tsx` | **Customize → Connectors**. | FR-22, FR-24, FR-25, FR-26 |
| desktop UI | `apps/desktop/src/features/customize/hooks-section.tsx` | **Customize → Hooks**. | FR-32 |
| desktop UI | `apps/desktop/src/features/customize/plugins-section.tsx` | **Customize → Plugins**. | FR-37 |
| desktop UI | `apps/desktop/src/features/customize/instructions-section.tsx` | **Customize → Instructions**. | FR-39 |

### 3.3 Interfaces

#### Engine RPC

| Command | Params | Effect |
| --- | --- | --- |
| `list_customizations` | — | skills, commands, agents with source, plugin, `uses`, `lastUsed`, `nameOnlyForBudget`; `settings` |
| `set_skill_override` | `{name, state}` | `off` · `user-invocable-only` · `name-only`; then reloads |
| `set_skill_settings` | `{listingBudget?, shellDisabled?}` | a budget of 0 restores the default |
| `reload_resources` | — | re-reads skills, commands, agents, hooks, plugins |
| `list_hooks` | — | hooks, problems, recent runs (re-reads the config) |
| `set_hooks_disabled` | `{disabled}` | `disableAllHooks` |
| `list_instructions` | — | personal, project, parent folders |
| `save_instructions` | `{scope: personal\|project, content}` | writes (empty removes), re-reads the chat's resources |

#### Tauri commands and events (shell)

- MCP: `mcp_state`, `mcp_upsert`, `mcp_remove`, `mcp_set_enabled`,
  `mcp_reconnect`, `mcp_set_permission`, `mcp_chat_tools`, `mcp_call`,
  `mcp_get_prompt`, `mcp_sign_in` (opens the page with the opener plugin),
  `mcp_sign_out`, `mcp_project_state`, `mcp_open_project` (each chat's tools
  load opens its project), `mcp_set_project_approval`, `mcp_read_resource`.
  Event `mcp://changed` on every change.
- Plugins: `plugins_state` (installed with what each adds, marketplaces, the
  catalog), `plugin_marketplace_add`, `plugin_marketplace_update`,
  `plugin_marketplace_remove`, `plugin_install`, `plugin_install_folder`,
  `plugin_update`, `plugin_uninstall`, `plugin_set_enabled`,
  `plugin_set_config`. Event `plugins://changed` makes every ready chat
  re-read its resources.

#### Agent tools

```text
skill            { name, arguments? }
mcp__<server>__<tool>                     connector tools (cut to 64 characters)
mcp__plugin_<plugin>_<server>__<tool>     plugin connector tools
mcp_search_tools { query, limit? }        words scored against names and descriptions,
                                          or "select:a,b" for exact names; returns names,
                                          descriptions and input schemas; its description
                                          lists the servers and their tool counts
mcp_call_tool    { name, arguments }      runs the named tool through the direct-call path
```

#### Skills format (Agent Skills specification)

A folder with `SKILL.md`: `name` (1–64, `a-z0-9-`, no edge or double
hyphen, equals the folder), `description` (1–1024), optional `license`,
`compatibility`, `metadata`, `allowed-tools`. evo also reads `when_to_use`,
`argument-hint`, `user-invocable` (default true), `disable-model-invocation`
(default false), `model`. Command files (`.evo/commands/x.md`) are a
single-file form of a skill; subfolders become `a:b`. Progressive
disclosure: only name and description are always in context, the body loads
when invoked, files under the skill load on demand. Body substitutions:
`$ARGUMENTS`, `$ARGUMENTS[N]` (0-based), `${SKILL_DIR}`, `\$`, `$N` (command
files only); shell lines `` !`cmd` `` and ```` ```! ```` blocks; planned:
`${PROJECT_DIR}`, `${SESSION_ID}`.

#### Connectors format (MCP)

```jsonc
{
  "mcpServers": {
    "<name>": { "command": "…", "args": [], "env": {}, "cwd": "…" },
    "<name>": { "type": "http" | "sse", "url": "…", "headers": {}, "oauth": {} },
    // evo's keys on any server: "disabled", "toolPermissions"
  },
  "projectServers": { "<root>": { "<name>": { /* approval, tool permissions */ } } },
  "pluginServers":  { /* tool permissions of plugin connectors */ }
}
```

`${VAR}` / `${VAR:-default}` expand. Tools are named
`mcp__<server>__<tool>`; prompts become `/server:prompt`; resources are
`@server:uri`. Remote servers sign in with OAuth 2.1 (PKCE, RFC 9728
discovery, dynamic or metadata-document client registration, or a given
client id). Status: Connected, Needs sign-in, Failed to connect, Pending
approval, Off. Per-tool permission: Always allow / Needs approval / Blocked
(Allow / Ask / Block in the UI). The 2026-07-28 MCP revision drops the
`initialize` handshake (stateless, `server/discover` probe); most servers
still speak 2025-11-25, so the client does both
(`ClientLifecycleMode::Auto`).

#### Plugins format (evo's own)

A folder with an optional `.evo-plugin/plugin.json` (`name` required;
version, description, author, homepage, repository, license, keywords,
component paths, `userConfig`, `dependencies`, `defaultEnabled`). The loader
looks for `.evo-plugin/plugin.json`, then the compatibility manifest folder
used by another agent tool's plugins, then `plugin.json`. Default layout:
`skills/`, `commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `bin/`
(added to PATH). Components are namespaced `plugin:name`; MCP tools
`mcp__plugin_<plugin>_<server>__<tool>`. `${PLUGIN_ROOT}` (the installed
version) and `${PLUGIN_DATA}` (kept across updates) — plus that other
tool's alias variable names for the same two — and `${user_config.KEY}` are
substituted in hooks and servers. `userConfig` values go to settings (planned:
sensitive ones to the OS keychain, and to hooks as
`EVO_PLUGIN_OPTION_<KEY>`).

Marketplaces: a catalog `.evo-plugin/marketplace.json`, the compatibility
folder's `marketplace.json`, or `marketplace.json` (`name`, `owner`,
`plugins[]`). Marketplace sources: `owner/repo[#ref]` (GitHub), any git URL
`[#ref]` (`https`, `http`, `ssh`, `git@`, `git`, `file`), or a folder.
Plugin sources: a path in the marketplace (`metadata.pluginRoot` for bare
names), `github`, `url`/`git`, `git-subdir` (a `sha`/`ref` pins); planned:
`archive`, npm. Ids are `name@marketplace` (`name@local` for a folder
installed in place); installs are cached per version. Planned:
`enabledPlugins` in user and project settings.

#### Hooks format (evo's own)

```jsonc
{ "hooks": { "<Event>": [ { "matcher": "…", "hooks": [ /* handler */ ] } ] } }
```

From settings files and plugins (planned: skill and agent frontmatter).
Handlers: `command` (shell form, or exec form with `args`), `http` (POST the
event; `${VAR}` in headers), `prompt`; planned: `mcp_tool`, `agent`.
Matchers: `*` or empty, a `|`/`,` list of exact names, else a regex. JSON on
stdin (`session_id`, `cwd`, `hook_event_name`, per-event fields); env
`EVO_PROJECT_DIR` (planned: `EVO_PLUGIN_ROOT`, `EVO_PLUGIN_DATA`,
`EVO_PLUGIN_OPTION_*`). Exit 0 = ok (stdout JSON parsed; plain stdout becomes
context for prompt-submit and session-start), exit 2 = block with stderr,
other = non-blocking error. JSON output: `continue`, `stopReason`,
`systemMessage`, `suppressOutput`, `hookSpecificOutput`
(`permissionDecision` allow/deny/ask/defer, `updatedInput`,
`additionalContext`), `decision: "block"` for PostToolUse / Stop. Hooks of
an event run in parallel; command hooks time out after 600 s.

Compatibility: older desktops that do not send the new RPC commands still
get skills and hooks from the engine; connector tools arrive only from a
desktop with the pool.

### 3.4 Data and storage

Files read:

| Kind | User | Project | Plugin |
| --- | --- | --- | --- |
| Skills | `~/.evo/agent/skills`, `~/.agents/skills` | `.evo/skills`, `.agents/skills` (working folder and repo root) | `skills/` |
| Commands | `~/.evo/agent/commands` | `.evo/commands`, `.evo/prompts` (templates) | `commands/` |
| Agents | `~/.evo/agent/agents` | `.evo/agents` | `agents/` |
| Hooks | `~/.evo/agent/settings.json` | `.evo/settings.json` | `hooks/hooks.json` |
| MCP | `~/.evo/agent/mcp.json` (connectors added in the app) | `.mcp.json` (asks first) | `.mcp.json`, `mcpServers` |
| Plugins | `<agent dir>/plugins` (installed) | — (planned: `.evo/settings.json` `enabledPlugins`) | — |
| Instructions | `~/.evo/agent/AGENTS.md` | the folder's instruction file | — |

Precedence on name clashes: project over user over plugin, evo's folders
over `.agents`, a skill over a command. Project-level anything follows the
existing folder trust (`trust.rs`).

Stores:

- `~/.evo/agent/mcp.json` — connectors, `projectServers[<root>][<name>]`
  (approval and tool permissions), `pluginServers` (plugin connector
  permissions).
- `mcp-auth.json` next to the connectors file — sign-in tokens per
  connector (like provider credentials in `auth.json`).
- `<agent dir>/plugins` — `marketplaces.json` + clones; installed copies in
  `cache/<marketplace>/<plugin>/<version>` (manifest version, else the
  entry's, else the commit); `data/<id>`; `installed.json` (version, path,
  on/off, settings).
- `<agent dir>/skill-usage.json` — `{name: {uses, lastUsed}}`, written
  beside and renamed.
- Engine memory: the session's hooks (loaded at start, re-read on
  `reload_resources` / `list_hooks`) and the last 100 runs.
- UI store: `chatConnectorsOff` per chat.

### 3.5 Behaviour

Skills and commands:

- `/name args` expands a known skill or command (a bare name finds a unique
  `ns:name`; plugin skills `plugin:name` too), else a prompt template;
  `/skill:name` still works. A skill with shell lines is expanded by the
  engine in the prompt path; other skills are still expanded by the harness.
- Shell lines run when the skill loads — Git Bash or PowerShell on Windows,
  `sh` elsewhere, in the session's folder, `${SKILL_DIR}` filled in, 120 s
  each, output cut at 20k characters. Commands come from the skill file
  before arguments are filled in.
- Listing: descriptions cut to 1536 characters; past
  `skillListingBudgetChars` the least used skills are listed by name only
  (`nameOnlyForBudget`).
- A Customize change is sent to the other idle engines as
  `reload_resources`.

Connectors:

- The shell starts the pool at launch; every server is connected once. The
  engine store adds the connectors' tools to every chat's external tools
  (`configure_external_tools`) and re-sends them on every change; the shell
  runs calls (`mcp_call`). A call to an Ask tool shows the approval prompt
  in the composer.
- A project's `.mcp.json` is found from a chat's folder up to the repository
  root when the chat's tools load (`mcp_open_project`).
- Each chat has a set of enabled connectors (default: all connected); the
  composer's `+` → Connectors switches them for that chat. Approved servers load
  as pool entries `name#root` (label `name`).
- Sign-in: the browser returns to a one-time
  `http://127.0.0.1:<port>/callback`; a URL connector with saved tokens
  connects through `AuthClient`, which refreshes them.
- Resources: `resources/list` on connect, `resources/read` on demand;
  `@server:uri` is attached as `<resource server uri>` blocks.
- Prompts: `/server:prompt <args>` calls `mcp_get_prompt` and sends the text.
- Tool search: past 40 connector tools or about 60k characters, the chat
  gets `mcp_search_tools` and `mcp_call_tool`; `mcp_call_tool` uses the same
  path as a direct call.
- Plugins: after each plugin change the shell gives the pool the enabled
  plugins' servers (`set_plugin_servers`: keys `plugin:<plugin>:<server>`).

Hooks:

- `SessionStart`: context waits for the first prompt.
- `UserPromptSubmit`: in the RPC prompt path (`rpc_prompt_hooks`); block →
  "Blocked by a hook: …"; context rides after the prompt in a
  `<hook-context>` block, hidden in the transcript by `typedPrompt`.
- `PreToolUse`: wraps `before_tool_call` in front of the extension approval
  hook.
- `PostToolUse` / `PostToolUseFailure`: `after_tool_call`; feedback and
  context appended to the result, messages in `details.hooks`.
- `Stop`: after a prompt run, in the background.
- `SessionEnd`: on shutdown, 1.5 s.
- The tool-call hooks are installed when a session starts with hooks for
  those events.
- Planned transcript display: a blocked call shows the hook's reason on the
  tool row; `systemMessage` as a warning line; hook errors as a muted event
  line; `additionalContext` never shown (FR-55).

Plugins:

- Enabled plugins add their components on `reload_resources`;
  `list_customizations` names the plugin of each skill and subagent; plugin
  hooks have source `plugin:<name>`; `bin/` goes first on PATH for the shell
  tools.
- Update fetches the marketplace again and reinstalls, keeping on/off and
  settings. Git runs without a window and never prompts.
- Engines pick up plugin changes on their next turn (no restart); a
  plugin's connectors join the pool when it is enabled.

Instructions:

- In each folder the first existing name of `CONTEXT_FILE_CANDIDATES` is the
  file read, so it is the file edited; a folder with none gets `AGENTS.md`.
  `save_instructions` re-reads the chat's resources; the desktop then
  reloads every idle chat.

### 3.6 Errors and edge cases

- Connector fails to connect: status Failed to connect, error in the detail,
  stderr in the server log; 401/403 → Needs sign-in.
- Hook config problems are reported (Customize → Hooks) instead of failing;
  a missing command is an error, not a block.
- `prompt` and `agent` hook handlers are reported as skipped.
- A `Stop` hook cannot continue the run yet.
- Hooks added for tool-call events apply to chats started afterwards.
- Tool results over 100k characters are cut.
- Connections close on exit; `SessionEnd` hooks get 1.5 s.

### 3.7 Security and trust

- Connector results, plugin content and skill files are untrusted data.
- Project skills, commands, agents, hooks and instructions follow folder
  trust; project hooks from an untrusted folder stay off until it is
  trusted.
- Project `.mcp.json` servers are pending until approved, per project, and
  offered only to chats in that project; the person's own connector of the
  same name wins.
- Connector tools: Allow / Ask / Block; read-only-annotated tools default to
  Allow, others to Ask; tool search keeps the same checks.
- Hooks run in the engine process with the person's permissions.
- Skill shell lines come from the skill file only, never from arguments;
  they can be switched off (`disableSkillShellExecution`). They do not yet
  pass the sandbox policy (FR-45, planned).
- Plugin paths must stay inside the plugin.
- Sign-in tokens are kept in `mcp-auth.json` (planned: the OS keychain,
  FR-50); plugin option values are saved with the other settings (planned:
  sensitive ones in the keychain, FR-57).

### 3.8 Configuration

| Key | Type | Default | Where | Applies |
| --- | --- | --- | --- | --- |
| `skillOverrides` | map name → `off` \| `user-invocable-only` \| `name-only` | empty | `~/.evo/agent/settings.json` | after reload; Customize → Skills |
| `skillListingBudgetChars` | number | 8000 | `~/.evo/agent/settings.json` | live; Skill settings card |
| `disableSkillShellExecution` | boolean | false | `~/.evo/agent/settings.json` | live; Skill settings card |
| `skillDirs` | list of folders | empty | `~/.evo/agent/settings.json` | after reload |
| `hooks` | hook config | empty | user and trusted project `.evo/settings.json` | sessions started afterwards for tool-call events; others on reload |
| `disableAllHooks` | boolean | false | settings | live; Customize → Hooks switch |
| `mcpServers`, `disabled`, `toolPermissions` | connector config | — | `~/.evo/agent/mcp.json` | live; Customize → Connectors |
| `chatConnectorsOff` | per-chat list | empty | desktop UI store | live; composer `+` menu |

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| MCP client in each engine | The app runs one engine per chat: N copies of every stdio server, N sign-ins and no single status to show. |

## 5. As-built notes

- **Planned layout vs built.** The design planned:

  ```text
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

  Built: there is no `evo-customize`; plugin manifests, marketplaces and the
  store are in `evo-plugins` (store in `<agent dir>/plugins`), and hook
  config parsing is in `evo-hooks/src/config.rs`.
- **Connector config merge.** Designed as plugin < user < project; built:
  the person's own connector wins over a project server of the same name
  (spec 6.2: kept).
- **Sign-in tokens** were designed for the OS keychain (`keyring`); built in
  `mcp-auth.json` (spec 6.2: to move, FR-50). Sign-in has not been tried against a
  real provider yet.
- **Result cut**: designed at 25k tokens with a note; built at 100k
  characters (spec 6.2: kept).
- **Pool lifecycle**: designed to start on first use or at launch per
  connector, restart with backoff, and show logs per server in Settings →
  Logs; built: all start at launch, logs show in the connector detail
  (FR-49 planned).
- **Hooks**: `prompt` was designed as a one-shot model call returning
  `{ok, reason}`; built handlers are `command` and `http`, `prompt` and
  `agent` are reported as skipped. `Stop` runs in the background and cannot
  continue the run. SubagentStart / SubagentStop, PreCompact / PostCompact
  and Notification are not wired (FR-51, FR-52). Customize → Hooks was
  designed read-only with "Turn off all hooks"; built with an on/off switch
  for all hooks, problems, recent runs and buttons to open the settings
  files.
- **Phase 1** first shipped Customize with Connectors, Plugins and Hooks
  marked Soon. The design's "to come" items — Connectors (status, Connect /
  Reconnect, tools with permission selects, an Add connector dialog, Pending
  approval project servers), Plugins (your plugins / Discover from added
  marketplaces / Marketplaces; a plugin's parts — skills, commands, agents,
  connectors, hooks; disable, remove, update) and Hooks — were built in
  phases 2–4.
- **MCP handshake order**: designed to try the 2025-11-25 `initialize`
  first and fall back to the stateless 2026-07-28 form; built with
  `ClientLifecycleMode::Auto`, which uses the stateless revision with the
  `initialize` handshake as fallback.
- **Skills, still to do from the design**: the rest of the frontmatter
  (`allowed-tools`, `model` / `effort` per turn, `context: fork`), moving the
  catalog into the `skill` tool's description within a budget (1% of the
  context window; the built listing budget applies to the system-prompt
  listing instead), shell lines through the sandbox policy (2-minute limit,
  off for untrusted folders; built with a 120 s limit, no sandbox), and file
  watching (FR-41, FR-43–FR-46).
- **Plugins, not yet**: npm and archive sources, `userConfig` secrets in the
  OS keychain, project-level plugin switches, `.zip` upload, marketplaces by
  URL to a `marketplace.json` (FR-56–FR-59). Designed install location
  `~/.evo/plugins/{cache,data,marketplaces}` (marketplaces cloned into
  `marketplaces/<name>`, "Check for updates" pulls); built under
  `<agent dir>/plugins` with "fetch again".
- **Desktop, not yet**: `@agent-name` mentions, Plugins and Manage
  connectors in the `+` menu, connector icons on tool rows (FR-60).
- **Not yet**: `.mcpb` bundles (FR-42), elicitation dialog (FR-48).
