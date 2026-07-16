import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { Root, NotFound } from './routes/__root'
import { TeamLayout, CodingLayout } from './routes/forge'
import { AimLayout } from './routes/aim'
import { TelemetryPage } from './routes/telemetry'
import { SchedulerPage } from './routes/scheduler'

const rootRoute = createRootRoute({
  component: Root,
  notFoundComponent: NotFound,
})

// / layout — forge mode, persists across / and /$sessionId
const teamLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'forge',
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

// /aim layout — AIM mode: sidebar → project → feature → main content
// (documents/plans/aim-mode-shell-ux-spec.md v2.2). The layout component
// reads $projectId/$feature itself via useParams(strict: false); the child
// routes exist to shape the URL space.
const aimLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/aim',
  component: AimLayout,
})
const aimIndexRoute = createRoute({
  getParentRoute: () => aimLayoutRoute,
  path: '/',
  component: () => null,
})
const aimProjectRoute = createRoute({
  getParentRoute: () => aimLayoutRoute,
  path: '$projectId',
  component: Outlet,
})
const aimProjectIndexRoute = createRoute({
  getParentRoute: () => aimProjectRoute,
  path: '/',
  component: () => null,
})
const aimFeatureRoute = createRoute({
  getParentRoute: () => aimProjectRoute,
  path: '$feature',
  component: () => null,
})

// /telemetry — standalone observability page (span aggregates & latency)
const telemetryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/telemetry',
  component: TelemetryPage,
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
  aimLayoutRoute.addChildren([
    aimIndexRoute,
    aimProjectRoute.addChildren([aimProjectIndexRoute, aimFeatureRoute]),
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
