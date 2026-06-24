import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Check, Copy, Download, ExternalLink, FileText, GitCompare, Loader2, Pencil, X } from 'lucide-react'
import Editor, { useMonaco } from '@monaco-editor/react'
import { codingWorkspaceFileUrl, getCodingWorkspaceGitDiff } from '@/api/client'
import { downloadCodingWorkspaceFile } from '@/lib/coding-workspace-download'
import { cn } from '@/lib/utils'
import { formatBytes } from '@/utils/format'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { useMonacoTheme, languageForExt } from '@/hooks/useMonacoTheme'
import { queryKeys } from '@/queries'
import type { WorkspaceFileInfo } from '@/api/types'

const TEXT_EXTENSIONS = new Set([
  'txt', 'md', 'markdown', 'rst',
  'json', 'jsonl', 'yaml', 'yml', 'toml', 'ini', 'env', 'gitignore',
  'csv', 'tsv', 'log',
  'py', 'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs',
  'html', 'css', 'scss', 'sass',
  'sh', 'bash', 'zsh', 'fish',
  'rs', 'go', 'java', 'kt', 'c', 'cpp', 'h', 'hpp', 'rb', 'php', 'swift',
  'sql', 'xml', 'svg',
])
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'])
const DRAWIO_EXTENSIONS = new Set(['drawio', 'dio'])
const MAX_TEXT_PREVIEW_BYTES = 512 * 1024
// Viewer URL length limit — diagrams above ~400KB XML fall back to text
const MAX_DRAWIO_VIEWER_BYTES = 400 * 1024

function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

type FileKind = 'image' | 'text' | 'drawio' | 'binary'

function kindOf(file: WorkspaceFileInfo): FileKind {
  const ext = extOf(file.name)
  if (IMAGE_EXTENSIONS.has(ext) || file.mime.startsWith('image/')) return 'image'
  if (DRAWIO_EXTENSIONS.has(ext)) return 'drawio'
  if (!ext || TEXT_EXTENSIONS.has(ext) || file.mime.startsWith('text/') || file.mime === 'application/json') return 'text'
  return 'binary'
}

function CopyButton({ workspace, file }: { workspace: string; file: WorkspaceFileInfo }) {
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const tooLarge = file.size > MAX_TEXT_PREVIEW_BYTES

  const handleCopy = async () => {
    if (busy || tooLarge) return
    setBusy(true)
    try {
      const res = await fetch(codingWorkspaceFileUrl(workspace, file.path))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await navigator.clipboard.writeText(await res.text())
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Best-effort copy. The user can still download/open the file.
    } finally {
      setBusy(false)
    }
  }

  const label = tooLarge ? 'File too large to copy' : copied ? 'Copied!' : 'Copy file contents'
  return (
    <button
      type="button"
      onClick={handleCopy}
      disabled={busy || tooLarge}
      title={label}
      aria-label={label}
      className="flex h-9 min-w-9 items-center justify-center gap-1 rounded px-2 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) disabled:cursor-not-allowed disabled:opacity-40 md:h-auto md:min-w-0 md:py-1"
    >
      {copied ? <Check size={12} className="text-(--color-success)" /> : busy ? <Loader2 size={12} className="animate-spin" /> : <Copy size={12} />}
    </button>
  )
}

