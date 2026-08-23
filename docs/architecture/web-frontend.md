# Web frontend

The frontend is a React 19, TypeScript and Vite application embedded in the
Tauri WebView. In development it runs at Vite's loopback server; production
packages `web/dist` into the desktop application.

## Route model

`web/src/router.ts` has four primary route families:

| Route | Surface |
|---|---|
| `/` and `/:sessionId` | Work mode and an optional active session |
| `/coding/:focusId?/:sessionId?` | Coding workspace/project focus and session |
| `/telemetry` | Standalone observability explorer |
| `/scheduler` | Standalone scheduled-task manager |

Settings and Help are application overlays owned by `routes/__root.tsx`, not
URL routes. `focusId` is either a URL-encoded workspace path or a project UUID;
the resolver retains compatibility with legacy Coding session URLs.

## State boundaries

| State kind | Owner | Examples |
|---|---|---|
| Server state | TanStack Query | agents, sessions, projects, Git, scheduler, settings |
| Live turn state | Zustand team store | blocks, agent activity, plan/questions, queue, usage |
| UI state | Zustand UI store | panels, sidebars, settings/help, view mode |
| Persistent browser preference | named `STORAGE_KEYS` | routes, appearance, pane sizes, pins |
| Native state | Tauri commands/events | backend URL, updater, tray, browser, file dialogs |

Only same-origin `/api` calls receive the desktop token. API types and parsing
live in `web/src/api`; mutations must invalidate/update the corresponding query
cache rather than maintaining a second durable truth in component state.

## Chat and workbench composition

`TeamChatView/index.tsx` is the main composition root. It combines:

- Work or Coding sidebar;
- transcript, streaming activity and agent switching;
- composer, attachments, skills, snippets, commands and workflow invocation;
- plan, permission and question interaction surfaces;
- single, Split and Monitor layouts;
- a lazy workbench dock for files, editor, Git, graph, Problems, terminal,
  browser, wiki, scheduler, plugins, processes and Side Chat.

Large panels are lazy-loaded. Logic is split into hooks for SSE, slash-command
registry, commands, auto-layout, responsive overlays and mobile gestures.
Shared shell primitives in `components/shell/` own sidebars, panels, rows,
context menus and mobile behavior.

## Streaming projection

`useTeamSse` connects/reconnects the session stream and projects envelope types
into the team store. Replayed history is loaded before live deltas. Event
handlers preserve partial turns, member streams, queued messages, todos, goal
progress, workflow progress, tool blocks, plan requests and terminal states.

Any backend SSE shape change must update all of:

1. the backend event schema/envelope;
2. `web/src/api` parsing;
3. block utilities and the team store;
4. the component that renders or acknowledges the event;
5. focused backend and frontend tests.

## Settings and in-app help

Settings covers providers, agents, Skills, MCP, sandbox, memory/Dream, language
servers, version control, built-in browser/WebBridge, connection/Conductor,
notifications, appearance, telemetry and diagnostics. Forms use matching
backend schemas and explicit query mutations.

The Help Center is a typed article catalogue under `web/src/help/locales/`.
English, Vietnamese and Japanese catalogues must keep the same category/article
IDs. Search indexes article blocks locally. User-visible feature changes should
update Help as well as the technical feature page.

## Design system

Tailwind v4 tokens are defined in `web/src/index.css`; reusable controls live
under `components/ui`. Z-index values use the named `--z-*` scale. Motion
tokens and user intensity presets are shared by CSS, the pre-paint script and
`web/src/lib/motion.ts`; see [Design system reference](../reference/design-system.md).

The shell is mobile-first and respects safe areas, reduced motion, native macOS
window controls, keyboard shortcuts and focus management.

## Verification

Run `bun run lint`, `bun run typecheck`, and the focused Vitest files under
`web/src/__tests__`. `bun run build` is required when a change can affect
production bundling or lazy imports.
