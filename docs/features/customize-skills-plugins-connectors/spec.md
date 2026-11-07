# Customize: skills, connectors (MCP), plugins and hooks — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | engine, crates `evo-mcp` `evo-plugins` `evo-hooks`, desktop |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Approval modes](../approval-modes/spec.md), [Subagents and nested sessions](../subagents-and-nested-sessions/spec.md), [Code intelligence](../code-intelligence/spec.md) |

## 1. Summary

One place, **Customize**, for everything that shapes what the agent can do —
skills, agent types, connectors, plugins, hooks and standing instructions —
and a chat input that reaches them: `/` opens commands and skills, `@`
mentions files and connector resources, `+` holds files, commands and
per-chat connector switches. Skills follow the open Agent Skills
specification and connectors the Model Context Protocol (MCP); plugins and
hooks are evo's own formats. Everything applies to open chats without
restarting the app.

## 2. Scope

### 2.1 Goals

- Skills and commands the person and the model can run, from evo's folders,
  the cross-client Agent Skills folders and plugins.
- Connectors (MCP servers), local or remote, shared by every chat, with
  sign-in, per-tool permissions, prompts and resources, and project servers
  that ask first.
- Hooks: the person's commands and web requests that run on agent events
  and can block, allow or add context.
- Plugins and marketplaces that bundle skills, commands, agents, hooks and
  connectors.
- Editing the standing instructions the agent reads in every chat.
- One **Customize** page for all of the above.

### 2.2 Non-goals

- Account sync, a hosted directory, managed or enterprise policy files.
- Language servers, output styles, monitors and themes inside plugins: a
  plugin that has them still loads; those parts are listed as unsupported.
  (Language servers are [Code intelligence](../code-intelligence/spec.md).)

## 3. User scenarios

### US-1 Run a skill from the chat (priority P1)

A person wants to run a skill or command by typing `/` so that a repeated
workflow is one line.

Acceptance scenarios:

1. **Given** a skill in the project, **when** the person types `/` in the
   composer, **then** the menu lists built-ins, skills, commands and
   templates, and Enter runs the chosen one (or inserts it when it takes
   arguments).
2. **Given** a skill the model may use, **when** a request fits it,
   **then** the model runs it with the `skill` tool and the transcript shows
   "Skill · name".

### US-2 Add a connector and use its tools (priority P1)

A person wants to connect an MCP server once so that every chat can use its
tools, with control over which tools need approval.

Acceptance scenarios:

1. **Given** the person adds a connector in **Customize → Connectors**,
   **when** it connects, **then** its tools reach every chat without a
   restart.
2. **Given** a tool set to Ask, **when** the agent calls it, **then** the
   composer shows Allow once / Always allow / Deny.
3. **Given** a remote server that answers 401/403, **when** the person
   presses Sign in, **then** the browser opens, and after sign-in the
   connector connects.

### US-3 A project brings its own servers (priority P2)

A person opens a project with a `.mcp.json` and wants its servers only
after approving them.

Acceptance scenarios:

1. **Given** a project file with servers, **when** a chat opens there,
   **then** the servers show as pending in **Customize → Connectors** and
   are not connected.
2. **Given** the person approves one, **then** it connects and is offered
   only to chats in that project.

### US-4 A hook guards the agent (priority P2)

A person wants a command to run on agent events so that they can block a
prompt or a tool call, or add context.

Acceptance scenarios:

1. **Given** a `UserPromptSubmit` hook that exits 2, **when** the person
   sends a prompt, **then** the prompt fails with "Blocked by a hook: …"
   before any model call.
2. **Given** a `PreToolUse` hook that asks, **when** the tool is called,
   **then** the approval prompt shows in the composer.

### US-5 Install a plugin from a marketplace (priority P2)

A person wants to add a marketplace and install a plugin so that its
skills, commands, agents, hooks and connectors arrive together.

Acceptance scenarios:

1. **Given** a marketplace added by `owner/repo`, git URL or folder, **when**
   the person installs a plugin, **then** its skills, commands, subagents,
   hooks and connectors appear in every ready chat.
2. **Given** an installed plugin, **when** the person updates it, **then**
   its on/off state and settings are kept.

### US-6 Edit standing instructions (priority P3)

A person wants to edit the instructions the agent reads in every chat, for
themselves or for one project.

Acceptance scenarios:

1. **Given** a trusted project folder, **when** the person saves its
   instructions, **then** idle chats use them from their next message.

### Edge cases

- Two items with the same name: project wins over user over plugin; evo's
  folders over the cross-client folder; a skill over a command. A project
  connector loses to the person's own connector of the same name.
