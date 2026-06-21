# Comparison

The coding-agent landscape exploded in 2025-2026: Claude Code, Codex CLI, Cursor,
Windsurf, Cline, Aider, opencode, and others all run agents with tools, and most
have some form of memory now. The real difference is **what workflow they fit
into**.

> **A note on accuracy.** Rows in our column are sourced from this repo. Rows in
> competitor columns are sourced from each project's public README and docs as of
> the date this file was last updated. If you spot something wrong, please open
> a PR — we'd rather be corrected than ship an inaccurate comparison.

## At a glance

| Row | EvoFlux | Claude Code | Codex CLI | Cursor / Windsurf | Aider | opencode |
|---|---|---|---|---|---|---|
| Maintainer | khuonghung (community) | Anthropic | OpenAI | Cursor / Codeium | Paul Gauthier (community) | anomalyco (community) |
| License | Apache 2.0 | Proprietary | Proprietary (Apache CLI shell) | Proprietary | Apache 2.0 | MIT |
| Surface | Desktop app + web cockpit | Terminal (CLI) | Terminal (CLI) | IDE (VS Code fork) | Terminal (CLI) | Terminal (TUI) |
| Primary use case | Personal AI OS - coding + research + media + scheduling | Repo-scoped coding agent | Repo-scoped coding agent | In-editor pair-programming | Repo-scoped coding agent | Repo-scoped coding agent |
| Provider lock | 15 providers (BYO key) | Anthropic only | OpenAI only | Anthropic + few, subscription | Many via LiteLLM | Many via Models.dev |
| Cost model | Your API keys | Anthropic subscription/API | OpenAI subscription/API | $20/mo+ subscription | Your API keys | Your API keys |

## Capability matrix

| | EvoFlux | Claude Code | Codex CLI | Cursor / Windsurf | Aider | opencode |
|---|---|---|---|---|---|---|
| Native desktop GUI | ✅ EvoFlux | terminal | terminal | IDE | terminal | terminal |
| In-app auto-updater | ✅ EvoFlux | brew/manual | brew/manual | yes (editor) | pip/brew | brew/manual |
| Watch live tool calls (inspector + arguments + results + diffs in GUI) | ✅ EvoFlux | terminal text | terminal text | inline in editor | terminal text | TUI |
| Multi-agent concurrent team view (split pane, lead + workers) | ✅ EvoFlux | sub-agents (sequential) | — | — | — | build/plan agents |
| Git-backed `/undo` and `/redo` across chat history | ✅ EvoFlux | — | — | editor undo | git commits | — |
| `@file` / `@folder` auto-attach to first turn | ✅ EvoFlux | manual @ in v0.2+ | — | yes | manual /add | yes |
| Persistent across reload (close tab → agent keeps running → stream resumes) | ✅ EvoFlux | session-scoped | session-scoped | editor-scoped | session-scoped | session-scoped |
| Cross-session memory beyond per-repo `CLAUDE.md` | editable wiki | per-repo `CLAUDE.md` | — | project rules | per-repo conventions | — |
| Local LLM support (Ollama, etc.) | ✅ first-class | — | — | partial | via LiteLLM | yes |
| Native image + video generation | ✅ built-in | — | — | — | — | — |
| Built-in telemetry dashboard | ✅ EvoFlux | — | — | — | — | — |
| Scheduling / cron / one-shot | ✅ EvoFlux | — | — | — | — | — |
| Voice input | ✅ client speech recognition | — | — | — | — | — |
| Documented HTTP API to embed | ✅ REST + SSE | — | — | — | — | — |

## Where EvoFlux fits

EvoFlux is the *desktop cockpit for local AI agents*. Other tools are coding
agents that live in your terminal or editor; EvoFlux is a long-running desktop
app that runs a team of agents on your hardware, drives your whole workflow
(code, research, media, scheduling), and shows you every step in a real UI. If
you want one polished local app to watch what your agents are doing - not a
coding-only terminal session - start here.

## When NOT to pick EvoFlux

- If you live full-time in a TUI / SSH session and want a single coding agent, Claude Code or Aider are simpler.
- If you only want in-IDE pair programming with no separate window, Cursor or Windsurf are the right shape.
- If you want a cloud agent service with no infrastructure, this isn't that.
