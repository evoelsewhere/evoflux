# evo desktop

The desktop app for evo. Tauri 2 shell + React 19 / TypeScript / Tailwind v4,
components from shadcn/ui (Base UI, `base-rhea`) and its **AI Elements**
patterns. Design language: [`/DESIGN.md`](../../DESIGN.md) (Geist, achromatic,
shadow-as-border, one blue accent).

## How it runs

```
┌────────────── evo-desktop (Tauri) ───────────────┐
│ React UI ── invoke("engine_send") ──► Rust shell │──stdin──►  evo-engine --mode rpc
│          ◄── event "engine://message" ───────────│◄─stdout──  (JSONL, crates/evo-protocol)
└──────────────────────────────────────────────────┘
```

The shell owns no agent logic. It runs `evo-engine` as a child process, so a
crashing native extension cannot take the window down, and relays the JSONL
protocol. The window is transparent: the sidebar shows **Mica** (Windows 11) or
**vibrancy** (macOS), and falls back to an opaque sidebar elsewhere.

## Develop

```bash
bun install
bun run dev:app               # stage the engine sidecar, then run the app
bun run build:dev             # debug build + NSIS installer (src-tauri/target/debug/bundle)
bun run build:app             # release build, all installers
```

The app always talks to the real engine. Connect a model provider in
Settings → Providers; models come from models.dev. `EVO_ENGINE_BIN` overrides
the engine binary path and `EVO_DESKTOP_ENGINE_ARGS` passes extra engine flags.

## UI map

