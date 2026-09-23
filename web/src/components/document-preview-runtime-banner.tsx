import { useState } from 'react'
import { AlertCircle, Download, Loader2, X } from 'lucide-react'

import type { OfficeRuntimeStatus } from '@/api/types'

function megabytes(bytes: number): string {
  return `${Math.max(1, Math.round(bytes / (1024 * 1024)))} MB`
}

const PHASE_LABEL = {
  downloading: 'Downloading the exact renderer',
  verifying: 'Verifying the download',
  extracting: 'Installing the exact renderer',
} as const

/**
 * Offers the optional LibreOffice runtime that renders Office files exactly
 * as laid out, and reports its download. Nothing is fetched until the user
 * asks; without it the viewer keeps its built-in approximate renderers.
 */
export function DocumentPreviewRuntimeBanner({
  status,
  starting,
  onInstall,
  onDismissError,
}: {
  status: OfficeRuntimeStatus | undefined
  starting: boolean
  onInstall: () => void
  onDismissError: () => void
}) {
  const [hidden, setHidden] = useState(false)
  if (!status?.available) return null
  const job = status.job

  if (job && job.phase !== 'failed') {
    const percent = job.bytes_total > 0 ? Math.min(100, Math.round((job.bytes_done / job.bytes_total) * 100)) : 0
    return (
      <div className="shrink-0 border-b border-(--color-border) bg-(--bg-card) px-3 py-2" role="status" aria-live="polite">
        <div className="flex items-center gap-2 text-[11px] text-(--color-text-2)">
          <Loader2 size={12} className="animate-spin" aria-hidden="true" />
          <span>{PHASE_LABEL[job.phase]}</span>
          {job.phase === 'downloading' && (
            <span className="ml-auto tabular-nums text-(--color-text-muted)">
              {percent}% · {megabytes(job.bytes_done)} / {megabytes(job.bytes_total)}
            </span>
          )}
        </div>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-(--bg-key)">
          <div
            className="h-full rounded-full bg-(--color-accent) transition-[width]"
            style={{ width: `${job.phase === 'downloading' ? percent : 100}%` }}
          />
        </div>
      </div>
    )
  }

  if (job?.phase === 'failed') {
    return (
      <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-card) px-3 py-2 text-[11px]" role="alert">
        <AlertCircle size={13} className="shrink-0 text-(--color-danger)" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-(--color-text-2)" title={job.error ?? undefined}>
          Could not install the exact renderer: {job.error}
        </span>
        <button
          type="button"
          onClick={onInstall}
          disabled={starting}
          className="shrink-0 rounded-md border border-(--color-border) px-2 py-1 text-(--color-text-2) hover:bg-(--bg-key) disabled:opacity-50"
        >
          Retry
        </button>
        <button
          type="button"
          onClick={onDismissError}
          aria-label="Dismiss renderer error"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key)"
        >
          <X size={13} />
        </button>
      </div>
    )
  }

  if (status.installed_version || hidden) return null

  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-card) px-3 py-2 text-[11px]">
      <span className="min-w-0 flex-1 text-(--color-text-2)">
        This preview is approximate. Install the LibreOffice renderer
        {status.download_bytes ? ` (${megabytes(status.download_bytes)} download)` : ''} to see
        pages exactly as Office lays them out.
      </span>
      <button
        type="button"
        onClick={onInstall}
        disabled={starting}
        className="flex shrink-0 items-center gap-1.5 rounded-md border border-(--color-border) px-2 py-1 text-(--color-text-2) hover:bg-(--bg-key) disabled:opacity-50"
      >
        <Download size={12} aria-hidden="true" /> Install renderer
      </button>
      <button
        type="button"
        onClick={() => setHidden(true)}
        aria-label="Hide renderer suggestion"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key)"
      >
        <X size={13} />
      </button>
    </div>
  )
}
