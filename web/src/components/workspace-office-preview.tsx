/**
 * Live-preview renderers for .docx/.xlsx/.pptx workspace files.
 *
 * Each component fetches the file's raw bytes (native Tauri read when
 * available, HTTP media proxy otherwise — same dual path as
 * ``WorkspaceFilesPanel``'s ``TextPreview``) and hands them to a
 * format-specific renderer:
 *   - .docx  → docx-preview (renders into HTML/CSS matching Word layout)
 *   - .xlsx  → xlsx (SheetJS) parses; rendered as a plain React table so
 *              untrusted cell content never reaches innerHTML
 *   - .pptx  → @aiden0z/pptx-renderer's PptxViewer (list-mode, one slide
 *              per scroll position)
 *
 * All three load their (large) rendering libraries via dynamic import so
 * the main bundle doesn't pay for them until a matching file is opened.
 */

import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { workspaceMediaUrl } from '@/api/client'
import { isTauriAvailable, tauriReadWorkspaceFile } from '@/api/tauri-workspace'
import { formatBytes } from '@/utils/format'
import type { WorkspaceFileInfo } from '@/api/types'

// Office documents run a few hundred KB to a few MB routinely — much
// higher than the plain-text preview cap (512 KB) would allow. 20 MB is a
// generous ceiling for in-browser parsing without risking a UI freeze.
const MAX_OFFICE_PREVIEW_BYTES = 20 * 1024 * 1024

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

interface FileBytesState {
  data: ArrayBuffer | null
  loading: boolean
  error: string | null
  tooLarge: boolean
}

/** Fetches a workspace file's raw bytes — native Tauri read when available,
 *  HTTP media proxy otherwise. Shared by every office-format preview below. */
function useWorkspaceFileBytes(
  sessionId: string,
  file: WorkspaceFileInfo,
  workspaceRoot: string | null | undefined,
): FileBytesState {
  const tooLarge = file.size > MAX_OFFICE_PREVIEW_BYTES
  const [data, setData] = useState<ArrayBuffer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!tooLarge)

  useEffect(() => {
    if (tooLarge) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)

    async function load() {
      try {
        let buffer: ArrayBuffer
        if (isTauriAvailable() && workspaceRoot) {
          const b64 = await tauriReadWorkspaceFile(workspaceRoot, file.path)
          buffer = base64ToArrayBuffer(b64)
        } else {
          const res = await fetch(workspaceMediaUrl(sessionId, file.path))
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          buffer = await res.arrayBuffer()
        }
        if (!cancelled) {
          setData(buffer)
          setLoading(false)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setLoading(false)
        }
      }
    }
    void load()

    return () => {
      cancelled = true
    }
  }, [sessionId, file.path, file.size, tooLarge, workspaceRoot])

  return { data, loading, error, tooLarge }
}

function TooLargeNotice({ file }: { file: WorkspaceFileInfo }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      <p className="text-sm text-(--color-text-2)">File too large to preview</p>
      <p className="text-xs text-(--color-text-subtle)">
        {formatBytes(file.size)} — limit is {formatBytes(MAX_OFFICE_PREVIEW_BYTES)}
      </p>
    </div>
  )
}

function LoadingSpinner() {
  return (
    <div className="flex h-full items-center justify-center text-(--color-text-subtle)">
      <Loader2 size={16} className="animate-spin" />
    </div>
  )
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">
      Failed to load: {message}
    </div>
  )
}

// ── .docx ────────────────────────────────────────────────────────────────────

export function DocxPreview({
  sessionId,
  file,
  workspaceRoot,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  workspaceRoot?: string | null
}) {
  const { data, loading, error, tooLarge } = useWorkspaceFileBytes(sessionId, file, workspaceRoot)
  const containerRef = useRef<HTMLDivElement>(null)
  const [renderError, setRenderError] = useState<string | null>(null)

  useEffect(() => {
    if (!data || !containerRef.current) return
    let cancelled = false
    const container = containerRef.current

    import('docx-preview')
      .then(({ renderAsync }) =>
        renderAsync(data, container, undefined, {
          inWrapper: true,
          ignoreLastRenderedPageBreak: true,
          className: 'docx-preview',
        }),
      )
      .catch((e) => {
        if (!cancelled) setRenderError(e instanceof Error ? e.message : String(e))
      })

    return () => {
      cancelled = true
      container.innerHTML = ''
    }
  }, [data])

  if (tooLarge) return <TooLargeNotice file={file} />
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorNotice message={error} />
  if (renderError) return <ErrorNotice message={renderError} />

  return (
    <div className="h-full overflow-auto bg-(--bg-page) p-4">
      <div ref={containerRef} className="docx-preview-container mx-auto" />
    </div>
  )
}

// ── .xlsx ────────────────────────────────────────────────────────────────────

interface SheetGrid {
  name: string
  rows: string[][]
  merges: { r0: number; c0: number; r1: number; c1: number }[]
}

