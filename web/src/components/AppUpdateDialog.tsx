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
import type { AppUpdateCheckResult } from '@/lib/app-updater'
import { useAppUpdaterStore } from '@/stores/useAppUpdaterStore'

export function AppUpdateDialog() {
  const available = useAppUpdaterStore((state) => state.available)
  const installing = useAppUpdaterStore((state) => state.installing)
  const installError = useAppUpdaterStore((state) => state.installError)
  const install = useAppUpdaterStore((state) => state.install)
  const dismiss = useAppUpdaterStore((state) => state.dismiss)
  const handleResult = useAppUpdaterStore((state) => state.handleResult)

  useEffect(() => {
    let cleanup: (() => void) | undefined
    let cancelled = false

    void import('@tauri-apps/api/event')
      .then(async ({ listen }) => {
        const unlisten = await listen<AppUpdateCheckResult>('app-update-result', (event) => {
          handleResult(event.payload)
        })
        if (cancelled) unlisten()
        else cleanup = unlisten
      })
      .catch(() => {
        // Browser build: no Tauri event bus.
      })

    return () => {
      cancelled = true
      cleanup?.()
    }
  }, [handleResult])

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

        <p className="text-xs leading-5 text-(--color-text-muted)">
          EvoFlux will download and verify the signed update, then restart to finish installation.
        </p>

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
            {installing ? 'Installing…' : 'Install and restart'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
