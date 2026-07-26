import { Suspense } from 'react'
import { RouterProvider } from '@tanstack/react-router'
import { useAppBackendBootstrap } from './hooks/use-app-backend-bootstrap'
import { router } from './router'
import { AppMotionConfig } from '@/components/motion/AppMotionConfig'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'

function App() {
  const backendReady = useAppBackendBootstrap()

  return (
    <AppMotionConfig>
      {backendReady ? (
        <Suspense fallback={<AppLoadingScreen />}>
          <RouterProvider router={router} />
        </Suspense>
      ) : (
        <AppLoadingScreen />
      )}
    </AppMotionConfig>
  )
}

function AppLoadingScreen() {
  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col items-center justify-center gap-5 bg-(--bg-page)" role="status" aria-label="Loading EvoFlux">
      <div className="relative flex items-center justify-center">
        <div className="absolute h-20 w-20 animate-pulse rounded-3xl bg-(--color-accent) opacity-20 blur-xl motion-reduce:animate-none" />
        <img src={EvoFluxLogo} width={52} height={52} className="relative rounded-2xl" alt="" aria-hidden="true" />
      </div>
      {/* Fades in late so quick loads never flash it — only a real sidecar
          boot (a few seconds) leaves time for the message to appear. */}
      <p className="animate-[fadeInLate_6s_ease_forwards] text-xs text-(--color-text-muted) opacity-0">
        Starting the local engine…
      </p>
      <style>{'@keyframes fadeInLate { 0%, 60% { opacity: 0 } 100% { opacity: 1 } }'}</style>
    </div>
  )
}

export default App
