import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useEffect } from 'react'
// Temporarily disabled for clean recordings — re-enable when done.
// import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { queryClient } from '@/lib/query-client'
import { Home } from 'lucide-react'
import { ToastStack } from '@/components/ToastStack'
import { MacTitleBar } from '@/components/MacTitleBar'
import { PersistentModeNavigation } from '@/components/shell/PersistentModeNavigation'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { useHistorySwipeNavigation } from '@/hooks/use-history-swipe-navigation'
import { useMobileViewportGuards } from '@/hooks/use-mobile-viewport'
import { useDesktopCommands } from '@/lib/desktop-commands'
import { useUIStore } from '@/stores/useUIStore'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { saveModeRoute } from '@/lib/mode-route'

const SettingsScreen = lazy(() =>
  import('@/components/SettingsScreen').then((module) => ({
    default: module.SettingsScreen,
  })),
)

export function Root() {
  useMobileViewportGuards()
  useDesktopCommands()
  useHistorySwipeNavigation()
  // Theme application is handled by `initTheme()` in main.tsx and the
  // inline pre-paint script in index.html. Do not force `.dark` here —
  // it would override the user's preference.
  const location = useLocation()
  const settingsOpen = useUIStore((state) => state.settingsOpen)

  useEffect(() => {
    const fullPath = window.location.pathname + window.location.search + window.location.hash
    localStorage.setItem(STORAGE_KEYS.lastRoute, fullPath)
    saveModeRoute(window.location.pathname, fullPath)
  }, [location])

  return (
    <QueryClientProvider client={queryClient}>
      <MacTitleBar />
      <PersistentModeNavigation />
      {settingsOpen ? (
        <Suspense fallback={<RouteLoadingFallback />}>
          <SettingsScreen />
        </Suspense>
      ) : (
        <>
          <Suspense fallback={<RouteLoadingFallback />}>
            <Outlet />
          </Suspense>
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
