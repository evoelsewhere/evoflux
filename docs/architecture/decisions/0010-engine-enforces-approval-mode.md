# 0010. The engine enforces the approval mode on every tool call

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| ADD sections | [8. Interfaces](../README.md#8-interfaces), [9. Cross-cutting concepts](../README.md#9-cross-cutting-concepts) |
| Related | [Approval modes SDD](../../features/approval-modes/sdd.md), [0005](0005-real-engine-and-live-reload.md) |

## Context

The ADD says tool calls pass a permission check, and the composer offers three
approval modes. In fact the mode is stored only in the webview and never
reaches the engine; the engine asks only when a `PreToolUse` hook, a plugin
handler or the self-kill guard says so. Shell commands and file edits
therefore run without a prompt in every mode. Engines are started both by the
webview and by the Rust shell (nested sessions through the mesh hub), so a
setting held only in the webview cannot reach all of them.

## Decision

The approval mode is an app setting in the app database, given to every
engine at start (`--approval-mode`) and changed live (`set_approval_mode`). The
engine enforces it as the last link of its `before_tool_call` chain: it
classifies each call as a read, an edit or a command and asks through the
existing UI dialog for the kinds the mode does not allow. Tools the app runs
(external tools) are gated by the app, reading the same setting.

## Consequences

- "Ask every time" and "Approve edits" mean what they say for every chat,
  subagent and nested session.
- Every new engine tool must be classified; unclassified tools ask as
  commands, so forgetting is safe but noisy.
- Runs with nobody watching wait for approval unless set otherwise; scheduled
  tasks get their own setting.
- Headless engines (`text`, `json` modes) default to `auto`; a person who asks
  for `ask` there gets refusals, not hangs.
- The ADD §9 permission paragraph names the three modes and the order of the
  checks.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Enforce in the app from tool-call events | Too late: the tool has started; the engine owns agent decisions. |
| Ship the gate as a default `PreToolUse` hook | User configuration that can be switched off; a process per call. |
| Keep the mode in the webview and pass it per prompt | Engines the shell starts without the webview would not get it, and a mid-run change would not apply. |
