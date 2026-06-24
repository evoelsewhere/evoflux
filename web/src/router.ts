import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { Root, NotFound } from './routes/__root'
import { TeamLayout, CodingLayout } from './routes/forge'
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
const codingSessionRoute = createRoute({
  getParentRoute: () => codingLayoutRoute,
  path: '$sessionId',
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
  codingLayoutRoute.addChildren([codingIndexRoute, codingSessionRoute]),
  telemetryRoute,
  schedulerRoute,
])

export const router = createRouter({ routeTree, defaultPreload: 'intent' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
