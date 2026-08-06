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

## Shell structure

- `src/components/shell/` — shared app chrome. `AppShell` owns the page frame (sidebar slot, `<main>` card, Ctrl+B); `SidebarShell` + `SidebarCard`/`SidebarFooter`/`SidebarSearchTrigger` own sidebar chrome; `SidePanel` owns resizable right-hand panels (incl. mobile overlay mode); `SessionRow`/`SessionContextMenu`/`EditSessionTitleDialog`/`CollapsibleSection` are the shared row/menu/section primitives. The mode sidebars (`Sidebar`, `CodingSidebar`) compose these — never hand-roll sidebar/panel chrome in a new view.
- `src/components/chat/` — forge/coding chat chrome (`ChatTopbar`, `ChatPanels`); `TeamChatView/index.tsx` is the composition root, with logic hooks in `TeamChatView/` (`useTeamSse`, `useSlashCommandRegistry`, `useMobileEdgeSwipes`).
- Sidebar collapse lives in `useUIStore.sidebarCollapsed`; pinned sessions in `stores/usePinnedSessions.ts`.
- localStorage keys go through the `STORAGE_KEYS` registry in `src/lib/storage-keys.ts` — no raw string literals (exception: pre-paint scripts in `public/`, which can't import TS and must be kept in sync by hand).
- z-index uses the `--z-*` token scale defined in `index.css` (`z-(--z-modal)` etc.) — no numeric z literals.

## Post-implementation checklist

```bash
bun run lint && bun run typecheck
```

## Documentation pointers

- Frontend conventions and test layout: `../documents/docs/guidelines.md`.
- Desktop packaging context: `../documents/docs/desktop.md`.
