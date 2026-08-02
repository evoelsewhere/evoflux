import { useEffect, useRef, useState } from 'react'
import * as GC from '@mescius/spread-sheets'
import '@mescius/spread-sheets-io'
import '@mescius/spread-sheets/styles/gc.spread.sheets.excel2016colorful.css'
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'

import { workspaceMediaUrl } from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'

interface XlsxPreviewProps {
  file: WorkspaceFileInfo
  sessionId?: string
  sourceUrl?: string
}

type PreviewStatus =
  | { state: 'loading'; error: null }
  | { state: 'ready'; error: null }
  | { state: 'error'; error: string }

function errorMessage(reason: unknown): string {
  if (reason instanceof Error) return reason.message
  if (typeof reason === 'string') return reason
  try {
    return JSON.stringify(reason)
  } catch {
    return 'The workbook could not be imported.'
  }
}

function makeWorkbookReadOnly(workbook: GC.Spread.Sheets.Workbook): void {
  workbook.options.allowUndo = false
  workbook.options.allowUserDragDrop = false
  workbook.options.allowUserDragFill = false
  workbook.options.allowUserEditFormula = false
  workbook.options.allowSheetReorder = false
  workbook.options.newTabVisible = false
  workbook.options.tabEditable = false

  workbook.bind(
    GC.Spread.Sheets.Events.EditStarting,
    (_sender: unknown, args: GC.Spread.Sheets.IEditStartingEventArgs) => {
      args.cancel = true
    },
  )

  for (let index = 0; index < workbook.getSheetCount(); index += 1) {
    const sheet = workbook.getSheet(index)
    if (!sheet) continue
    sheet.options.isProtected = true
    Object.assign(sheet.options.protectionOptions, {
      allowSelectLockedCells: true,
      allowSelectUnlockedCells: true,
      allowFilter: true,
      allowSort: true,
      allowOutlineColumns: true,
      allowOutlineRows: true,
      allowUsePivotTable: true,
    })
  }
}

/** Excel-compatible, read-only workbook preview rendered directly in WebView. */
export function XlsxPreview({ sessionId, sourceUrl: providedSourceUrl, file }: XlsxPreviewProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [retryKey, setRetryKey] = useState(0)
  const [status, setStatus] = useState<PreviewStatus>({ state: 'loading', error: null })
  const sourceUrl = providedSourceUrl ?? (sessionId ? workspaceMediaUrl(sessionId, file.path) : '')

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    const licenseKey = import.meta.env.VITE_SPREADJS_LICENSE_KEY?.trim()
    if (licenseKey) GC.Spread.Sheets.LicenseKey = licenseKey

    const controller = new AbortController()
    let disposed = false
    host.replaceChildren()

    const workbook = new GC.Spread.Sheets.Workbook(host, { sheetCount: 0 })
    const resizeObserver = new ResizeObserver(() => {
      workbook.invalidateLayout()
      workbook.repaint()
    })
    resizeObserver.observe(host)

    if (!sourceUrl) {
      queueMicrotask(() => {
        if (!disposed) setStatus({ state: 'error', error: 'Missing workbook source URL.' })
      })
      return () => {
        resizeObserver.disconnect()
        workbook.destroy()
        host.replaceChildren()
      }
    }

    void fetch(sourceUrl, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Workbook download failed (HTTP ${response.status}).`)
        const blob = await response.blob()
        if (disposed) return

        const source = new File([blob], file.name, {
          type: file.mime || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          lastModified: file.mtime * 1000,
        })
        await new Promise<void>((resolve, reject) => {
          workbook.import(source, resolve, reject, {
            fileType: GC.Spread.Sheets.FileType.excel,
          })
        })
      })
      .then(() => {
        if (disposed) return
        makeWorkbookReadOnly(workbook)
        workbook.invalidateLayout()
        workbook.repaint()
        setStatus({ state: 'ready', error: null })
      })
      .catch((reason: unknown) => {
        if (disposed || controller.signal.aborted) return
        setStatus({ state: 'error', error: errorMessage(reason) })
      })

    return () => {
      disposed = true
      controller.abort()
      resizeObserver.disconnect()
      workbook.destroy()
      host.replaceChildren()
    }
  }, [file.mime, file.mtime, file.name, retryKey, sourceUrl])

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-white">
      <div ref={hostRef} className="h-full min-h-0 w-full" data-testid="xlsx-preview-host" />

      {status.state === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center gap-2 bg-(--bg-app) text-(--color-text-subtle)">
          <Loader2 size={17} className="animate-spin" aria-hidden="true" />
          <span className="text-xs">Loading workbook…</span>
        </div>
      )}

      {status.state === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-(--bg-app) px-6 text-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-(--color-error)/10 text-(--color-error)">
            <AlertCircle size={18} aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-medium text-(--color-text)">Workbook preview unavailable</p>
            <p className="mt-1 max-w-sm text-xs leading-5 text-(--color-text-muted)">{status.error}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              setStatus({ state: 'loading', error: null })
              setRetryKey((value) => value + 1)
            }}
            className="flex items-center gap-1.5 rounded-md border border-(--color-border) px-3 py-1.5 text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key)"
          >
            <RefreshCw size={12} aria-hidden="true" />
            Try again
          </button>
        </div>
      )}
    </div>
  )
}
