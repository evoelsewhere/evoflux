# web/src/ — Agent Instructions

Frontend application source: routes, API client, streaming stores, UI components, hooks, and tests.

## Where to look first

```
api/          Backend client, auth token injection, SSE parser
routes/       TanStack Router pages
components/   Reusable UI and feature components
stores/       Zustand stores for team/session/UI state
queries/      TanStack Query hooks and mutations
hooks/        Shared React hooks
utils/        Markdown, formatting, block/event helpers
__tests__/    Bun/Happy DOM tests mirroring app areas
router.ts     Route tree setup
index.css     Tailwind v4 theme/global styles
```

## Common feature checks

- Backend API shape changed: update `api/client.ts`, query hooks, stores, and tests.
- SSE event changed: update `api/sse*`, block helpers in `utils/blocks.ts`, and `stores/useTeamStore*`.
- New page/route: update TanStack route setup and add focused route/component tests.
- Settings form change: check zod/client validation and matching backend schema.
- Tool rendering change: inspect `components/ToolCall*` and copy/formatting tests.

## Commands

```bash
bun run lint
bun run typecheck
bunx tsc -p tsconfig.test.json --noEmit
bun run test
```

## Gotchas

- Use static ESM imports and `@/` aliases.
- Tests rely on isolated module state; keep using the package test script.
- Store tests usually seed with `useStore.setState(...)` and assert via `useStore.getState()`.
- Preserve desktop token injection rules: only same-origin `/api` requests receive auth.