- An untrusted project folder: its skills, hooks and instructions are not
  read; its `.mcp.json` servers stay pending.
- A broken hook config: the problem is reported; other hooks still run.
- A connector returns a huge result: it is cut.
- A chat has too many connector tools: they move behind a search tool.
- A hook added for a tool-call event applies to chats started afterwards.

## 4. Requirements

### 4.1 Functional

Skills and commands:

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Skills load from evo's project and user folders, the cross-client Agent Skills folders (project: the working folder and the repository root; user: the home folder) and enabled plugins. | Given a skill in each place, then each is listed. |
| FR-2 | Command files are single-file skills named after their path (`a/b.md` → `a:b`); a skill of the same name wins; the description falls back to the first line. | Given `a/b.md` with no description, then skill `a:b` is listed with the first line. |
| FR-3 | On name clashes, project wins over user over plugin, evo's folders over the cross-client folder, and a skill over a command; project-level items follow folder trust. | Given two skills of one name, then the project's is used. |
| FR-4 | Skills follow the Agent Skills specification; evo also reads `when_to_use`, `argument-hint`, `user-invocable` (default true), `disable-model-invocation` (default false) and `model`. Only name and description are always in context; the body loads when invoked and the skill's files on demand. | Given a skill with `disable-model-invocation`, then the model's listing leaves it out. |
| FR-5 | A per-skill override — off, user-invocable only, name only — is applied after loading and set from Customize (the chat then reloads). | Given a skill set to name only, then the model's listing shows its name without the description. |
| FR-6 | The model has a `skill` tool `{name, arguments?}`; the system prompt keeps the list of available skills. | Given a listed skill, when the model calls `skill`, then the body is loaded with the arguments. |
| FR-7 | `/name args` expands a known skill or command (a bare name finds a unique `ns:name`), else a prompt template; `/skill:name` still works. | Given `/b` and only `a:b`, then `a:b` runs. |
| FR-8 | Skill bodies substitute `$ARGUMENTS`, `$ARGUMENTS[N]` (0-based), `${SKILL_DIR}` and `\$`; `$N` only in command files (skill bodies often hold shell snippets). | Given each form, then it is replaced as stated. |
| FR-9 | Agent files may name tools in PascalCase (`Read` → `read`, `Grep`/`Glob` → `bash`, …); short model family aliases mean the chat's model. | Given an agent file with PascalCase tools, then the subagent gets evo's tools. |
| FR-10 | The `/` menu lists built-ins (`/clear`, `/compact`, `/fork`, `/customize`), then skills, commands, templates and connector prompts; word-prefix matching ignores `:_-`; ↑↓ move, Tab completes, Enter runs or inserts when the command takes arguments, Esc closes. | Manual check in the running app. |
| FR-11 | The composer shows a typed `/name` as an accent token with its argument hint; the user's bubble shows the `/name` token; a saved skill prompt is shown as typed; a skill run shows as a "Skill · name" row. | Manual check in the running app. |
| FR-12 | **Sidebar → Customize** has sections for Skills (switch, "Who can use it"), Agents, Connectors, Plugins, Hooks, Code intelligence and Instructions, with a scope filter (All / Personal / Project), a search box, rows grouped by source and a detail pane. A change reloads the other idle chats. | Manual check in the running app. |
| FR-13 | Each skill run, by the tool or `/name`, is counted (uses and last use) and shown in Customize, in the list and the detail. | Given two runs, then the skill shows 2 uses and the last time. |
| FR-14 | Skill descriptions in the model's listing are cut to 1536 characters; past the listing budget (default 8000 characters) the least used skills are listed by name only until it fits, and Customize marks them "name only, to fit the listing budget". They still run by `/name` and the `skill` tool. | Given more skills than fit, then the least used lose their descriptions first. |
| FR-15 | Shell lines in a skill — `` !`command` `` inline or a fenced block opened with ```` ```! ```` — run when the skill loads and are replaced by their output, in the session's folder with `${SKILL_DIR}` filled in, 120 s each, output cut at 20k characters. They run for the `skill` tool and for `/name`. | Given a skill with a shell line, then the model sees its output. |
| FR-16 | A Skill settings card under the skill list sets the listing budget (0 restores the default) and whether shell lines run. | Given shell lines off, then a skill's shell lines do not run. |

Connectors (MCP):

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-17 | The person's connectors are kept in one file in the MCP `mcpServers` form: a command with args, env and folder, or a type with URL and headers; `${VAR}` and `${VAR:-default}` expand; evo adds `disabled` and per-tool permissions; unknown keys are kept. | Given a file with both kinds and unknown keys, then it round-trips. |
| FR-18 | Each connector has one connection for the whole app, shared by every chat, over stdio, streamable HTTP or SSE, speaking both the stateless 2026-07-28 revision and the `initialize` handshake. Status: Connected, Needs sign-in, Failed to connect, Pending approval, Off. Each keeps a 200-line server log. | Given two chats, then one server process serves both. |
| FR-19 | Connector tools reach every chat as `mcp__<server>__<tool>` (cut to 64 characters) and are re-sent on every change. | Given a new connector, then open chats get its tools. |
| FR-20 | Each tool has a permission Allow / Ask / Block; tools annotated read-only default to Allow, others to Ask. A call to an Ask tool shows Allow once / Always allow / Deny in the composer; Always allow saves Allow. | Given an Ask tool, when called, then the approval shows. |
| FR-21 | Tool results over 100k characters are cut. | Given a huge result, then the chat gets the cut text. |
| FR-22 | **Customize → Connectors** lists connectors with status and a switch; the detail shows the error, properties, server instructions, tools with Allow / Ask / Block, prompts, resources and the server log; an Add/Edit dialog has Command, URL and JSON modes. | Manual check in the running app. |
| FR-23 | Connector prompts appear in the `/` menu as `/server:prompt <args>`; the server fills the prompt in and the text is sent. Tool rows read "Called server · tool". | Manual check in the running app. |
| FR-24 | Remote connectors sign in with OAuth 2.1 (metadata discovery, registered, metadata-document or dynamic client registration, PKCE, code exchange, refresh). The browser returns to a one-time loopback address; tokens are kept per connector. Customize shows Sign in (primary when the server answered 401/403) and Sign out. | Manual sign-in against a real provider. |
| FR-25 | A project's `.mcp.json` (nearest from the chat's folder up to the repository root) lists servers that stay pending until the person approves each; decisions and tool permissions are remembered per project; approved servers are offered only to chats in that project; the person's own connector of the same name wins. Customize shows them with Approve / Deny and a switch. | Given a project file, then its servers stay pending until approved. |
| FR-26 | Connector resources are listed on connect and shown in Customize; `@server:uri` in a message is read and attached when the message is sent. | Given `@server:uri`, then the resource text rides with the message. |
| FR-27 | The composer `+` menu has Attach files, Commands and skills, Connectors (a switch per connector for this chat; the chat's tools are re-sent) and Resources (inserts `@server:uri`). | Manual check in the running app. |
| FR-28 | Past 40 connector tools in a chat, or about 60k characters of names, descriptions and schemas, the chat gets `mcp_search_tools {query, limit?}` and `mcp_call_tool {name, arguments}` instead of all of them; Allow / Ask / Block still apply; the transcript labels a call by the tool it ran. | Given 41 tools, then the chat has the two search tools. |

Hooks:

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-29 | Hooks come from user settings, a trusted project's settings and enabled plugins; comments are allowed; `disableAllHooks` turns all off; problems are reported instead of failing; matchers are `*` or empty, a `|`/`,` list of exact names, else a regex; tool names also match their PascalCase form and `Bash` covers `bash` and `powershell`; duplicate handlers run once. | Given a bad entry, then it is reported and the others load. |
| FR-30 | `command` and `http` handlers run in parallel with the event as JSON; exit 0 / 2 / other and the JSON output combine into one outcome (deny over ask over allow); timeouts 600 s for commands, 60 s for HTTP, 30 s for prompt hooks. `prompt` and `agent` handlers are reported as skipped. | Given exit 2, then the outcome blocks with stderr. |
| FR-31 | Events: `SessionStart` (its context waits for the first prompt); `UserPromptSubmit` (block → the prompt fails with "Blocked by a hook: …"; context rides after the prompt and is hidden in the transcript); `PreToolUse` (deny → the call fails with the reason, ask → the approval prompt, allow, `updatedInput`); `PostToolUse` / `PostToolUseFailure` (feedback and context appended to the result); `Stop` after a prompt run (in the background); `SessionEnd` on shutdown (1.5 s). | Given a blocking `UserPromptSubmit` hook, then no model call happens. |
| FR-32 | The last 100 hook runs are kept. **Customize → Hooks** shows on/off for all hooks, problems, hooks by event with matcher, what runs and whose, buttons to open the settings files, recent runs (result, reason, duration) and an example. | Manual check in the running app. |

Plugins and marketplaces:

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-33 | A plugin is a folder with an optional manifest and a default layout (skills, commands, agents, hooks, connectors, `bin/`); listed skills, hooks and connectors add to the defaults, listed commands and agents replace them; paths stay inside the plugin; a root skill file makes the plugin one skill; `${PLUGIN_ROOT}`, `${PLUGIN_DATA}` and `${user_config.KEY}` are filled in in hooks and connectors. Plugins written for another agent tool's manifest folder and variable names also load. | Given a folder without a manifest, then its default layout loads. |
| FR-34 | A marketplace is added by `owner/repo[#ref]` (GitHub), any git URL `[#ref]` or a folder; plugin sources are a path in the marketplace, `github`, `url`/`git` or `git-subdir` (a `sha`/`ref` pins). | Given each source form, then it parses and fetches. |
| FR-35 | Plugins install (cached per version), install from a folder in place, update (fetch the marketplace again and reinstall, keeping on/off and settings), uninstall, switch on/off and take settings. Git never opens a window or prompts. | Given install, update and uninstall from a folder marketplace, then the store matches. |
| FR-36 | An enabled plugin adds skills and commands named `plugin:name` (a unique bare `/name` finds them), subagents `plugin:name`, its hooks, its `bin/` first on PATH for the shell tools, and its connectors (tools `mcp__plugin_<plugin>_<server>__<tool>`); every ready chat re-reads its resources after a change. Customize names the plugin of each skill and subagent. | Given an installed plugin, then its skill, command, subagent and hook appear in a chat. |
| FR-37 | **Customize → Plugins** has Installed (switch, contents, a settings form from the plugin's options, update, uninstall, show in folder), Discover (the marketplaces' plugins with Install / Reinstall), Marketplaces (add, fetch again, remove) and Add from folder. Plugin skills and subagents are grouped as "Plugin · name"; plugin hooks are labelled. | Manual check in the running app. |
| FR-38 | Plugin parts evo does not support (language servers, output styles, monitors, themes) are listed as unsupported; the rest of the plugin loads. | Given such a plugin, then it loads and lists the unsupported parts. |

Instructions:

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-39 | **Customize → Instructions** edits the standing instructions in every system prompt: **Personal** (for every chat), **This project** (read once the folder is trusted) and **Also read** (parent folders, read-only); the editor has Edit / Preview, Save (`Ctrl+S`), Revert, unsaved marks and a note when the folder is not trusted. | Manual check in the running app. |
| FR-40 | The file edited is the file read: the first existing instruction file name in the folder, else `AGENTS.md`; saving empty text removes the file; idle chats use the change from their next message. | Given empty text, when saved, then the file is gone. |

Planned (not built yet):

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-41 | Planned: a skill with `context: fork` will run in a child agent. | Given such a skill, then it runs as a subagent. |
| FR-42 | Planned: `.mcpb` connector bundles will install. | Given a bundle, then its connector is added. |
| FR-43 | Planned: a skill's `allowed-tools` will pre-approve those tools for that turn, and `model` / `effort` will apply to that turn. | Given `allowed-tools`, then those calls need no approval in that turn. |
| FR-44 | Planned: the skill catalog will move into the `skill` tool's description within a budget of 1% of the context window, least used first. | Given a small context window, then the catalog fits the budget. |
| FR-45 | Planned: skill shell lines will run through the sandbox policy and be off for untrusted folders. | Given an untrusted folder, then shell lines do not run. |
| FR-46 | Planned: skill folders will be watched, so edits apply without a reload. | Given an edited skill, then the next run uses it. |
| FR-47 | Planned: skill bodies will substitute `${PROJECT_DIR}` and `${SESSION_ID}`. | Given each, then it is replaced. |
| FR-48 | Planned: connector elicitation will show a desktop dialog. | Given a server's elicitation, then a dialog asks the person. |
| FR-49 | Planned: connectors will start on first use or at launch per connector and restart with backoff; server logs will also show in **Settings → Logs**. | Given a crashed server, then it restarts with backoff. |
| FR-50 | Planned: connector sign-in tokens will be kept in the OS keychain and refreshed on expiry. | Given a sign-in, then the token is in the keychain. |
| FR-51 | Planned: hook handlers `prompt` (a one-shot model call returning `{ok, reason}`), `mcp_tool` and `agent`. | Given a `prompt` hook, then its answer decides the outcome. |
| FR-52 | Planned: hook events `SubagentStart` / `SubagentStop` (the `agent` tool), `PreCompact` / `PostCompact` and `Notification` (raised by the desktop); a `Stop` hook will be able to continue the run. | Given a `PreCompact` hook, then it runs before compaction. |
| FR-53 | Planned: hooks declared in skill and agent frontmatter. | Given a skill with a hook, then it runs while the skill is active. |
| FR-54 | Planned: hook environment `EVO_PLUGIN_ROOT`, `EVO_PLUGIN_DATA` and `EVO_PLUGIN_OPTION_<KEY>` for plugin hooks. | Given a plugin hook, then the variables are set. |
| FR-55 | Planned: hook results in the transcript — a blocked call shows the hook's reason on the tool row, `systemMessage` shows as a warning line, hook errors as a muted event line; `additionalContext` is never shown. | Manual check in the running app. |
| FR-56 | Planned: plugin sources `npm` and `archive`, and marketplaces added by a URL to a marketplace file. | Given an archive source, then it installs. |
| FR-57 | Planned: sensitive plugin options will be kept in the OS keychain (today they are saved with the other settings). | Given a sensitive option, then it is in the keychain. |
| FR-58 | Planned: plugins enabled per scope — user or project settings (`enabledPlugins`), chosen on install. | Given a project-scope plugin, then it is on only in that project. |
| FR-59 | Planned: install a plugin by uploading a `.zip`, with the options form shown on install. | Given a `.zip`, then the plugin installs. |
| FR-60 | Planned: `@agent-name` mentions in the composer; Plugins and Manage connectors in the `+` menu; connector tool rows show the connector's icon. | Manual check in the running app. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Formats follow open specifications where one exists (Agent Skills for skills, the Model Context Protocol for connectors); everything else is evo's own and lives in evo's folders, plus the cross-client Agent Skills folder. | Review. |
| NFR-2 | Background processes — stdio servers, hook commands, shell lines, git — open no console window, and git never prompts. | Manual on Windows: no window flashes. |
| NFR-3 | Text passed to a skill never runs as a shell command: shell lines are taken from the skill file before arguments are filled in. | Given arguments with `` !`…` ``, then nothing runs. |
| NFR-4 | Project-level customizations stay off until trusted or approved: skills, hooks and instructions follow folder trust; project connectors ask first. | Given an untrusted folder, then its hooks do not run. |
| NFR-5 | Settings, customization and connector changes apply to chats without restarting the app: idle chats reload; plugins and connectors re-send tools. | Given a change, then the next message uses it. |
| NFR-6 | The skill usage file is written beside and renamed, so engines never read half a file. | Review. |

## 5. Success criteria

- SC-1 A hook that blocks a prompt stops it before any model call.
- SC-2 An installed plugin's skill, command (with its argument hint),
  subagent and hook all appear in a chat, with no restart.
- SC-3 A connector added in the app is usable in every open chat within one
  message, without restarting.
- SC-4 A chat with more connector tools than fit the model's context still
  reaches every tool.

## 6. Clarifications

### 6.1 Open

None.

### 6.2 Resolved

- 2026-11-06 — Q: Where do hooks run, and what about untrusted folders? →
  A: In the engine process with the person's permissions; project hooks
  from an untrusted folder stay off until the folder is trusted (FR-29,
  NFR-4).
- 2026-11-06 — Q: Do hook matchers accept PascalCase tool names (`Bash`,
  `Edit`)? → A: Yes, with the same alias table agent files use (FR-29).
- 2026-11-06 — Q: Does the MCP client support the new 2026-07-28 revision?
  → A: Yes; it speaks the stateless revision with the `initialize`
  handshake as fallback, since most servers still speak 2025-11-25 (FR-18).
- 2026-11-06 — Q: Why are connectors shared by the app and not per chat? →
  A: The app runs one engine per chat; a server per engine would mean N
  copies of every stdio server, N sign-ins and no single status (FR-18).
- 2026-11-07 — Q: Connector sign-in tokens are designed for the OS keychain but
  kept in a file next to the connectors file. Move them? → A: Yes, together
  with sensitive plugin options (FR-50, FR-57); until then the file stays,
  like provider credentials.
- 2026-11-07 — Q: Config merges as plugin < user < project, but the person's own
  connector wins over a project server of the same name. Which is intended?
  → A: The person's own connector wins, so a project cannot replace a
  connector the person set up (FR-25).
- 2026-11-07 — Q: Cut long tool results at 25k tokens (design) or 100k characters
  (built)? → A: 100k characters (FR-21).

## 7. History

- 2026-11-06 — Phases 1–5 built (skills and commands; connectors; sign-in,
  project servers and resources; hooks; plugins and marketplaces; tool
  search, skill usage, the listing budget and shell lines in skills) and
  custom instructions. `.mcpb` bundles and `context: fork` not built.
- 2026-11-07 — Moved to the spec / plan / tasks format.
- 2026-11-07 — Open clarifications answered by the owner (accepted as proposed).
