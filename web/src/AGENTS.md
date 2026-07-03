# web/src/ — Agent Instructions

Frontend application source: routes, API client, streaming stores, UI components, hooks.

## Where to look first

```
api/          Backend client, auth token injection, SSE parser
routes/       TanStack Router pages
components/   Reusable UI and feature components
stores/       Zustand stores for team/session/UI state
queries/      TanStack Query hooks and mutations
hooks/        Shared React hooks
utils/        Markdown, formatting, block/event helpers
router.ts     Route tree setup
index.css     Tailwind v4 theme/global styles
```

## Common feature checks

- Backend API shape changed: update `api/client.ts`, query hooks, and stores.
- SSE event changed: update `api/sse*`, block helpers in `utils/blocks.ts`, and `stores/useTeamStore*`.
- New page/route: update TanStack route setup.
- Settings form change: check zod/client validation and matching backend schema.
- Tool rendering change: inspect `components/ToolCall*`.

## Commands

```bash
bun run lint
bun run typecheck
```

## Gotchas

- Use static ESM imports and `@/` aliases.
- Preserve desktop token injection rules: only same-origin `/api` requests receive auth.
