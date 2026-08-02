import { useEffect, useRef, useState } from 'react'
import EmbedPDF from '@embedpdf/snippet'
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'

import { workspaceMediaUrl } from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'

interface PdfPreviewProps {
  file: WorkspaceFileInfo
  sessionId?: string
  sourceUrl?: string
}

type PreviewStatus =
  | { state: 'loading'; error: null }
  | { state: 'ready'; error: null }
  | { state: 'error'; error: string }

/**
 * Full PDF reader backed by PDFium WebAssembly. The viewer stays inside the
 * application WebView and reads the permission-scoped workspace media URL;
 * it never launches a browser process or a server-side renderer.
 */
export function PdfPreview({ sessionId, sourceUrl: providedSourceUrl, file }: PdfPreviewProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [retryKey, setRetryKey] = useState(0)
  const [status, setStatus] = useState<PreviewStatus>({ state: 'loading', error: null })
  const sourceUrl = providedSourceUrl ?? (sessionId ? workspaceMediaUrl(sessionId, file.path) : '')

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    host.replaceChildren()
    if (!sourceUrl) {
      queueMicrotask(() => setStatus({ state: 'error', error: 'Missing PDF source URL.' }))
      return () => host.replaceChildren()
    }

    try {
      const viewer = EmbedPDF.init({
        type: 'container',
        target: host,
        src: sourceUrl,
        worker: true,
        theme: { preference: 'system' },
        tabBar: 'never',
        // EvoFlux is local-first: never fetch UI or fallback fonts from a CDN.
        // PDFs with embedded fonts retain their native typography; documents
        // that omit required font programs remain offline instead of leaking a
        // font request to a third-party service.
        fonts: { ui: null, signature: null },
        fontFallback: null,
        // This surface is a preview. Keep navigation/search/selection/print,
        // while removing document-mutating tools from the ready-made viewer.
        disabledCategories: ['annotation', 'redaction', 'signature', 'stamp'],
      })

      if (!viewer) throw new Error('The PDF viewer could not be initialized.')
      setStatus({ state: 'ready', error: null })

      return () => {
        viewer.remove()
        host.replaceChildren()
      }
    } catch (reason) {
      setStatus({
        state: 'error',
        error: reason instanceof Error ? reason.message : String(reason),
      })
      return () => host.replaceChildren()
    }
  }, [file.mtime, retryKey, sourceUrl])

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-(--bg-app)">
      <div ref={hostRef} className="h-full min-h-0 w-full" data-testid="pdf-preview-host" />

      {status.state === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center gap-2 bg-(--bg-app) text-(--color-text-subtle)">
          <Loader2 size={17} className="animate-spin" aria-hidden="true" />
          <span className="text-xs">Loading PDF…</span>
        </div>
      )}

      {status.state === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-(--bg-app) px-6 text-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-(--color-error)/10 text-(--color-error)">
            <AlertCircle size={18} aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-medium text-(--color-text)">PDF preview unavailable</p>
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
