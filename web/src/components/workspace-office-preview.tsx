/**
 * High-fidelity Office previews.
 *
 * The backend uses the bundled OfficeCLI renderer to produce one consistent,
 * paginated HTML representation for DOCX, XLSX and PPTX. The result is loaded
 * into a script-sandboxed iframe with an in-document CSP, keeping document
 * content isolated from EvoFlux while preserving the renderer's pagination,
 * layout, charts, merged cells and slide geometry.
 */

import { useEffect, useState } from 'react'
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import { workspaceOfficePreviewUrl } from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'

interface OfficePreviewProps {
  sessionId: string
  file: WorkspaceFileInfo
}

function OfficePreview({ sessionId, file }: OfficePreviewProps) {
  const [html, setHtml] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setHtml(null)
    setError(null)

    void fetch(workspaceOfficePreviewUrl(sessionId, file.path), {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.ok) return response.text()
        let detail = `Preview failed (HTTP ${response.status})`
        try {
          const payload = await response.json() as { detail?: string }
          if (payload.detail) detail = payload.detail
        } catch {
          // Keep the status-based fallback message.
        }
        throw new Error(detail)
      })
      .then(setHtml)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setError(reason instanceof Error ? reason.message : String(reason))
      })

    return () => controller.abort()
  }, [file.path, file.size, file.mtime, retryKey, sessionId])

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-(--color-error)/10 text-(--color-error)">
          <AlertCircle size={18} aria-hidden="true" />
        </span>
        <div>
          <p className="text-sm font-medium text-(--color-text)">Preview unavailable</p>
          <p className="mt-1 max-w-sm text-xs leading-5 text-(--color-text-muted)">{error}</p>
        </div>
        <button
          type="button"
          onClick={() => setRetryKey((value) => value + 1)}
          className="flex items-center gap-1.5 rounded-md border border-(--color-border) px-3 py-1.5 text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key)"
        >
          <RefreshCw size={12} aria-hidden="true" />
          Try again
        </button>
      </div>
    )
  }

  if (!html) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-(--color-text-subtle)">
        <Loader2 size={17} className="animate-spin" aria-hidden="true" />
        <span className="text-xs">Rendering document…</span>
      </div>
    )
  }

  return (
    <iframe
      key={`${file.path}:${file.mtime}`}
      title={`Preview ${file.name}`}
      srcDoc={html}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      className="h-full min-h-0 w-full border-0 bg-[#f0f0f0]"
    />
  )
}

export function DocxPreview(props: OfficePreviewProps) {
  return <OfficePreview {...props} />
}

export function XlsxPreview(props: OfficePreviewProps) {
  return <OfficePreview {...props} />
}

export function PptxPreview(props: OfficePreviewProps) {
  return <OfficePreview {...props} />
}
