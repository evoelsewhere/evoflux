# Agent terminal: shell choice and interactive tools — Spec

| | |
| --- | --- |
| Status | Accepted |
| Area | desktop UI, desktop shell |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Agent tools for working with the person](../agent-tools/spec.md), [Approval modes enforced in the engine](../approval-modes/spec.md) |

## 1. Summary

The agent can already start a command in the app's terminal (`terminal_run`)
and look at a tab's screen (`terminal_read`). It cannot pick the shell, type
into a tab that is already running, press keys such as Ctrl+C, stop a tab,
wait for a line such as "ready on :3000", or tell when a command finished and
with which exit code. These tools also skip the approval mode and read the
person's own tabs without asking. This feature lets the agent choose among the
shells found on the computer, work with a tab interactively, and do it under
the same approvals as its other commands.

The agent tool names and arguments are part of this spec's contract (the
model sees them); their full schemas are in [plan 3.3](plan.md#33-interfaces).

## 2. Scope

### 2.1 Goals

- Find the shells people actually use on Windows, macOS and Linux, with ids
  that are the same on every machine.
- Let the agent list shells and tabs, start a command in a chosen shell or an
  existing tab, send text and keys, read only new output, wait for a pattern
  or for output to settle, and stop a tab.
- Know which chat started each tab, and ask before the agent runs commands,
  types into or reads a tab it did not start.
- Know where each command starts and ends, and its exit code, through shell
  integration (FR-16).
- Later: Windows Terminal profiles and Visual Studio developer shells as extra
  shell sources, and command ends reported in WSL and Nushell tabs (see
  [tasks.md](tasks.md), phase 3).

### 2.2 Non-goals

- One-off commands: the engine's own shell tools (`bash`, `powershell`) stay
  the way to run a command and get its output; the terminal is for long-lived
  and interactive work the person can watch.
- Engine-wide enforcement of the composer's approval mode for built-in tools:
  [approval modes](../approval-modes/spec.md). This feature gates only the
  terminal tools, in the app.
- Typing passwords or secrets for the person.
- Full-screen programs (vim, htop) beyond reading their current screen.
- Remote shells (SSH profiles).

## 3. User scenarios

### US-1 Start a long-running command and wait for it (priority P1)

The agent wants to start a dev server in the shell the project needs and
continue as soon as it is ready, so that it does not guess with fixed waits.

Acceptance scenarios:

1. **Given** Git Bash is installed, **when** the agent runs `npm run dev` in
   the shell "Git Bash" and waits for "ready on", **then** a Git Bash tab
   opens, the command is typed once the shell's prompt appears, and the call
   returns as soon as the line is printed.
2. **Given** a shell that is not on this computer, **when** the agent asks for
   it, **then** the call fails and lists the shells that are available.

### US-2 Work with a running tab (priority P1)

The agent wants to follow a tab's output, press keys in it and stop it, so
that it can drive interactive programs the person can watch.

Acceptance scenarios:

1. **Given** a tab the chat started, **when** the agent reads it twice with
   the returned cursor, **then** the second read returns only the new lines.
2. **Given** a tab running a dev server, **when** the agent presses Ctrl+C,
   **then** the server stops and the tab shows a prompt again.
3. **Given** a tab running a dev server, **when** the agent stops the tab,
   **then** the tab shows exited and the server's port is free.

### US-3 The person stays in control of their terminal (priority P1)

The person wants the terminal tools to follow the approval mode and never
touch their own tabs silently, so that the agent cannot run or read anything
they did not allow.

Acceptance scenarios:

1. **Given** "Ask every time", **when** the agent runs a command, **then**
   an approval names the shell, folder and command, and nothing is typed until
   the person allows it.
2. **Given** "Approve for me", **when** the agent reads a tab the person
   opened, **then** it asks "Let the agent read <tab>?" the first time only.
3. **Given** a tab waiting for a password, **when** the agent tries to type
   text, **then** nothing is typed and the agent is told to ask the person.
4. **Given** the agent started a tab, **when** the person looks at the tab
   strip, **then** the tab is marked as an agent tab, also after a window
   reload.

### US-4 Know when a command finished (priority P2)

The agent wants a command's exit code and only its output, so that it can
tell success from failure without reading the whole screen.

Acceptance scenarios:

1. **Given** a bash tab, **when** the agent runs `git status` and waits for
   it to finish, **then** the result says `exit code 0` and holds only the
   status text.
2. **Given** Command Prompt, **when** a command finishes, **then** the end is
   reported without an exit code.

### Edge cases

- Window reload while the agent works with tabs: FR-11, NFR-3.
- A chat that was deleted while its tabs keep running, and two chats using
  one tab: FR-13.
- Very large output: NFR-4.
- The full list of failure cases and what the agent and the person see:
  [plan 3.6](plan.md#36-errors-and-edge-cases).

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | On Windows the shell list holds every one of these that is installed: PowerShell 7, Windows PowerShell, Command Prompt, Git Bash, each WSL distribution, MSYS2 bash, Cygwin bash, Nushell. | Given a machine with Git, two WSL distributions and Nushell, when the terminal's "New terminal" menu opens, then it lists Git Bash, both distributions by name and Nushell. |
| FR-2 | On macOS and Linux the list holds the shells in `/etc/shells`, Homebrew's `bin` folders and the login shell's `PATH`; the login shell (`$SHELL`) is marked default. | Given macOS with Homebrew bash and fish, when the list loads, then it shows zsh (default), bash 5 from Homebrew and fish, once each. |
| FR-3 | Shell ids are stable across machines: the program's file name (`zsh`, `bash`, `pwsh`), plus `git-bash`, `msys2`, `cygwin`, `cmd`, `powershell`, `wsl:<distribution>`. | The same zsh is `zsh` whether or not it is `$SHELL`. |
| FR-4 | `terminal_list` returns the shells (id, name, default) and the tabs (id, title, shell, folder, status, who started it). It returns no tab content. | Called with one tab of the person's and one of this chat's, it lists both with owners `you` and `this chat`. |
| FR-5 | `terminal_run` starts a command in a new tab with a chosen shell (by id, name or file name), or in an existing tab (`tabId`). An unknown shell is an error that lists the available ids. | `{"command":"ls","shell":"Git Bash"}` opens a Git Bash tab; `{"shell":"tcsh"}` on Windows returns an error naming the shells found. |
| FR-6 | `terminal_run` types the command once the shell has printed its first prompt (output then 300 ms of quiet, at most 10 s), not after fixed sleeps. | A slow-starting WSL tab still receives the whole command. |
| FR-7 | `terminal_send` sends text and named keys (Enter, Tab, Esc, Backspace, arrows, Home, End, PageUp/PageDown, Ctrl+A–Z) to a tab. | Sending `["ctrl+c"]` to a tab running a dev server stops it and the tab shows a prompt again. |
| FR-8 | `terminal_read` with `since` returns only the output written after that cursor, without escape codes, and a new cursor; without `since` it returns the current screen. | Two reads in a row with the returned cursor return the new lines only. |
| FR-9 | `terminal_read` (and `terminal_run`) can wait for a regular expression in new output or for `untilIdleMs` of quiet, up to `timeoutMs` (max 120 s), and say whether it matched or timed out. Stopping the run ends the wait. | `waitFor: "ready on"` returns as soon as the line appears; a stopped turn returns at once. |
| FR-10 | `terminal_kill` stops a tab's shell and the programs it started; with `close: true` it also closes the tab. | After `terminal_kill`, the tab shows exited and the dev server's port is free. |
| FR-11 | Each tab records the chat that started it; the tab strip marks agent tabs, and the owner survives a window reload. | After a reload, `terminal_list` still shows the tab as `this chat`. |
| FR-12 | Commands follow the approval mode: `terminal_run` and `terminal_send` ask in "Ask every time" and "Approve edits", run directly in "Approve for me". | In "Ask every time", `terminal_run` shows an approval with the shell, folder and command, and nothing is typed until it is allowed. |
| FR-13 | Acting on a tab the chat did not start always asks: reading it (once per tab per chat), typing into it, running in it and stopping it, whatever the approval mode. | In "Approve for me", `terminal_read` on the person's tab asks "Let the agent read <tab>?" the first time only. |
| FR-14 | `terminal_send` refuses text when the tab's last line looks like a password prompt, and tells the agent to ask the person. | With `sudo` waiting for a password, sending text returns an error and types nothing. |
| FR-15 | The transcript shows each terminal call: the tool, shell and tab, the command or keys, and the output excerpt. | A `terminal_send` of Ctrl+C shows "Pressed Ctrl+C in <tab>". |
| FR-16 | In PowerShell, bash (incl. Git Bash and MSYS2), zsh and fish, `terminal_run` with `wait: true` returns when the command finishes, with its exit code and only its output. Command Prompt reports the end without an exit code. | `{"command":"git status","shell":"bash","wait":true}` returns `exit code 0` and the status text only. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Platforms: Windows 10/11 (ConPTY), macOS 11+, Linux. | Manual check on Windows and macOS. |
| NFR-2 | Shell discovery takes under 300 ms on the UI's critical path; WSL distributions load in the background with a 3 s limit. | Opening the menu right after start does not wait for WSL. |
| NFR-3 | Each tab keeps at most 1 MB of plain output for cursors; a cursor older than that says how much was dropped. | Reading with a stale cursor returns a "… N characters dropped" line, then the kept output. |
| NFR-4 | A tool result holds at most 20,000 characters (the end of the output) and says when it was cut. | Reading a build log of 1 MB returns its last 20,000 characters and a note. |
| NFR-5 | Waiting does not block the UI or other chats' tools. | Two chats waiting on two tabs both return on time. |

## 5. Success criteria

- SC-1 With "Approve for me", the agent can start a dev server in any listed
  shell, wait for its ready line and stop it again without the person typing
  anything.
- SC-2 Nothing is typed into, run in, read from or stopped in a tab the chat
  did not start without the person's approval.
- SC-3 The "New terminal" menu opens right after start without waiting for
  WSL distributions.
- SC-4 In PowerShell, Git Bash, zsh and fish, a finished command reports its
  exit code, so a failing command is told apart from a passing one every time.

## 6. Clarifications

### 6.1 Open

None.

### 6.2 Resolved

- 2026-11-07 — Q: Should this feature enforce the approval mode engine-wide?
  → A: No. Engine-wide enforcement is a separate fix
  ([approval modes](../approval-modes/spec.md)); this feature reads the mode
  in the app, so the terminal tools are gated either way (section 2.2, FR-12).
- 2026-11-07 — Q: Is the approval mode global or per chat? → A: It stays
  global, as the composer shows it (FR-12, plan 3.7).
- 2026-11-07 — Q: What environment do tabs the agent starts get? → A: They
  follow the sandbox's `inheritEnv` rule (plan 3.7).
- 2026-11-07 — Q: Are Windows Terminal profiles and Visual Studio developer
  shells in scope? → A: Later work (section 2.1; tasks phase 3).
- 2026-11-07 — Q: Is shell integration for WSL and Nushell in scope? → A:
  Later work (section 2.1; plan 3.5; tasks phase 3).
- 2026-11-07 — Q: Should `terminal_run` accept multi-line commands? → A: No,
  it stays one line; `terminal_send` with newlines covers multi-line input
  (plan 3.3).
- 2026-11-07 — Q: Does this need an ADR? → A: No: the feature applies the
  existing approval flow to app-side tools. The ADD's cross-cutting section
  gains one sentence (tasks phase 1).

## 7. History

- 2026-11-07 — Draft.
- 2026-11-07 — Accepted with the proposed answers to every open question.
- 2026-11-07 — Moved to the spec / plan / tasks format.
