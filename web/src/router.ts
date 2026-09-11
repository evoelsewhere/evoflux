import { lazy } from 'react'
import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { Root, NotFound } from './routes/__root'
import { restoreLastRouteBeforeRouterMount } from '@/lib/mode-route'
import { TelemetryRedirect } from './routes/telemetry'

restoreLastRouteBeforeRouterMount()

const TeamLayout = lazy(() =>
  import('./routes/work').then((module) => ({ default: module.TeamLayout })),
)
const CodingLayout = lazy(() =>
  import('./routes/work').then((module) => ({ default: module.CodingLayout })),
)
const SchedulerPage = lazy(() =>
  import('./routes/scheduler').then((module) => ({ default: module.SchedulerPage })),
)

const rootRoute = createRootRoute({
  component: Root,
  notFoundComponent: NotFound,
})

// / layout — work mode, persists across / and /$sessionId
const teamLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'work',
  component: TeamLayout,
})
const teamIndexRoute = createRoute({
  getParentRoute: () => teamLayoutRoute,
  path: '/',
  component: () => null,
})
const teamSessionRoute = createRoute({
  getParentRoute: () => teamLayoutRoute,
  path: '$sessionId',
  component: () => null,
})

// /coding layout — coding mode without query-string mode state
const codingLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/coding',
  component: CodingLayout,
})
const codingIndexRoute = createRoute({
  getParentRoute: () => codingLayoutRoute,
  path: '/',
  component: () => null,
})
// /coding/$focusId[/$sessionId] — $focusId anchors the sidebar/panel to a
// specific workspace (URL-encoded path) or project (UUID) even before a
// session is picked; see utils/workspace.ts's codingFocusId/isProjectFocusId.
// NOTE: there is deliberately no separate /coding/$sessionId route anymore —
// a single dynamic segment can't be split between two sibling routes (one
// wins arbitrarily), so a bare old-style /coding/{sessionId} link is parsed
// as $focusId too. TeamLayoutBase's resolve effect falls back to treating it
// as a legacy session id when it doesn't resolve as a project/workspace.
const codingFocusRoute = createRoute({
  getParentRoute: () => codingLayoutRoute,
  path: '$focusId',
  component: Outlet,
})
const codingFocusIndexRoute = createRoute({
  getParentRoute: () => codingFocusRoute,
  path: '/',
  component: () => null,
})
const codingFocusSessionRoute = createRoute({
  getParentRoute: () => codingFocusRoute,
  path: '$sessionId',
  component: () => null,
})

// /telemetry — kept only so existing links and bookmarks land somewhere.
//
// Telemetry lives in Settings now. It used to be both: a standalone page
// with its own sidebar carrying Models and Tools, and a Settings page with
// only Overview and Traces. The standalone one was linked from nowhere, so
// half the monitoring views were reachable by URL alone.
const telemetryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/telemetry',
  component: TelemetryRedirect,
})

// /scheduler — standalone scheduler page (manage scheduled tasks)
const schedulerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/scheduler',
  component: SchedulerPage,
})

const routeTree = rootRoute.addChildren([
  teamLayoutRoute.addChildren([teamIndexRoute, teamSessionRoute]),
  codingLayoutRoute.addChildren([
    codingIndexRoute,
    codingFocusRoute.addChildren([codingFocusIndexRoute, codingFocusSessionRoute]),
  ]),
  telemetryRoute,
  schedulerRoute,
])

export const router = createRouter({ routeTree, defaultPreload: 'intent' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