function TextPreview({
  workspace,
  file,
  onAddComment,
  editing = false,
  onContentChange,
}: {
  workspace: string
  file: WorkspaceFileInfo
  onAddComment?: (path: string, startLine: number, endLine: number) => void
  editing?: boolean
  onContentChange?: (content: string) => void
}) {
  const tooLarge = file.size > MAX_TEXT_PREVIEW_BYTES
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!tooLarge)
  const editorRef = useRef<Parameters<NonNullable<Parameters<typeof Editor>[0]['onMount']>>[0] | null>(null)

  const monaco = useMonaco()
  const theme = useMonacoTheme(monaco)

  useEffect(() => {
    if (tooLarge) return
    let cancelled = false
    fetch(codingWorkspaceFileUrl(workspace, file.path))
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.text()
      })
      .then((text) => {
        if (!cancelled) {
          setContent(text)
          setLoading(false)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [workspace, file.path, tooLarge])

  const handleEditorMount = useCallback((editor: Parameters<NonNullable<Parameters<typeof Editor>[0]['onMount']>>[0]) => {
    editorRef.current = editor

    // Wire up line selection for "Add comment" when not editing
    if (!editing && onAddComment) {
      editor.onDidChangeCursorSelection((e) => {
        const sel = e.selection
        if (sel.startLineNumber > 0) {
          onAddComment(file.path, sel.startLineNumber, sel.endLineNumber)
        }
      })
    }
  }, [editing, onAddComment, file.path])

  const handleChange = useCallback((value: string | undefined) => {
    if (value !== undefined) onContentChange?.(value)
  }, [onContentChange])

  if (tooLarge) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <FileText size={24} className="text-(--color-text-subtle)" />
        <p className="text-sm text-(--color-text-2)">File too large to preview</p>
        <p className="text-xs text-(--color-text-subtle)">{formatBytes(file.size)} — limit is {formatBytes(MAX_TEXT_PREVIEW_BYTES)}</p>
      </div>
    )
  }
  if (loading) return <div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>
  if (error) return <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">Failed to load: {error}</div>
  if (content === null) return null

  const ext = extOf(file.name)
  const language = languageForExt(ext)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Editor
        theme={theme}
        language={language}
        value={content}
        onMount={handleEditorMount}
        onChange={editing ? handleChange : undefined}
        loading={<div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>}
        options={{
          readOnly: !editing,
          domReadOnly: !editing,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 12,
          lineHeight: 20,
          fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
          renderLineHighlight: editing ? 'line' : 'none',
          lineNumbers: 'on',
          glyphMargin: false,
          folding: true,
          wordWrap: 'on',
          contextmenu: editing,
          scrollbar: {
            verticalScrollbarSize: 8,
            horizontalScrollbarSize: 8,
            useShadows: false,
          },
          overviewRulerLanes: 0,
          hideCursorInOverviewRuler: true,
          overviewRulerBorder: false,
          padding: { top: 8, bottom: 8 },
          automaticLayout: true,
        }}
      />
    </div>
  )
}

function ImagePreview({ workspace, file }: { workspace: string; file: WorkspaceFileInfo }) {
  const url = codingWorkspaceFileUrl(workspace, file.path)
  return (
    <div className="flex h-full min-h-0 items-center justify-center overflow-auto bg-(--bg-page) p-4">
      <img src={url} alt={file.name} className="block max-h-full max-w-full rounded border border-(--color-border) object-contain" />
    </div>
  )
}

function DrawioPreview({ workspace, file }: { workspace: string; file: WorkspaceFileInfo }) {
  const [xmlContent, setXmlContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch(codingWorkspaceFileUrl(workspace, file.path))
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.text()
      })
      .then((xml) => {
        if (!cancelled) { setXmlContent(xml); setLoading(false) }
      })
      .catch((e) => {
        if (!cancelled) { setError(e instanceof Error ? e.message : String(e)); setLoading(false) }
      })
    return () => { cancelled = true }
  }, [workspace, file.path])

  if (loading) return <div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>
  if (error) return <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">Failed to load: {error}</div>
  if (!xmlContent) return null

  // Large diagrams fall back to a text/XML view
  if (new Blob([xmlContent]).size > MAX_DRAWIO_VIEWER_BYTES) {
    const lines = xmlContent.split('\n')
    return (
      <div className="min-h-0 flex-1 overflow-auto font-mono text-xs leading-relaxed">
        {lines.map((line, i) => (
          <div key={i} className="flex items-start gap-3 whitespace-pre-wrap break-words px-3 text-(--color-text-2)">
            <span className="inline-block w-8 shrink-0 select-none text-right tabular-nums text-(--color-text-subtle)">{i + 1}</span>
            <span className="min-w-0 flex-1">{line || ' '}</span>
          </div>
        ))}
      </div>
    )
  }

  const encoded = btoa(unescape(encodeURIComponent(xmlContent)))
  const iframeSrc = `https://viewer.diagrams.net/?lightbox=0&toolbar=0&nav=1&xml=${encodeURIComponent(encoded)}`

  return (
    <div className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <iframe
        src={iframeSrc}
        title={file.name}
        className="h-full w-full border-0"
        sandbox="allow-scripts allow-same-origin allow-popups"
      />
    </div>
  )
}

