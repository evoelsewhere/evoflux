# web/ — Agent Instructions

React/Vite frontend for EvoFlux, embedded in the Tauri shell and served by the backend in packaged builds.

## Tech stack

- Bun, React 19, TypeScript 5.9, Vite 7, Tailwind v4.
- TanStack Router/Query, Zustand + Immer, Base UI, Tauri JS plugins.

## Layout

```
src/           Application code, routes, components, stores, queries
public/        Static assets
vite.config.ts Vite config and API/SSE dev proxy
eslint.config.js ESLint config
components.json shadcn/ui-style component config
```

## Essential commands

```bash
bun install --frozen-lockfile
bun dev                         # Vite on :5173, proxies /api to :8000
bun run lint
bun run typecheck
bun run build
```

## Code style

- ESM only; no `require()`.
- Import app modules through `@/`.
- Prefer functional components with explicit props.
- Use TanStack Query for server state and Zustand stores for client state.
- Keep UI mobile-first and consistent with existing Tailwind v4 patterns.

## Post-implementation checklist

```bash
bun run lint && bun run typecheck
```

## Documentation pointers

- Frontend conventions and test layout: `../documents/docs/guidelines.md`.
- Desktop packaging context: `../documents/docs/desktop.md`.
