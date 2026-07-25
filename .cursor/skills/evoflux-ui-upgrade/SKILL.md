---
name: evoflux-ui-upgrade
description: >-
  Orchestrates the EvoFlux comprehensive UI/UX upgrade phases (motion, chrome,
  panels, settings, chat). Use when implementing the UI/UX full upgrade plan,
  delegating UI-only phases to subagents, or verifying frontend polish work.
---

# EvoFlux UI Upgrade Orchestrator

## Constraints

- **UI-only** — no API, store contract, or backend changes
- Always load `evoflux-product-ui` + `design-motion-product` before editing
- Use `design-taste` / `design-redesign` / `design-ui-ux-pro-max` for design decisions
- Work on branch `feat/ui-ux-comprehensive` unless told otherwise

## Phase order

1. **A — Motion system** — kill hardcoded chrome durations; helpers in `lib/motion.ts`
2. **B — Forge/Coding chrome** — sidebars, topbar, empty states, composer, coding headers
3. **C — Panels** — Monitor, Activity, Browser, Terminal, Graph; hide dead Task List
4. **D — Settings outliers** — Providers, Telemetry, AgentForm/McpServerForm cards
5. **E — Chat content** — block enter, ToolCall, LoadingVerb/ThinkingDots

## Allowlist

Prefer edits under `web/src/**` and `web/public/appearance-init.js`. Do not touch `app/` or tests unless fixing a type import breakage from UI-only renames.

## Verify each phase

```bash
cd web && bun run lint && bun run typecheck
```

Smoke: Appearance Reduced → Cinematic on Settings modal, sidebar, composer, Coding Workspace, one Monitor/Terminal open.