function BinaryPreview({ workspace, file }: { workspace: string; file: WorkspaceFileInfo }) {
  const url = codingWorkspaceFileUrl(workspace, file.path)
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <FileText size={28} className="text-(--color-text-subtle)" />
      <div>
        <p className="text-sm text-(--color-text-2)">No inline preview for this file type</p>
        <p className="mt-0.5 text-xs text-(--color-text-subtle)">{file.mime} · {formatBytes(file.size)}</p>
      </div>
      <div className="flex items-center gap-2">
        <a href={url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 rounded-md bg-(--bg-key) px-3 py-1.5 text-xs text-(--color-accent) transition-colors hover:bg-(--bg-key)">
          <ExternalLink size={12} /> Open in new tab
        </a>
        <button type="button" onClick={() => void downloadCodingWorkspaceFile(workspace, file)} className="flex items-center gap-1.5 rounded-md border border-(--color-border) px-3 py-1.5 text-xs text-(--color-text-2) transition-colors hover:border-(--color-border-strong)">
          <Download size={12} /> Download
        </button>
      </div>
    </div>
  )
}

function diffLineClass(line: string) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-(--color-accent)'
  if (line.startsWith('@@')) return 'bg-(--color-accent)/10 text-(--color-accent)'
  if (line.startsWith('+')) return 'bg-(--color-diff-add-bg) text-(--color-diff-add-text)'
  if (line.startsWith('-')) return 'bg-(--color-diff-del-bg) text-(--color-diff-del-text)'
  if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('new file mode')) return 'text-(--color-text)'
  return 'text-(--color-text-2)'
}

function DiffPreview({ diff }: { diff: string }) {
  return (
    <pre className="h-full overflow-auto bg-(--bg-page) p-3 font-mono text-[11px] leading-relaxed">
      {diff.split('\n').map((line, index) => (
        <span key={index} className={cn('block whitespace-pre-wrap break-all px-1', diffLineClass(line))}>{line || ' '}</span>
      ))}
    </pre>
  )
}

