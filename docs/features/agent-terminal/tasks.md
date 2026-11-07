# Agent terminal: shell choice and interactive tools — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — Discovery, ownership, the five tools, approvals, transcript

Done when: the verification rows FR-1–FR-15 pass on Windows, and FR-2 and
FR-3 pass on macOS.

- [ ] T1 [P] [FR-1] Write `cargo test` cases for Windows discovery, with temp folders standing in for Git, MSYS2 and Cygwin — `apps/desktop/src-tauri/src/terminal.rs` — check: the tests fail for the missing shells
- [ ] T2 [P] [FR-2, FR-3] Write `cargo test` cases for `/etc/shells` parsing and the id rules — `apps/desktop/src-tauri/src/terminal.rs` — check: the tests fail for the right reason
- [ ] T3 [FR-1, FR-2, FR-3, NFR-2] Implement shell discovery: every Windows shell and each WSL distribution (in the background, 3 s limit), `/etc/shells` + Homebrew + login `PATH` on Unix, stable ids, `ShellInfo.kind` and `isDefault` — `apps/desktop/src-tauri/src/terminal.rs` — check: T1 and T2 pass; `terminal_shells` timed with and without WSL
- [ ] T4 [FR-10, FR-11] `terminal_spawn` takes `owner`, kept in `SessionInfo` and returned by `terminal_list`; killing a session ends its process tree — `apps/desktop/src-tauri/src/terminal.rs`, `apps/desktop/src/features/terminal/pty.ts` — check: reload keeps the owner; killed dev server frees its port
- [ ] T5 [NFR-3, NFR-4] Write unit tests for the output log: ring, offsets, dropped-characters note, cut results — `apps/desktop/src/features/terminal/` — check: the tests fail before T6
- [ ] T6 [FR-8, FR-9, NFR-3, NFR-4, NFR-5] Implement the output log (1 MB escape-free ring, running offset, regex / idle / exit waiters) and feed it from the terminal instance — `apps/desktop/src/features/terminal/output-log.ts`, `apps/desktop/src/features/terminal/terminal-instance.ts` — check: T5 passes
- [ ] T7 [FR-5, FR-10, FR-11] `TerminalTab.owner`, `create({ shell, cwd, owner })`, `kill(key)` — `apps/desktop/src/stores/terminal-store.ts` — check: typecheck; `terminal_list` shows owners
- [ ] T8 [FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, FR-10, FR-14, NFR-4] Tool schemas and handlers for `terminal_list`, `terminal_run`, `terminal_send`, `terminal_read`, `terminal_kill`: shell name resolution, wait for the first prompt, key names to bytes, password-prompt check, 20,000-character results — `apps/desktop/src/features/terminal/agent-tools.ts` — check: drive the tools over WebView2 DevTools (`runUiTool`)
- [ ] T9 [FR-4, FR-5] Drop `terminalTool` from the browser feature; `UI_TOOLS` takes the terminal tools through `features/terminal/index.ts` — `apps/desktop/src/features/browser/agent-tools.ts`, `apps/desktop/src/features/terminal/index.ts` — check: typecheck; old `terminal_run` / `terminal_read` arguments still work
- [ ] T10 [FR-9, FR-12, FR-13, NFR-5] Pass the chat id and an `ask` callback to the terminal tools, keep the per-chat read permission, end waits when the engine drops the call — `apps/desktop/src/stores/engine-store.ts` — check: each approval mode × own / person's tab in the running app
- [ ] T11 [P] [FR-11] Mark agent tabs in the tab strip (agent icon, chat title in the tooltip) — `apps/desktop/src/features/terminal/terminal-panel.tsx` — check: manual in the running app
- [ ] T12 [P] [FR-15] Render the five tools in the transcript — `apps/desktop/src/components/ai-elements/tool.tsx` — check: look at the transcript for each tool
- [ ] T13 [FR-12, FR-13] Add to ADD §9: "App-side tools — terminal, scheduler, connectors — ask through the same approval panel." — `docs/architecture/README.md` — check: review
- [ ] T14 [FR-4, FR-15] Update the UI map and the tool table in [agent tools](../agent-tools/spec.md) — `apps/desktop/README.md`, `docs/features/agent-tools/` — check: review

