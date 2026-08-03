import { Suspense } from 'react'
import { RouterProvider } from '@tanstack/react-router'
import { FileText, RotateCcw } from 'lucide-react'
import { useAppBackendBootstrap } from './hooks/use-app-backend-bootstrap'
import { router } from './router'
import { AppMotionConfig } from '@/components/motion/AppMotionConfig'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { useLocale } from '@/i18n'

const ANSI_SGR_PATTERN = new RegExp(
  `${String.fromCharCode(27)}\\[[0-9;]*m`,
  'g',
)

function App() {
  useLocale()
  const backend = useAppBackendBootstrap()

  return (
    <AppMotionConfig>
      {backend.ready ? (
        <Suspense fallback={<AppLoadingScreen />}>
          <RouterProvider router={router} />
        </Suspense>
      ) : (
        <AppLoadingScreen
          startup={backend.startup}
          onRetry={backend.retry}
          onRevealLog={backend.revealLog}
        />
      )}
    </AppMotionConfig>
  )
}

interface AppLoadingScreenProps {
  startup?: ReturnType<typeof useAppBackendBootstrap>['startup']
  onRetry?: () => Promise<void>
  onRevealLog?: () => Promise<void>
}

function AppLoadingScreen({ startup, onRetry, onRevealLog }: AppLoadingScreenProps) {
  const hasError = startup?.phase === 'error'
  const seconds = startup ? Math.max(1, Math.round(startup.elapsed_ms / 1_000)) : 0
  const errorSummary = startup?.error
    ?.replace(ANSI_SGR_PATTERN, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 520)

  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col items-center justify-center bg-(--bg-page) px-6" role="status" aria-label="Loading EvoFlux">
      <div className="relative flex items-center justify-center">
        <div className="absolute h-20 w-20 animate-pulse rounded-3xl bg-(--color-accent) opacity-20 blur-xl motion-reduce:animate-none" />
        <img src={EvoFluxLogo} width={52} height={52} className="relative rounded-2xl" alt="" aria-hidden="true" />
      </div>
      <div className="mt-5 flex w-full max-w-md flex-col items-center text-center">
        <p className="text-sm font-medium text-(--color-text)">
          {startup?.message ?? 'Loading EvoFlux…'}
        </p>
        {!hasError && startup ? (
          <>
            <div className="mt-4 h-1 w-48 overflow-hidden rounded-full bg-(--color-border-subtle)">
              <div className="h-full w-2/5 animate-[engineProgress_1.4s_ease-in-out_infinite] rounded-full bg-(--color-accent)" />
            </div>
            <p className="mt-3 text-xs text-(--color-text-muted)">
              {startup.attempt > 0 ? `Attempt ${startup.attempt} of ${startup.max_attempts} · ` : ''}
              {seconds}s
            </p>
          </>
        ) : null}
        {hasError ? (
          <div className="mt-4 w-full rounded-xl border border-(--color-border) bg-(--bg-card) p-4 text-left shadow-sm">
            <p className="text-xs leading-5 text-(--color-text-muted)">
              {errorSummary || 'No additional error details were provided.'}
              {startup?.error && startup.error.length > 520 ? '…' : ''}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {onRetry ? (
                <button
                  type="button"
                  onClick={() => void onRetry()}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-(--color-accent) px-3 text-xs font-medium text-white transition-opacity hover:opacity-90"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Try again
                </button>
              ) : null}
              {onRevealLog ? (
                <button
                  type="button"
                  onClick={() => void onRevealLog()}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-(--color-border) px-3 text-xs font-medium text-(--color-text) hover:bg-(--bg-hover)"
                >
                  <FileText className="h-3.5 w-3.5" />
                  View backend log
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
      <style>{'@keyframes engineProgress { 0% { transform: translateX(-140%) } 50% { transform: translateX(80%) } 100% { transform: translateX(260%) } }'}</style>
    </div>
  )
}

export default App