| Area | Built from |
| --- | --- |
| Title bar: app menu (☰ on Windows/Linux, the native menu bar on macOS — `features/shell/mac-menu.tsx`), sidebar toggle, back/forward | `dropdown-menu` submenus, `dialog` (About), Tauri menu API |
| Notifications: bell in the title bar, toasts, OS notifications — see [notifications SDD](../../docs/features/notifications/sdd.md) | `popover`, `tauri-plugin-notification` |
| Sidebar: brand, search, quick actions, chats grouped by workspace; a running chat's title shimmers | shadcn `sidebar`, `collapsible`, `kbd`, `tooltip` |
| Subagents: the engine's built-in `agent` tool (`crates/evo-engine/src/agent_tool.rs`, types from `.evo/agents/*.md`) streams the child's steps as `details.child`; `components/ai-elements/agent-run.tsx` shows them nested under the call with the report, kept worktree, tool uses, tokens and time; the child's cost counts toward the turn. Background agents (`background: true`) keep running after the turn; their steps arrive as session mesh events (`src/engine/mesh.ts`, [`docs/features/session-mesh-protocol/sdd.md`](../../docs/features/session-mesh-protocol/sdd.md)), and when one finishes while the chat is idle the store wakes it with an automated prompt (at most 5 in a row); reports and wakes show as event lines | `trace`, `markdown` |
| Nested sessions: chats get `start_session` / `message_session` / `list_sessions` as external tools (`engine-store.ts`); a proposed session is a card (`session-proposal.tsx`) unless Settings → Sandbox allows starting directly; started sessions run in the background, sit under their parent in the sidebar (up to 3, then "N more nested sessions · M unread"), and send the parent a note per finished turn | `sidebar` sub-menu |
| Worktree review (`components/ai-elements/worktree-review.tsx`, `src-tauri/src/worktrees.rs`, `crates/evo-worktrees`): a subagent's kept worktree, a worktree session (toolbar chip) or Settings → Sandbox opens the changes since the worktree was cut; Apply puts them in the workspace uncommitted and removes the worktree, Discard throws it away | `dialog`, `code-block` |
| Settings (`features/settings/settings-view.tsx`, `settings-registry.ts`, `settings-controls.tsx`): a modal over the app (Mod+, or the sidebar's gear; Esc or × closes it): the section list on the left with search (Enter opens the first match, the first Esc clears it), groups split by a rule and Documentation / Report an issue links at the bottom; the open section scrolls on the right as titled groups of rows split by hairlines, label and description on the left, the control on the right | `dialog` |
| Settings → Sandbox (`sections/sandbox-settings.tsx`): inherit host environment, load shell profile, maximum execution time, maximum inline output, denied file patterns, where managed worktrees go (inside the repository or the user data directory; `crates/evo-engine/src/worktrees.rs`, used by child agents started with `"isolation": "worktree"`). Saved under `sandbox` in the app settings; every engine starts with them as `--sandbox-config` (`crates/evo-tools/src/sandbox.rs`), idle engines restart on a change | Base UI `switch`, `input` |
| Settings → General (`src-tauri/src/system.rs`): run on startup into the tray (`tauri-plugin-autostart`, `--hidden`), the tray icon (closing the main window hides it; without the icon closing the last window quits), keep the computer awake (sleep only, not the display), the default "Open in" app for the toolbar button (`openInDefault` in `ui-store.ts`; "Last used" follows the app picked from its menu last). One running copy (`tauri-plugin-single-instance`): a second launch shows the first | Base UI `switch` |
| Settings → Data & logs (`sections/logs-settings.tsx`, `src-tauri/src/db.rs`): where `evo.db` lives, its size and schema version, the transcripts folder (`~/.evo/agent/transcripts`, one file per chat) with its size and file count, and the run log (clear, export). Chat search in the command palette (`features/sessions/command-palette.tsx`) matches titles, previews and transcript text (`chats_search`, refreshed from changed transcript files) and shows only the latest query's answer. See [`docs/features/app-database/sdd.md`](../../docs/features/app-database/sdd.md) | — |
| Usage (sidebar → Usage, `features/usage/` — `usage-page.tsx`, `usage-charts.tsx`, `analysis.ts`; `stores/usage-store.ts`, `src-tauri/src/db.rs`): what the models cost and how well they used it, from the history each chat's engine records per response (`crates/evo-engine/src/usage_log.rs`, `usage_events` in `evo.db`). Today / 7 / 30 / 90 days / All time, grouped Auto / hourly / daily / weekly. Totals: spend, per day and monthly projection, per response, tokens, cache share and savings, speed, failures. Over time: spend, tokens or responses stacked by model (top four coloured, `--viz-*` in `index.css`, the rest as Other) with hover values. What stands out: observations from the numbers. Model efficiency: cost per response, per 1k output tokens and output speed as bars, and a table with prompt/output size, cache hit, paid per 1M, today's models.dev price, latency and failures (click a model to filter). Price check: the same tokens on other models at models.dev prices. Then cost by part and source, by chat (opens it), the latest 50 responses, Clear history. Refreshes every 15 s. See [`docs/features/usage-and-cost/sdd.md`](../../docs/features/usage-and-cost/sdd.md) | — |
| Customize (sidebar → Customize, `features/customize/customize-page.tsx`, `stores/customize-store.ts`): section tabs on top (Instructions, Skills, Subagents, Connectors, Plugins, Hooks), search and Personal / Project filter. Skills — folders in the Agent Skills format (`SKILL.md` + `references/`, `assets/`, `scripts/`; `.evo/skills`, `.agents/skills`, `~/.evo/agent/skills`, `~/.agents/skills`) and single-file commands (`.evo/commands`): a list grouped by source with a switch each, and a detail with the properties (how to run it, allowed tools, compatibility, license, author, version), "who can use it" (on, only `/name`, name only, off: `skillOverrides`) and the skill folder as a file tree with a viewer (markdown rendered, links between the skill's files open them, other text as code, images). Instructions (`features/customize/instructions-section.tsx`, RPC `list_instructions` / `save_instructions`) — personal instructions for every chat (`~/.evo/agent/AGENTS.md`) and the project's own file, edited with Edit / Preview and Save; parent folders' files shown read-only; idle chats reload on save. Each skill shows how often it ran and when last; a Skill settings card under the list sets the model's listing budget (`skillListingBudgetChars`; the least used skills are listed by name only past it) and whether `` !`command` `` lines in skills run. Subagents — `.evo/agents` and built-ins. Read with RPC `list_customizations` (`crates/evo-engine/src/customize.rs`, which also lists a skill's files); a change reloads every idle engine | `switch`, `dropdown-menu`, `markdown` |
| Connectors (Customize → Connectors, `features/customize/connectors-section.tsx`, `stores/connectors-store.ts`, `lib/mcp.ts`, `src-tauri/src/mcp.rs`, `crates/evo-mcp`): MCP servers in `~/.evo/agent/mcp.json`, one shared pool in the shell (stdio commands, streamable HTTP, SSE). Each connector shows its status, tools and prompts and a log; each tool is Allow / Ask / Block (read-only tools default to Allow). Every chat gets the connected tools as `mcp__<server>__<tool>`; "Ask" shows an approval in the composer. Add by command, URL or a pasted `mcpServers` JSON. URL servers sign in with OAuth in the browser (tokens in `~/.evo/agent/mcp-auth.json`). A project's `.mcp.json` servers wait for Approve and serve only chats in that project. The composer's + menu switches connectors per chat and inserts `@server:uri` resources, read and attached on send | `dialog`, `switch`, `collapsible` |
| Plugins (Customize → Plugins, `features/customize/plugins-section.tsx`, `lib/plugins.ts`, `src-tauri/src/plugins.rs`, `crates/evo-plugins`): bundles of skills, commands, subagents, hooks and connectors in `<agent dir>/plugins`. Installed (switch, what it adds, settings, update, uninstall), Discover (plugins from your marketplaces), Marketplaces (add a GitHub `owner/repo`, any git URL with optional `#ref`, or a folder). Their parts appear as `plugin:name`; their connectors join the shared MCP pool | `switch`, `input` |
| Hooks (Customize → Hooks, `features/customize/hooks-section.tsx`; `crates/evo-hooks`, `crates/evo-engine/src/hooks.rs`): commands or web requests from `hooks` in your settings or a trusted project's `.evo/settings.json`, run on SessionStart, UserPromptSubmit, PreToolUse, PostToolUse(Failure), Stop and SessionEnd. Exit 2 blocks (a prompt fails with the reason, a tool call returns it as its error); JSON can ask you first (the approval prompt), allow, rewrite a tool's input, or add context. The page lists them by event, switches them all off, and shows recent runs | `switch` |
| Composer `/` menu (`features/chat/command-menu.tsx`): built-ins `/clear` `/compact` `/fork` `/customize`, then skills, commands and templates; matches the start of a word ignoring `:_-`; ↑↓, Tab completes, Enter runs (or inserts a command that takes arguments), Esc. A leading known command shows as an accent token with its `argument-hint` (a layer behind the textarea, `prompt-input.tsx`). The engine expands `/name args`; the model loads skills itself with the `skill` tool ("Skill · name" row) | `prompt-input` |
| Chat menu (right-click or "…", `features/shell/chat-menu.tsx`): Open in › New window / the apps from Open in, Pin, Mark as unread, Rename, Fork, Move to › workspace, Archive, Delete, each with a one-key shortcut. A chat in its own window is owned by that window (`src-tauri/src/window.rs`); closing it stops the chat's engine | Base UI `context-menu`, `dropdown-menu` submenus |
| Chat card toolbar: workspace switcher; Open in, context usage, side panel in one group. Open in lists the file manager, editors and terminals the shell finds, with their OS icons (`src-tauri/src/apps.rs`), and reopens the last one in one click | `dropdown-menu`, shadcn AI Elements **Context** (`hover-card` + `progress`) with the engine's per-category breakdown (`get_context_breakdown`) and Compact |
| Thread | shadcn AI Elements **Chat** (`message-scroller`), **Message** (`message`, `bubble`) |
| Agent steps | shadcn AI Elements **Reasoning** and **Tool** on `trace` + `code-block`, mapped like DeepSeek Harness: parts in stream order (`messageId:contentIndex`), tools stream a *preparing* row from partial args, per-tool bodies (terminal, diff with +N −M, file), consecutive steps grouped under a live/summary title, the finished turn folded behind "Completed in Ns", a ticking "Working for Ns", deltas applied once per animation frame |
| Permission prompts | shadcn AI Elements **Confirmation** (`item` + `button`), taking the composer's place until answered (Enter allows, Esc rejects) |
| Reply text | `components/markdown.tsx`: Streamdown with fenced code routed to `code-block` (shadcn Code Block › Markdown) |
| Composer | AI Elements **Prompt Input** (`input-group`, `attachment`) + **Model Selector** |
| Code intelligence (Customize → Code intelligence, `features/customize/languages-section.tsx`; `crates/evo-lsp`, `crates/evo-engine/src/lsp_tool.rs`): language servers for 21 languages behind the agent's `lsp` tool (diagnostics, definition, references, hover, symbols). The project's languages come first with Install / Install all (npm, go, rustup, dotnet, gem or a GitHub release into `~/.evo/agent/lsp`); servers on PATH, in the Rust toolchain or bundled with VS Code-style editors are used as they are. A chat in a project that needs one suggests it once. See [`docs/features/code-intelligence/sdd.md`](../../docs/features/code-intelligence/sdd.md) | `switch` |
| Sent files and notifications (`features/chat/user-tools.ts`, `components/ai-elements/sent-files.tsx`): `send_file` puts deliverables in the chat as cards (Open, View in Files, Show in folder) that stay visible when a turn folds; `notify` sends a notification that opens the chat | — |
| Questions and tasks (`features/chat/questions-panel.tsx`, `features/chat/todo-bar.tsx`; `crates/evo-engine/src/interaction.rs`): `ask_user` puts 1–4 questions with options (one or several, or your own words) in the chat input's place, one per step (chips to jump, Back / Next; a single-choice pick moves on) — digits pick, `Enter` goes next or sends on the last step, `Ctrl+Enter` sends once all are answered, Skip lets the agent decide; `update_todos` keeps a task list pinned above the input with progress and the task in progress. See [`docs/features/agent-tools/sdd.md`](../../docs/features/agent-tools/sdd.md) | — |
| Web tools (`crates/evo-web`, `crates/evo-engine/src/web_tools.rs`): every chat gets `web_search` (no key: DuckDuckGo's HTML results, then Exa's hosted search, then Wikipedia; each paced and paused when limited) and `web_fetch` (a public page as Markdown, 40k characters per call; public addresses only, checked on every redirect). The transcript shows the results as links and the page text. `webTools: false` in settings turns them off. See [`docs/features/web-search-and-fetch/sdd.md`](../../docs/features/web-search-and-fetch/sdd.md) | — |
| Memory (side panel → Memory, `features/memory/memory-panel.tsx`; `crates/evo-engine/src/memory.rs`): what the agent keeps across chats — personal memories in `~/.evo/agent/memory`, a project's in `~/.evo/agent/projects/<folder>/memory` (outside the repo). The agent saves with its `memory` tool; every chat's system prompt carries the index. The panel searches, filters by type (about you, how to work, project, reference), reads, edits, forgets, adds, and switches memory off. See [`docs/features/memory-and-scheduler/sdd.md`](../../docs/features/memory-and-scheduler/sdd.md) | `switch`, `tooltip` |
| Scheduler (sidebar → Scheduler, `features/scheduler/scheduler-page.tsx`, `stores/scheduler-store.ts`, `lib/schedule.ts`): prompts that run as new chats in a folder — manual, once, hourly, daily, weekdays, weekly or cron. Tasks on the left, the chosen one on the right with its schedule editor (next run shown), Run now, on/off, delete and past runs that open their chats. The main window starts due tasks; one missed while evo was closed runs once at launch. Chats get `create/list/update/delete_scheduled_task`, each change approved in the composer | `switch` |
| Side panel (`features/panels/right-panel.tsx`, `app/app.tsx`): the tool between the chat and a tool rail on the window's right edge, which always shows — every tool as an icon (the visible one in the accent colour, a dot on tools open in the background), clicking the visible one collapses the panel to the rail, right-click or middle-click closes an open tool, collapse / expand at the bottom (also the header's side panel button). Each tool's own tabs (shells, pages, files) sit in its top row. Plugins live in Customize, not here | `resizable`, `tooltip` + `kbd`, `context-menu` |
| Terminal (Ctrl+`, Ctrl+Shift+` for another): the user's shells in the chat's folder, one tab each, picked from the shells found (`src-tauri/src/terminal.rs`: ConPTY / Unix pty via `portable-pty`). xterm.js with the app theme and code font, copy/paste (Ctrl+C with a selection, Ctrl+Shift+C/V, Ctrl+V on Windows), find (Ctrl+Shift+F), links on Ctrl+click, right-click menu. Shells keep running while another tool shows and survive a window reload (output re-attached from a backlog); `exit` closes the tab; closing the Terminal tool ends them | `@xterm/xterm` + fit, search, web-links, unicode11 |
| Side chat (Ctrl+;): questions about the chat while it runs — the engine's `side_question` RPC (`crates/evo-engine/src/side_questions.rs`): reads the conversation so far, no tools, nothing added to the chat, follow-ups queue, Stop and New; in memory only | `markdown` |
| Files (Ctrl+F): open files on the left (tabs in the toolbar, CodeMirror 6 — edit in place with auto save or Ctrl+S, markdown preview, images, open at a line from file paths in tool rows or the agent's `show_file`), the folder tree on the right (resizable, hideable; the open file is revealed and selected). One box filters the tree by file name (fuzzy, honours .gitignore) or, starting with `?`, searches inside the files (`fs_grep`), results grouped by file and opened at the line. Below 560px the tree and the editor take turns. Selection follows the Settings accent (`brand`). Git ([SDD](../../docs/features/files-git/sdd.md)): changed files end with M / A / D, folders holding changes get a dot, ignored paths are dimmed, and the gutter marks lines changed against HEAD (click a marker for the committed lines). Changes on disk reload by themselves; unsaved edits get Override / Discard. Right-click a path: Attach as context, Open in, Show in Explorer, Copy path (`src-tauri/src/files.rs`). Word, PowerPoint and Excel files open in the Office viewer (`features/files/office/office-viewer.tsx`, [SDD](../../docs/features/office-v3-parity/sdd.md)): the engine's native render (RPC `office_preview`) in a script-free iframe, or exact LibreOffice pages (pdf.js, `office/exact-pages.ts`) once the runtime is installed from the viewer banner (`components/office-install.tsx`, `stores/office-store.ts`; no settings page). Zoom and fit, Ctrl+F search, thumbnails, PPTX Normal / Sorter / Reading views and speaker notes, XLSX name box, formula bar, sheet tabs and Print layout. A deck or workbook the agent builds live shows its finished slides or sheets with placeholders for the rest and follows the build; a new Office file written during a turn opens by itself (Settings → General → Open generated documents automatically). *Select an area to edit* (PPTX) and *Select cells to edit* (XLSX) send selected shapes, areas or cells with an instruction (`office/document-annotator.tsx`, `stores/annotations-store.ts`, composer chip "Annotations: N"; sent as `/skill:office-annotation-edit`); Undo, Redo and History step through the file's saved versions (`office/document-version-controls.tsx`, RPC `document_versions_*`). PDF, legacy and OpenDocument files open as pdf.js pages (`features/files/document-viewer.tsx`) | `@codemirror/*`, `context-menu` |
| Browser (Ctrl+T): tabs of real pages — child webviews laid over the panel (`src-tauri/src/browser.rs`, Tauri `unstable`), hidden while a menu or dialog covers them; address bar takes URLs, hosts, local files or a search | native webview |
| Agent tools from the app (`features/browser/agent-tools.ts`, RPC external tools on every chat): `browser_navigate`, `browser_tabs`, `browser_screenshot`, `browser_read_page` (outline with `ref_N`), `browser_find`, `browser_click`, `browser_type`, `browser_key`, `browser_form_input`, `browser_scroll`, `browser_eval`, `browser_console`, `browser_network`; `terminal_run`, `terminal_read`; `show_file`. On Windows clicks, keys and screenshots go through the WebView2 DevTools Protocol (trusted input); elsewhere clicks and typing are scripted and screenshots are unavailable | `trace` rows with screenshots |
| Widgets in the chat (`components/widget-frame.tsx`, `lib/widget-document.ts`): a `show_widget` call renders its HTML in a sandboxed iframe (scripts only, CSP with a CDN allowlist, app theme variables, height 120–2400 px) under its tool row, also when the turn folds; `sendPrompt(text)` from the widget sends a user message. `visualize_read_me` is a compact row ([SDD](../../docs/features/office-v3-parity/sdd.md)) | `iframe` |
| Search / commands | `command` dialog (Ctrl/⌘ P) |

## Source layout

```
src/
  app/            app shell: layout, providers, bootstrap + global hotkeys
  components/
    ui/           shadcn primitives — generated, edit only to fix them
    ai-elements/  shadcn/ui AI Elements patterns (ui.shadcn.com/docs/ai-elements) on the engine's data
    markdown.tsx  reply markdown: Streamdown + code-block
  features/       one folder per feature, UI + its local logic
    chat/         thread, turns, composer, transcript reducer
    shell/        sidebar, header bar, window controls
    panels/       side panel + panel registry
    terminal/     Terminal tool: xterm instances, pty IPC
    side-chat/    Side chat tool
    files/        Files tool: explorer, CodeMirror editor, path menu
    browser/      Browser tool + the app's agent tools (browser, terminal, show_file)
    notifications/ notify(), bell + notification center, toasts
    sessions/     command palette
  engine/         protocol types + IPC client (no React)
  stores/         zustand stores: engine (connection + transcript), sessions, ui
  lib/            pure helpers (format, platform, cn)
src-tauri/
  src/engine.rs   child-process bridge to evo-engine
  src/window.rs   Mica / vibrancy material
  src/terminal.rs pseudo-terminals for the Terminal tool
  src/files.rs    list / search / read / save for the Files tool
  src/browser.rs  browser tabs as child webviews, page script, DevTools Protocol
```

Rules of thumb: components read state through store selectors and call store
actions; only `stores/engine-store.ts` talks to `engine/client.ts`; `features/*`
may use `components/*` but not each other's internals.

## Known gaps

- Saved sessions are not listed by the engine over RPC yet, so the sidebar keeps
  the chats started in the app, and switching chats starts a fresh engine.
- The approval mode is stored but not yet sent to the engine.
- Side-panel tools memory, scheduler and plugins are placeholders.
- A window holding browser tabs is no longer a `WebviewWindow` to Tauri:
  commands take `Window` or `Webview`, never `WebviewWindow`.
- Browser: no dev-server launcher (`launch.json`) yet; screenshots and
  trusted input are Windows-only.
- The main bundle is ~1.2 MB (streamdown/shiki); split it with dynamic imports.