### Phase 2 — Shell integration

Done when: FR-16 passes for PowerShell, Git Bash, zsh and fish, and Command
Prompt reports the end of a command.

- [ ] T15 [FR-16] Integration scripts for PowerShell, bash, zsh and fish, written to the app's data folder on every start — `apps/desktop/src-tauri/src/shell_integration/` — check: the scripts appear under `<app data>/shell-integration/`
- [ ] T16 [FR-16] `terminal_spawn` passes each shell's extra args and env (and the `PROMPT` sequences for Command Prompt) — `apps/desktop/src-tauri/src/terminal.rs` — check: a new tab of each shell emits markers
- [ ] T17 [FR-16] OSC 133 handler, markers stored in the output log, `wait: true` returns the text between C and D and the exit code; tabs without markers fall back to waits and say so — `apps/desktop/src/features/terminal/terminal-instance.ts`, `apps/desktop/src/features/terminal/output-log.ts`, `apps/desktop/src/features/terminal/agent-tools.ts` — check: `wait: true` with a passing and a failing command in each shell
- [ ] T18 [FR-16] `terminalShellIntegration` setting (boolean, default `true`) in **Settings → General → Terminal** — app settings — check: turning it off starts the next new tab without integration
- [ ] T19 [FR-16] Update the UI map and the tool table in [agent tools](../agent-tools/spec.md) — `apps/desktop/README.md`, `docs/features/agent-tools/` — check: review

### Phase 3 — More shell sources, WSL and Nushell integration

Done when: those shells appear in the list, and WSL and Nushell tabs report
command ends.

- [ ] T20 [FR-1] Windows Terminal profiles and Visual Studio developer shells as extra shell sources — `apps/desktop/src-tauri/src/terminal.rs` — check: they appear in the "New terminal" menu
- [ ] T21 [FR-16] Shell integration for WSL (script path translated into the distribution) and Nushell — `apps/desktop/src-tauri/src/shell_integration/` — check: `wait: true` returns an exit code in WSL and Nushell tabs
- [ ] T22 [FR-1, FR-16] Update the UI map and the tool table in [agent tools](../agent-tools/spec.md) — `apps/desktop/README.md`, `docs/features/agent-tools/` — check: review

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test` for Windows discovery with temp folders standing in for Git, MSYS2, Cygwin; manual check of WSL distributions | not run |
| FR-2 | `cargo test` for `/etc/shells` parsing; manual check on macOS with Homebrew | not run |
| FR-3 | `cargo test` for the id rules; manual check on macOS | not run |
| FR-4 | Drive `terminal_list` over WebView2 DevTools in the running app (`runUiTool`) | not run |
| FR-5 | Drive `terminal_run` in Git Bash and with an unknown shell over WebView2 DevTools | not run |
| FR-6 | Drive `terminal_run` in a slow-starting WSL tab | not run |
| FR-7 | Drive `terminal_send` Ctrl+C to a dev server | not run |
| FR-8 | Drive `terminal_read` twice with the returned cursor | not run |
| FR-9 | Drive `terminal_run` / `terminal_read` with `waitFor`; stop the turn during a wait | not run |
| FR-10 | Drive `terminal_kill`; check the dev server's port is free | not run |
| FR-11 | Reload the window, then `terminal_list` | not run |
| FR-12 | Each approval mode × own tab, in the running app | not run |
| FR-13 | Each approval mode × person's tab, in the running app | not run |
| FR-14 | `sudo -v` in WSL, then `terminal_send` text | not run |
| FR-15 | Look at the transcript for each tool | not run |
| FR-16 | `wait: true` with a passing and a failing command in each shell | not run |
| NFR-1 | Manual check on Windows and macOS | not run |
| NFR-2 | Time `terminal_shells` with and without WSL | not run |
| NFR-3 | Unit tests for `output-log.ts` (ring, offsets) | not run |
| NFR-4 | Unit tests for `output-log.ts` (cut results) | not run |
| NFR-5 | Two chats waiting on two tabs | not run |
