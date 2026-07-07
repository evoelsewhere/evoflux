import { Suspense } from 'react'
import { RouterProvider } from '@tanstack/react-router'
import { useAppBackendBootstrap } from './hooks/use-app-backend-bootstrap'
import { router } from './router'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'

function App() {
  const backendReady = useAppBackendBootstrap()

  if (!backendReady) return <AppLoadingScreen />

  return (
    <Suspense fallback={<AppLoadingScreen />}>
      <RouterProvider router={router} />
    </Suspense>
  )
}

function AppLoadingScreen() {
  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh items-center justify-center bg-(--bg-page)" role="status" aria-label="Loading EvoFlux">
      <div className="relative flex items-center justify-center">
        <div className="absolute h-20 w-20 animate-pulse rounded-3xl bg-(--color-accent) opacity-20 blur-xl motion-reduce:animate-none" />
        <img src={EvoFluxLogo} width={52} height={52} className="relative rounded-2xl" alt="" aria-hidden="true" />
      </div>
    </div>
  )
}

export default App