export function CodingFileViewerPanel({
  workspace,
  file,
  onClose,
  onAddComment,
  mobile = false,
}: {
  workspace: string
  file: WorkspaceFileInfo | null
  onClose: () => void
  onAddComment?: (path: string, startLine: number, endLine: number) => void
  mobile?: boolean
}) {
  const prefersReducedMotion = useReducedMotion()
  const resizable = useResizableWidth({
    storageKey: 'oa.codingFileViewer.width',
    defaultWidth: 560,
    minWidth: 420,
    maxWidth: Math.min(880, Math.max(420, Math.floor((typeof window === 'undefined' ? 880 : window.innerWidth) - 320))),
    edge: 'left',
    disabled: mobile,
  })
  const [viewMode, setViewMode] = useState<'file' | 'diff'>('file')
  const [editing, setEditing] = useState(false)
  const scopedDiff = useQuery({
    queryKey: [...queryKeys.coding.diff(workspace), file?.path ?? null] as const,
    queryFn: () => getCodingWorkspaceGitDiff(workspace, file ? [file.path] : []),
    enabled: file !== null && viewMode === 'diff',
    staleTime: 5_000,
  })
  if (!file) return null

  const kind = kindOf(file)

  return (
    <motion.aside
      initial={prefersReducedMotion ? { opacity: 0 } : mobile ? { opacity: 0 } : { width: 0 }}
      animate={prefersReducedMotion ? { opacity: 1 } : mobile ? { opacity: 1 } : { width: resizable.width }}
      exit={prefersReducedMotion ? { opacity: 0 } : mobile ? { opacity: 0 } : { width: 0 }}
      transition={{ duration: prefersReducedMotion ? 0.01 : 0.22, ease: [0.4, 0, 0.2, 1] }}
      className={cn(
        'fixed bottom-0 right-0 z-40 min-h-0 w-full overflow-hidden border-l border-(--color-border) bg-(--bg-card) shadow-xl md:relative md:inset-y-auto md:right-auto md:z-auto md:w-auto md:shrink-0 md:shadow-none',
        mobile ? 'mobile-safe-top max-w-none' : '',
      )}
      aria-label="File viewer"
    >
      <div className={cn('relative flex h-full min-h-0 w-full flex-col', mobile ? 'max-w-none' : 'md:w-full')}>
        {!mobile && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize file viewer"
            title="Drag to resize · double-click to reset"
            className="absolute left-0 top-0 z-20 h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
            onPointerDown={resizable.startResize}
            onDoubleClick={resizable.resetWidth}
          />
        )}
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-3 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-(--color-text-subtle)">File</p>
            <p className="mt-1 truncate font-mono text-xs text-(--color-text)" title={file.path}>{file.path}</p>
            <p className="mt-0.5 text-[10px] text-(--color-text-subtle)">{formatBytes(file.size)} · {file.mime}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <div className="mr-1 flex rounded-md border border-(--color-border) p-0.5">
              <button type="button" onClick={() => { setViewMode('file'); setEditing(false) }} className={cn('h-8 rounded px-2 text-[11px] md:h-auto md:py-1', viewMode === 'file' && !editing ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}>
                File
              </button>
              {kind === 'text' && (
                <button type="button" onClick={() => { setViewMode('file'); setEditing(true) }} className={cn('flex h-8 items-center gap-1 rounded px-2 text-[11px] md:h-auto md:py-1', editing ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}>
                  <Pencil size={11} /> Edit
                </button>
              )}
              <button type="button" onClick={() => { setViewMode('diff'); setEditing(false) }} className={cn('flex h-8 items-center gap-1 rounded px-2 text-[11px] md:h-auto md:py-1', viewMode === 'diff' ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}>
                <GitCompare size={11} /> Diff
              </button>
            </div>
            <button type="button" onClick={() => void downloadCodingWorkspaceFile(workspace, file)} title="Download" className="flex h-9 w-9 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) md:h-auto md:w-auto md:p-1.5">
              <Download size={14} />
            </button>
            {(kind === 'text' || kind === 'drawio') && <CopyButton workspace={workspace} file={file} />}
            <button type="button" onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) md:h-auto md:w-auto md:p-1.5" aria-label="Close file viewer">
              <X size={16} />
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-hidden">
          {viewMode === 'diff' ? (
            scopedDiff.isLoading ? <div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>
              : scopedDiff.isError ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">Failed to load diff</div>
                : !scopedDiff.data?.is_git_repo ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-text-subtle)">Not a git repository</div>
                  : !scopedDiff.data.diff ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-text-subtle)">No diff for this file</div>
                    : <DiffPreview diff={scopedDiff.data.diff} />
          ) : kind === 'image' ? <ImagePreview workspace={workspace} file={file} />
            : kind === 'drawio' ? <DrawioPreview key={file.path} workspace={workspace} file={file} />
            : kind === 'text' ? <TextPreview key={file.path} workspace={workspace} file={file} onAddComment={onAddComment} editing={editing} />
            : <BinaryPreview workspace={workspace} file={file} />}
        </div>
      </div>
    </motion.aside>
  )
}
