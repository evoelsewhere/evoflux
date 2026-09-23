import { Suspense } from 'react'
import { RouterProvider } from '@tanstack/react-router'
import { FileText, RotateCcw } from 'lucide-react'
import { useAppBackendBootstrap } from './hooks/use-app-backend-bootstrap'
import { router } from './router'
import { AppMotionConfig } from '@/components/motion/AppMotionConfig'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { useLocale } from '@/i18n'
import { WebBridgeAppearanceSync } from '@/components/WebBridgeAppearanceSync'

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
          <WebBridgeAppearanceSync />
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
  const errorSummary = startup?.error
    ?.replace(ANSI_SGR_PATTERN, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 520)

  if (!hasError) {
    return (
      <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col items-center justify-center bg-(--bg-page) px-6" role="status" aria-label="Loading EvoFlux">
        <div className="relative flex items-center justify-center">
          <div className="absolute h-20 w-20 animate-[splashGlow_2s_ease-in-out_infinite] rounded-3xl bg-(--color-accent) opacity-20 blur-xl motion-reduce:animate-none" />
          <img src={EvoFluxLogo} width={52} height={52} className="relative rounded-2xl" alt="" aria-hidden="true" />
        </div>
        <p className="mt-5 text-sm font-semibold tracking-wide text-(--color-text)">EvoFlux</p>
        <div className="mt-3 flex items-center gap-1.5" aria-hidden="true">
          {[0, 1, 2].map((index) => (
            <span
              key={index}
              className="h-1.5 w-1.5 rounded-full bg-(--color-text-muted) animate-[splashDot_1.2s_ease-in-out_infinite] motion-reduce:animate-none"
              style={{ animationDelay: `${index * 0.16}s` }}
            />
          ))}
        </div>
        <style>{'@keyframes splashGlow { 0%, 100% { opacity: 0.15; transform: scale(1) } 50% { opacity: 0.3; transform: scale(1.12) } } @keyframes splashDot { 0%, 80%, 100% { opacity: 0.25; transform: scale(0.8) } 40% { opacity: 1; transform: scale(1) } }'}</style>
      </div>
    )
  }

  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col items-center justify-center bg-(--bg-page) px-6" role="alert">
      <img src={EvoFluxLogo} width={52} height={52} className="rounded-2xl" alt="" aria-hidden="true" />
      <div className="mt-5 flex w-full max-w-md flex-col items-center text-center">
        <p className="text-sm font-medium text-(--color-text)">EvoFlux couldn't start</p>
        <p className="mt-1 text-xs text-(--color-text-muted)">Something went wrong while opening EvoFlux. Please try again.</p>
        <div className="mt-4 w-full rounded-xl border border-(--color-border) bg-(--bg-card) p-4 text-left shadow-sm">
          <details className="text-xs text-(--color-text-muted)">
            <summary className="cursor-pointer select-none font-medium text-(--color-text)">Details</summary>
            <p className="mt-2 leading-5 break-words">
              {errorSummary || 'No additional error details were provided.'}
              {startup?.error && startup.error.length > 520 ? '…' : ''}
            </p>
          </details>
          <div className="mt-4 flex flex-wrap gap-2">
            {onRetry ? (
              <button
                type="button"
                onClick={() => void onRetry()}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-(--color-accent) px-3 text-xs font-medium text-(--color-text-on-accent) transition-opacity hover:opacity-90"
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
                View log
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
