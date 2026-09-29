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
  const downloading = useAppUpdaterStore((state) => state.downloading)
  const ready = useAppUpdaterStore((state) => state.ready)
  const restarting = useAppUpdaterStore((state) => state.restarting)
  const progress = useAppUpdaterStore((state) => state.progress)
  const hidden = useAppUpdaterStore((state) => state.hidden)
  const error = useAppUpdaterStore((state) => state.error)
  const download = useAppUpdaterStore((state) => state.download)
  const restart = useAppUpdaterStore((state) => state.restart)
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

  // Only the install itself is uninterruptible — the app is seconds from
  // closing. A download can be put aside, and so can a finished one: it
  // installs when EvoFlux quits.
  const sealed = restarting

  return (
    <Dialog open={available !== null && !hidden} onOpenChange={(open) => !open && dismiss()}>
      <DialogContent showCloseButton={!sealed} className="sm:max-w-md">
        <DialogHeader>
          <div className="mb-1 flex size-9 items-center justify-center rounded-lg bg-(--color-accent-soft) text-(--color-accent)">
            <Download size={17} aria-hidden="true" />
          </div>
          <DialogTitle>
            {ready ? 'EvoFlux update ready to install' : 'EvoFlux update available'}
          </DialogTitle>
          <DialogDescription>
            {ready ? (
              <>
                EvoFlux {available?.version} is downloaded and verified. You currently have{' '}
                {available?.current_version}.
              </>
            ) : (
              <>
                EvoFlux {available?.version} is available. You currently have{' '}
                {available?.current_version}.
              </>
            )}
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

        {restarting ? (
          <UpdateProgress progress={{ phase: 'installing' }} />
        ) : downloading ? (
          <UpdateProgress progress={progress} />
        ) : ready ? (
          <p className="text-xs leading-5 text-(--color-text-muted)">
            The update is downloaded and verified. Restart now to install it, or keep working — it
            installs the next time you quit EvoFlux.
          </p>
        ) : (
          <p className="text-xs leading-5 text-(--color-text-muted)">
            EvoFlux downloads and verifies the signed update while you keep working. You choose when
            to restart.
          </p>
        )}

        {error ? (
          <p
            role="alert"
            className="rounded-lg bg-(--color-error)/10 px-3 py-2 text-xs leading-5 text-(--color-error)"
          >
            {error}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="outline" disabled={sealed} onClick={dismiss}>
            {dismissLabel({ downloading, ready })}
          </Button>
          {ready || restarting ? (
            <Button disabled={restarting} onClick={() => void restart()}>
              <RefreshCw
                className={restarting ? 'animate-spin' : undefined}
                size={14}
                aria-hidden="true"
              />
              {restarting ? 'Installing…' : 'Restart now'}
            </Button>
          ) : (
            <Button disabled={downloading} onClick={() => void download()}>
              {downloading ? (
                <RefreshCw className="animate-spin" size={14} aria-hidden="true" />
              ) : (
                <Download size={14} aria-hidden="true" />
              )}
              {downloading ? phaseLabel(progress) : 'Download update'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function dismissLabel({ downloading, ready }: { downloading: boolean; ready: boolean }): string {
  if (ready) return 'Install when I quit'
  if (downloading) return 'Continue in background'
  return 'Later'
}

/** What the button says while the download happens. */
function phaseLabel(progress: AppUpdateProgress | null): string {
  return progress?.phase === 'verifying' ? 'Verifying…' : 'Downloading…'
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
          ? 'EvoFlux closes to install the update and opens again when it is done.'
          : 'Signed update, verified before it is installed.'}
      </p>
    </div>
  )
}