async function parseWorkbook(data: ArrayBuffer): Promise<SheetGrid[]> {
  const XLSX = await import('xlsx')
  const wb = XLSX.read(data, { type: 'array' })
  return wb.SheetNames.map((name) => {
    const ws = wb.Sheets[name]
    const rows = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1, defval: '', raw: false })
    const merges = (ws['!merges'] ?? []).map((m) => ({
      r0: m.s.r,
      c0: m.s.c,
      r1: m.e.r,
      c1: m.e.c,
    }))
    return { name, rows: rows.map((r) => r.map((c) => String(c ?? ''))), merges }
  })
}

/** Returns the set of {r,c} cells that are covered (but not anchored) by a
 *  merge — these must be skipped entirely when rendering, since the anchor
 *  cell's colSpan/rowSpan already accounts for them. */
function buildMergeSkip(merges: SheetGrid['merges']): Set<string> {
  const skip = new Set<string>()
  for (const m of merges) {
    for (let r = m.r0; r <= m.r1; r++) {
      for (let c = m.c0; c <= m.c1; c++) {
        if (r === m.r0 && c === m.c0) continue
        skip.add(`${r}:${c}`)
      }
    }
  }
  return skip
}

function SheetTable({ sheet }: { sheet: SheetGrid }) {
  const mergeSkip = buildMergeSkip(sheet.merges)
  const mergeAnchor = new Map(sheet.merges.map((m) => [`${m.r0}:${m.c0}`, m]))
  const colCount = Math.max(1, ...sheet.rows.map((r) => r.length))

  return (
    <table className="border-collapse font-mono text-xs">
      <tbody>
        {sheet.rows.map((row, r) => (
          <tr key={r}>
            {Array.from({ length: colCount }, (_, c) => {
              if (mergeSkip.has(`${r}:${c}`)) return null
              const anchor = mergeAnchor.get(`${r}:${c}`)
              const colSpan = anchor ? anchor.c1 - anchor.c0 + 1 : 1
              const rowSpan = anchor ? anchor.r1 - anchor.r0 + 1 : 1
              return (
                <td
                  key={c}
                  colSpan={colSpan > 1 ? colSpan : undefined}
                  rowSpan={rowSpan > 1 ? rowSpan : undefined}
                  className="min-w-16 border border-(--color-border) px-2 py-1 text-(--color-text) whitespace-pre"
                >
                  {row[c] ?? ''}
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function XlsxPreview({
  sessionId,
  file,
  workspaceRoot,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  workspaceRoot?: string | null
}) {
  const { data, loading, error, tooLarge } = useWorkspaceFileBytes(sessionId, file, workspaceRoot)
  const [sheets, setSheets] = useState<SheetGrid[] | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [activeSheet, setActiveSheet] = useState(0)

  useEffect(() => {
    if (!data) return
    let cancelled = false
    parseWorkbook(data)
      .then((result) => {
        if (!cancelled) {
          setSheets(result)
          setActiveSheet(0)
        }
      })
      .catch((e) => {
        if (!cancelled) setParseError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [data])

  if (tooLarge) return <TooLargeNotice file={file} />
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorNotice message={error} />
  if (parseError) return <ErrorNotice message={parseError} />
  if (!sheets) return <LoadingSpinner />

  const sheet = sheets[activeSheet]

  return (
    <div className="flex h-full flex-col">
      {sheets.length > 1 && (
        <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-(--color-border) bg-(--bg-page) px-2 py-1.5">
          {sheets.map((s, i) => (
            <button
              key={s.name}
              type="button"
              onClick={() => setActiveSheet(i)}
              className={cn(
                'shrink-0 rounded px-2 py-1 text-xs transition-colors',
                i === activeSheet
                  ? 'bg-(--bg-key) text-(--color-accent)'
                  : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
              )}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto bg-(--bg-page) p-2">
        {sheet ? <SheetTable sheet={sheet} /> : null}
      </div>
    </div>
  )
}

// ── .pptx ────────────────────────────────────────────────────────────────────

export function PptxPreview({
  sessionId,
  file,
  workspaceRoot,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  workspaceRoot?: string | null
}) {
  const { data, loading, error, tooLarge } = useWorkspaceFileBytes(sessionId, file, workspaceRoot)
  const containerRef = useRef<HTMLDivElement>(null)
  const [renderError, setRenderError] = useState<string | null>(null)

  useEffect(() => {
    if (!data || !containerRef.current) return
    let cancelled = false
    let viewer: import('@aiden0z/pptx-renderer').PptxViewer | null = null
    const container = containerRef.current

    import('@aiden0z/pptx-renderer')
      .then(({ PptxViewer }) =>
        PptxViewer.open(data, container, {
          fitMode: 'contain',
          renderMode: 'list',
          listOptions: { showSlideLabels: true },
        }),
      )
      .then((v) => {
        if (cancelled) {
          v.destroy()
          return
        }
        viewer = v
      })
      .catch((e) => {
        if (!cancelled) setRenderError(e instanceof Error ? e.message : String(e))
      })

    return () => {
      cancelled = true
      viewer?.destroy()
    }
  }, [data])

  if (tooLarge) return <TooLargeNotice file={file} />
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorNotice message={error} />
  if (renderError) return <ErrorNotice message={renderError} />

  return (
    <div className="h-full overflow-auto bg-(--bg-page) p-4">
      <div ref={containerRef} className="mx-auto flex flex-col items-center gap-4" />
    </div>
  )
}
