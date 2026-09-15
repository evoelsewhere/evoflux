import { Download, RefreshCw } from 'lucide-react'
import { useEffect } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { AppUpdateCheckResult, AppUpdateProgress } from '@/lib/app-updater'
import { cn } from '@/lib/utils'
import { useAppUpdaterStore } from '@/stores/useAppUpdaterStore'

export function AppUpdateDialog() {
  const available = useAppUpdaterStore((state) => state.available)
  const installing = useAppUpdaterStore((state) => state.installing)
  const progress = useAppUpdaterStore((state) => state.progress)
  const installError = useAppUpdaterStore((state) => state.installError)
  const install = useAppUpdaterStore((state) => state.install)
  const dismiss = useAppUpdaterStore((state) => state.dismiss)
  const handleResult = useAppUpdaterStore((state) => state.handleResult)
  const handleProgress = useAppUpdaterStore((state) => state.handleProgress)

  useEffect(() => {
    const unlisteners: Array<() => void> = []
    let cancelled = false

    const attach = (unlisten: () => void) => {
      if (cancelled) unlisten()
      else unlisteners.push(unlisten)
    }

    void import('@tauri-apps/api/event')
      .then(async ({ listen }) => {
        attach(
          await listen<AppUpdateCheckResult>('app-update-result', (event) => {
            handleResult(event.payload)
          }),
        )
        attach(
          await listen<AppUpdateProgress>('app-update-progress', (event) => {
            handleProgress(event.payload)
          }),
        )
      })
      .catch(() => {
        // Browser build: no Tauri event bus.
      })

    return () => {
      cancelled = true
      for (const unlisten of unlisteners) unlisten()
    }
  }, [handleProgress, handleResult])

  return (
    <Dialog open={available !== null} onOpenChange={(open) => !open && dismiss()}>
      <DialogContent showCloseButton={!installing} className="sm:max-w-md">
        <DialogHeader>
          <div className="mb-1 flex size-9 items-center justify-center rounded-lg bg-(--color-accent-soft) text-(--color-accent)">
            <Download size={17} aria-hidden="true" />
          </div>
          <DialogTitle>EvoFlux update available</DialogTitle>
          <DialogDescription>
            EvoFlux {available?.version} is available. You currently have{' '}
            {available?.current_version}.
          </DialogDescription>
        </DialogHeader>

        {available?.notes ? (
          <div className="max-h-52 overflow-y-auto rounded-lg border border-(--color-border) bg-(--bg-key)/50 p-3">
            <p className="mb-1 text-xs font-medium text-(--color-text)">What&apos;s new</p>
            <p className="whitespace-pre-wrap text-xs leading-5 text-(--color-text-muted)">
              {available.notes}
            </p>
          </div>
        ) : null}

        {installing ? (
          <UpdateProgress progress={progress} />
        ) : (
          <p className="text-xs leading-5 text-(--color-text-muted)">
            EvoFlux will download and verify the signed update, then restart to finish installation.
          </p>
        )}

        {installError ? (
          <p
            role="alert"
            className="rounded-lg bg-(--color-error)/10 px-3 py-2 text-xs leading-5 text-(--color-error)"
          >
            {installError}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="outline" disabled={installing} onClick={dismiss}>
            Later
          </Button>
          <Button disabled={installing} onClick={() => void install()}>
            {installing ? (
              <RefreshCw className="animate-spin" size={14} aria-hidden="true" />
            ) : (
              <Download size={14} aria-hidden="true" />
            )}
            {installing ? phaseLabel(progress) : 'Install and restart'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** What the button says while the work happens. */
function phaseLabel(progress: AppUpdateProgress | null): string {
  switch (progress?.phase) {
    case 'verifying':
      return 'Verifying…'
    case 'installing':
      return 'Installing…'
    default:
      return 'Downloading…'
  }
}

function megabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1)
}

/**
 * The bar the dialog was missing.
 *
 * An update is three stages of very different lengths — minutes of download,
 * a moment of verification, then an install that ends in a restart — and the
 * dialog reported all of it as one spinner labelled "Installing…". A window
 * that says the same thing for four minutes is indistinguishable from one
 * that has hung, which is the state the user was looking at.
 */
function UpdateProgress({ progress }: { progress: AppUpdateProgress | null }) {
  const downloading = progress?.phase === 'downloading' || progress == null
  const total = progress?.phase === 'downloading' ? progress.total : null
  const downloaded = progress?.phase === 'downloading' ? progress.downloaded : 0
  // Without a Content-Length there is no percentage to show honestly, so the
  // bar keeps moving on its own and the text says how much has arrived.
  const percent = total && total > 0 ? Math.min(100, Math.round((downloaded / total) * 100)) : null

  const label = progress?.phase === 'verifying'
    ? 'Verifying the signature…'
    : progress?.phase === 'installing'
      ? 'Installing — EvoFlux will restart'
      : total
        ? `Downloading ${megabytes(downloaded)} of ${megabytes(total)} MB`
        : downloaded > 0
          ? `Downloading ${megabytes(downloaded)} MB`
          : 'Starting download…'

  const determinate = downloading && percent !== null

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-(--color-text)">{label}</span>
        {determinate ? (
          <span className="font-mono text-xs tabular-nums text-(--color-text-muted)">
            {percent}%
          </span>
        ) : null}
      </div>
      <div
        role="progressbar"
        aria-label="Update progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={determinate ? (percent as number) : undefined}
        aria-valuetext={determinate ? `${percent}%` : label}
        className="h-1.5 w-full overflow-hidden rounded-full bg-(--bg-key)"
      >
        <div
          className={cn(
            'h-full rounded-full bg-(--color-accent)',
            determinate
              ? 'transition-[width] duration-300 ease-out'
              : 'w-1/3 animate-[progress-sweep_1.2s_ease-in-out_infinite]',
          )}
          style={determinate ? { width: `${percent}%` } : undefined}
        />
      </div>
      <p className="text-[11px] leading-4 text-(--color-text-subtle)">
        {progress?.phase === 'installing'
          ? 'Do not close EvoFlux — it restarts on its own.'
          : 'Signed update, verified before it is installed.'}
      </p>
    </div>
  )
}
