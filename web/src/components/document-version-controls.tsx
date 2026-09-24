/**
 * Undo / redo / version history for a workspace document, in the viewer
 * header. Every save of the file is a version (see
 * app/services/document_versions.py); stepping or restoring writes that
 * version back to the workspace, and the open preview re-renders from it.
 */
import { useEffect, useRef, useState } from 'react'
import { History, Loader2, Redo2, Undo2 } from 'lucide-react'

import type { DocumentVersion } from '@/api/client'
import { cn } from '@/lib/utils'
import { useDocumentVersionMutation, useDocumentVersionsQuery } from '@/queries/useDocumentVersionsQuery'

function versionTitle(version: DocumentVersion, index: number): string {
  if (version.label) return version.label
  if (version.source === 'baseline' || index === 0) return 'Original'
  return `Version ${index + 1}`
}

// Kept local: the viewer is lazy-loaded and stays free of the i18n bundle.
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatWhen(seconds: number): string {
  const date = new Date(seconds * 1000)
  const sameDay = date.toDateString() === new Date().toDateString()
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export interface DocumentVersionControlsProps {
  sessionId: string
  path: string
  /** The file's mtime: every save refreshes the history. */
  revision: number
  buttonClassName: string
}

export function DocumentVersionControls({ sessionId, path, revision, buttonClassName }: DocumentVersionControlsProps) {
  const history = useDocumentVersionsQuery(sessionId, path, revision)
  const change = useDocumentVersionMutation(sessionId, path)
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const data = history.data
  const busy = change.isPending
  const versions = data?.versions ?? []

  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  return (
    <div className="relative flex items-center gap-0.5" ref={menuRef} role="group" aria-label="Document versions">
      <button
        type="button"
        onClick={() => change.mutate({ action: 'undo' })}
        disabled={!data?.can_undo || busy}
        aria-label="Undo last change to this file"
        title="Undo last change"
        className={buttonClassName}
      >
        <Undo2 size={14} />
      </button>
      <button
        type="button"
        onClick={() => change.mutate({ action: 'redo' })}
        disabled={!data?.can_redo || busy}
        aria-label="Redo change to this file"
        title="Redo"
        className={buttonClassName}
      >
        <Redo2 size={14} />
      </button>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={versions.length === 0}
        aria-label="Version history"
        aria-expanded={open}
        title="Version history"
        className={cn(buttonClassName, open && 'bg-(--bg-key) text-(--color-text)')}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <History size={14} />}
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Versions of this file"
          className="absolute top-8 right-0 z-(--z-overlay) w-72 overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-card) shadow-lg"
        >
          <div className="border-b border-(--color-border) px-3 py-2 text-[11px] font-medium text-(--color-text-muted)">
            {versions.length} version{versions.length === 1 ? '' : 's'} · restoring keeps later ones until the next edit
          </div>
          <ol className="max-h-72 overflow-y-auto py-1">
            {versions.map((version, index) => ({ version, index })).reverse().map(({ version, index }) => {
              const current = version.id === data?.head
              return (
                <li key={version.id}>
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={current}
                    disabled={current || busy}
                    onClick={() => {
                      change.mutate({ action: 'restore', version_id: version.id })
                      setOpen(false)
                    }}
                    className={cn(
                      'flex w-full items-start gap-2 px-3 py-1.5 text-left text-xs transition-colors hover:bg-(--bg-key) disabled:cursor-default',
                      current && 'bg-(--color-accent)/8',
                    )}
                  >
                    <span className={cn(
                      'mt-1 size-2 shrink-0 rounded-full border border-(--color-text-muted)',
                      current && 'border-(--color-accent) bg-(--color-accent)',
                    )}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-(--color-text)">{versionTitle(version, index)}</span>
                      <span className="block text-[10px] text-(--color-text-subtle)">
                        {formatWhen(version.created_at)} · {formatSize(version.size)}{current ? ' · current' : ''}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>
        </div>
      )}
      {change.error && (
        <span role="alert" className="sr-only">{change.error.message}</span>
      )}
    </div>
  )
}
