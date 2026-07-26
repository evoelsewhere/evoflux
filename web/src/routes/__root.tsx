import { QueryClientProvider } from '@tanstack/react-query'
import { Suspense, useEffect } from 'react'
// Temporarily disabled for clean recordings — re-enable when done.
// import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { Link, Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { queryClient } from '@/lib/query-client'
import { Home } from 'lucide-react'
import { ToastStack } from '@/components/ToastStack'
import { MacTitleBar } from '@/components/MacTitleBar'
import { SettingsScreen } from '@/components/SettingsScreen'
import { WikiPanel } from '@/components/WikiPanel'
import { SchedulerPanel } from '@/components/SchedulerPanel'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { useHistorySwipeNavigation } from '@/hooks/use-history-swipe-navigation'
import { useMobileViewportGuards } from '@/hooks/use-mobile-viewport'
import { useDesktopCommands } from '@/lib/desktop-commands'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'
import { STORAGE_KEYS } from '@/lib/storage-keys'

/**
 * RootOverlayPanels — fixed-position utility overlays that must open in
 * every mode (forge / coding / aim), not just where a TeamChatView happens
 * to be mounted. Open state lives in useUIStore (with mutual exclusion).
 * The scheduler's create-form context used to come from TeamChatView
 * props; the /coding routes prime ``useTeamStore._workspace`` from the URL
 * (see routes/forge.tsx), so the same values are derivable here from the
 * router + team store.
 */
function RootOverlayPanels() {
  const wikiOpen = useUIStore((s) => s.wikiOpen)
  const schedulerOpen = useUIStore((s) => s.schedulerOpen)
  const closeWiki = useUIStore((s) => s.closeWiki)
  const closeScheduler = useUIStore((s) => s.closeScheduler)
  const location = useLocation()
  const contextMode: 'forge' | 'coding' = location.pathname.startsWith('/coding') ? 'coding' : 'forge'
  const codingWorkspace = useTeamStore((s) => s._workspace)
  return (
    <>
      <WikiPanel open={wikiOpen} onClose={closeWiki} />
      <SchedulerPanel
        open={schedulerOpen}
        onClose={closeScheduler}
        contextMode={contextMode}
        contextWorkspace={contextMode === 'coding' ? codingWorkspace : null}
      />
    </>
  )
}

export function Root() {
  useMobileViewportGuards()
  useDesktopCommands()
  useHistorySwipeNavigation()
  // Theme application is handled by `initTheme()` in main.tsx and the
  // inline pre-paint script in index.html. Do not force `.dark` here —
  // it would override the user's preference.
  const navigate = useNavigate()
  const location = useLocation()
  const settingsOpen = useUIStore((state) => state.settingsOpen)

  useEffect(() => {
    if (window.location.pathname === '/' && window.location.search === '') {
      const savedRoute = localStorage.getItem(STORAGE_KEYS.lastRoute)
      if (savedRoute && savedRoute !== '/') {
        navigate({ to: savedRoute, replace: true })
      }
    }
  }, [navigate])

  useEffect(() => {
    const fullPath = window.location.pathname + window.location.search + window.location.hash
    localStorage.setItem(STORAGE_KEYS.lastRoute, fullPath)
  }, [location])

  return (
    <QueryClientProvider client={queryClient}>
      <MacTitleBar />
      {settingsOpen ? (
        <Suspense fallback={<RouteLoadingFallback />}>
          <SettingsScreen />
        </Suspense>
      ) : (
        <>
          <Suspense fallback={<RouteLoadingFallback />}>
            <Outlet />
          </Suspense>
          <RootOverlayPanels />
        </>
      )}
      <ToastStack />
      {/* <ReactQueryDevtools initialIsOpen={false} /> */}
    </QueryClientProvider>
  )
}

function RouteLoadingFallback() {
  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh items-center justify-center bg-(--bg-page)" role="status" aria-label="Loading EvoFlux">
      <div className="relative flex items-center justify-center">
        <div className="absolute h-20 w-20 animate-pulse rounded-3xl bg-(--color-accent) opacity-20 blur-xl motion-reduce:animate-none" />
        <img src={EvoFluxLogo} width={52} height={52} className="relative rounded-2xl" alt="" aria-hidden="true" />
      </div>
    </div>
  )
}

export function NotFound() {
  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col items-center justify-center gap-6 bg-(--bg-page)">
      <div className="text-center">
        <p className="font-mono text-6xl font-bold text-(--color-text-muted)">404</p>
        <p className="mt-3 text-sm text-(--color-text-muted)">Page not found</p>
      </div>
      <Link
        to="/"
        className="interactive-weight flex items-center gap-2 rounded-lg bg-(--bg-key) px-4 py-2 text-sm text-(--color-accent) ring-1 ring-(--color-border-strong) transition-colors hover:bg-(--bg-key)"
      >
        <Home size={14} />
        Go home
      </Link>
    </div>
  )
}
