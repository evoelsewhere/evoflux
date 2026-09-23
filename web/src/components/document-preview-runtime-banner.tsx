import { useState } from 'react'
import { AlertCircle, Download, Loader2, RefreshCw, X } from 'lucide-react'

import type { OfficeRuntimeStatus } from '@/api/types'
import { STORAGE_KEYS } from '@/lib/storage-keys'

function megabytes(bytes: number): string {
  const value = bytes / (1024 * 1024)
  // One decimal below 10 MB so a slow start visibly moves instead of
  // reading "1 MB" from the first byte to the millionth.
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} MB`
}

function readHiddenVersion(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEYS.officeRuntimeOfferHidden)
  } catch {
    return null
  }
}

function writeHiddenVersion(version: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEYS.officeRuntimeOfferHidden, version)
  } catch {
    // Storage may be unavailable; the offer then only hides for this viewer.
  }
}

const PHASE_LABEL = {
  downloading: 'Downloading the exact renderer',
  verifying: 'Verifying the download',
  extracting: 'Installing the exact renderer',
} as const

const rowClass = 'flex shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-card) px-3 py-2 text-[11px]'
const buttonClass = 'flex shrink-0 items-center gap-1.5 rounded-md border border-(--color-border) px-2 py-1 text-(--color-text-2) hover:bg-(--bg-key) disabled:opacity-50'
const iconButtonClass = 'flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key)'

/**
 * Offers the optional LibreOffice runtime that renders Office files exactly
 * as laid out, reports its download, and says when an exact render is
 * pending or could not be produced. Nothing is fetched until the user asks;
 * without it the viewer keeps its built-in approximate renderers.
 */
export function DocumentPreviewRuntimeBanner({
  status,
  starting,
  requestError,
  rendering,
  fallback,
  onInstall,
  onCancel,
  onDismissError,
}: {
  status: OfficeRuntimeStatus | undefined
  starting: boolean
  /** A failed install/cancel request (e.g. the bundle was withdrawn). */
  requestError: Error | null
  /** The approximate pages are shown while the exact render runs. */
  rendering: boolean
  /** The exact renderer is installed but could not render this file. */
  fallback: boolean
  onInstall: () => void
  onCancel: () => void
  onDismissError: () => void
}) {
  const [hiddenVersion, setHiddenVersion] = useState(readHiddenVersion)
  const job = status?.job

  if (requestError || job?.phase === 'failed') {
    const message = job?.phase === 'failed' ? job.error : requestError?.message
    return (
      <div className={rowClass} role="alert">
        <AlertCircle size={13} className="shrink-0 text-(--color-danger)" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-(--color-text-2)" title={message ?? undefined}>
          Could not install the exact renderer: {message}
        </span>
        {status?.available && (
          <button type="button" onClick={onInstall} disabled={starting} className={buttonClass}>
            Retry
          </button>
        )}
        <button type="button" onClick={onDismissError} aria-label="Dismiss renderer error" className={iconButtonClass}>
          <X size={13} />
        </button>
      </div>
    )
  }

  if (job) {
    const percent = job.bytes_total > 0 ? Math.min(100, Math.round((job.bytes_done / job.bytes_total) * 100)) : 0
    const downloading = job.phase === 'downloading'
    return (
      <div className="shrink-0 border-b border-(--color-border) bg-(--bg-card) px-3 py-2" role="status" aria-live="polite">
        <div className="flex items-center gap-2 text-[11px] text-(--color-text-2)">
          <Loader2 size={12} className="animate-spin" aria-hidden="true" />
          <span>{PHASE_LABEL[job.phase]}</span>
          {downloading && (
            <span className="ml-auto tabular-nums text-(--color-text-muted)">
              {percent}% · {megabytes(job.bytes_done)} / {megabytes(job.bytes_total)}
            </span>
          )}
          {(downloading || job.phase === 'verifying') && (
            <button
              type="button"
              onClick={onCancel}
              className={`${buttonClass} ${downloading ? '' : 'ml-auto'}`}
            >
              Cancel
            </button>
          )}
        </div>
        <div
          className="mt-1.5 h-1 overflow-hidden rounded-full bg-(--bg-key)"
          role="progressbar"
          aria-label="Exact renderer download"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={downloading ? percent : 100}
        >
          <div
            className="h-full rounded-full bg-(--color-accent) transition-[width]"
            style={{ width: `${downloading ? percent : 100}%` }}
          />
        </div>
      </div>
    )
  }

  if (rendering) {
    return (
      <div className={rowClass} role="status" aria-live="polite">
        <Loader2 size={12} className="shrink-0 animate-spin" aria-hidden="true" />
        <span className="text-(--color-text-2)">
          Rendering exact pages… the first exact render can take up to a minute.
        </span>
      </div>
    )
  }

  const installed = status?.installed_version ?? null
  const offerVersion = status?.available ? status.version : null
  // An update outranks the fallback notice: the newer renderer may be the
  // one that can render this file.
  const offered = Boolean(offerVersion)
    && installed !== offerVersion
    && hiddenVersion !== offerVersion

  if (fallback && !offered) {
    return (
      <div className={rowClass} role="status">
        <AlertCircle size={13} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <span className="text-(--color-text-2)">
          The exact renderer could not render this file, so this preview is approximate.
        </span>
      </div>
    )
  }

  if (!status || !offered || !offerVersion) return null

  const hide = () => {
    writeHiddenVersion(status.version as string)
    setHiddenVersion(status.version)
  }

  return (
    <div className={rowClass}>
      <span className="min-w-0 flex-1 text-(--color-text-2)">
        {installed
          ? `A newer exact renderer (LibreOffice ${status.version}) is available.`
          : 'This preview is approximate. Install the LibreOffice renderer to see pages exactly as Office lays them out.'}
      </span>
      <button type="button" onClick={onInstall} disabled={starting} className={buttonClass}>
        {installed
          ? <><RefreshCw size={12} aria-hidden="true" /> Update renderer</>
          : <><Download size={12} aria-hidden="true" /> Install renderer</>}
      </button>
      <button type="button" onClick={hide} aria-label="Hide renderer suggestion" className={iconButtonClass}>
        <X size={13} />
      </button>
    </div>
  )
}
