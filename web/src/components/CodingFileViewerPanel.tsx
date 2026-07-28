import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, Copy, Download, ExternalLink, FileText, GitCompare, Loader2, Pencil, Save, Undo2, X, Eye } from 'lucide-react'
import Editor, { DiffEditor, useMonaco } from '@monaco-editor/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import 'github-markdown-css/github-markdown.css'

import { codingWorkspaceFileUrl, getCodingWorkspaceGitDiff, writeCodingWorkspaceFile } from '@/api/client'
import { downloadCodingWorkspaceFile } from '@/lib/coding-workspace-download'
import { cn } from '@/lib/utils'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { formatBytes } from '@/utils/format'
import { useMonacoTheme, languageForExt } from '@/hooks/useMonacoTheme'
import { queryKeys } from '@/queries'
import { SidePanel } from './shell/SidePanel'
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
      className="flex h-9 min-w-9 items-center justify-center gap-1 rounded-xs px-2 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) disabled:cursor-not-allowed disabled:opacity-40 md:h-auto md:min-w-0 md:py-1"
    >
      {copied ? <Check size={12} className="text-(--color-success)" /> : busy ? <Loader2 size={12} className="animate-spin" /> : <Copy size={12} />}
    </button>
  )
}

function TextPreview({
  workspace,
  file,
  onAddComment,
  onSendToChat,
  onAddCodeToChat,
  editing = false,
  onSaved,
  pendingDiff,
  onAcceptDiff,
  onRejectDiff,
}: {
  workspace: string
  file: WorkspaceFileInfo
  onAddComment?: (path: string, startLine: number, endLine: number) => void
  onSendToChat?: (action: string, code: string, path: string, startLine: number, endLine: number) => void
  /** Append selected code block to the chat composer. */
  onAddCodeToChat?: (code: string, path: string, startLine: number, endLine: number) => void
  editing?: boolean
  onSaved?: () => void
  pendingDiff?: { original: string; modified: string } | null
  onAcceptDiff?: () => void
  onRejectDiff?: () => void
}) {
  const tooLarge = file.size > MAX_TEXT_PREVIEW_BYTES
  const [content, setContent] = useState<string | null>(null)
  const [modified, setModified] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!tooLarge)
  const [saving, setSaving] = useState(false)
  const [editorMounted, setEditorMounted] = useState(false)
  const editorRef = useRef<Parameters<NonNullable<Parameters<typeof Editor>[0]['onMount']>>[0] | null>(null)

  const monaco = useMonaco()
  const theme = useMonacoTheme(monaco)
  const isDirty = modified !== null && modified !== content

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
          setModified(null)
          setLoading(false)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [workspace, file.path, tooLarge])

  // Register custom context menu actions
  useEffect(() => {
    if (!monaco || !editorMounted || !editorRef.current) return
    const editor = editorRef.current
    const disposables: { dispose: () => void }[] = []

    if (!editing && onSendToChat) {
      disposables.push(
        editor.addAction({
          id: 'evoflux.explain',
          label: 'Explain this code',
          contextMenuGroupId: 'evoflux',
          contextMenuOrder: 1,
          run: (ed) => {
            const sel = ed.getSelection()
            const text = sel ? ed.getModel()?.getValueInRange(sel) : ''
            if (text && sel) onSendToChat('explain', text, file.path, sel.startLineNumber, sel.endLineNumber)
          },
        }),
      )
      disposables.push(
        editor.addAction({
          id: 'evoflux.refactor',
          label: 'Refactor selection',
          contextMenuGroupId: 'evoflux',
          contextMenuOrder: 2,
          run: (ed) => {
            const sel = ed.getSelection()
            const text = sel ? ed.getModel()?.getValueInRange(sel) : ''
            if (text && sel) onSendToChat('refactor', text, file.path, sel.startLineNumber, sel.endLineNumber)
          },
        }),
      )
      disposables.push(
        editor.addAction({
          id: 'evoflux.fix',
          label: 'Fix this code',
          contextMenuGroupId: 'evoflux',
          contextMenuOrder: 3,
          run: (ed) => {
            const sel = ed.getSelection()
            const text = sel ? ed.getModel()?.getValueInRange(sel) : ''
            if (text && sel) onSendToChat('fix', text, file.path, sel.startLineNumber, sel.endLineNumber)
          },
        }),
      )
      disposables.push(
        editor.addAction({
          id: 'evoflux.addComment',
          label: 'Add to chat as reference',
          contextMenuGroupId: 'evoflux',
          contextMenuOrder: 4,
          run: (ed) => {
            const sel = ed.getSelection()
            if (sel) onAddComment?.(file.path, sel.startLineNumber, sel.endLineNumber)
          },
        }),
      )
      disposables.push(
        editor.addAction({
          id: 'evoflux.addToChat',
          label: 'Add to chat',
          contextMenuGroupId: 'evoflux',
          contextMenuOrder: 5,
          run: (ed) => {
            const sel = ed.getSelection()
            const text = sel ? ed.getModel()?.getValueInRange(sel) : ''
            if (text && sel) onAddCodeToChat?.(text, file.path, sel.startLineNumber, sel.endLineNumber)
          },
        }),
      )
    }

    // Ctrl+S to save in edit mode
    if (editing) {
      disposables.push(
        editor.addAction({
          id: 'evoflux.save',
          label: 'Save file',
          keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
          run: () => { void handleSave() },
        }),
      )
    }

    return () => { disposables.forEach((d) => d.dispose()) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monaco, editorMounted, editing, onSendToChat, onAddComment, onAddCodeToChat, file.path])

  const handleEditorMount = useCallback((editor: Parameters<NonNullable<Parameters<typeof Editor>[0]['onMount']>>[0]) => {
    editorRef.current = editor
    setEditorMounted(true)
  }, [])

  const handleChange = useCallback((value: string | undefined) => {
    if (value !== undefined) setModified(value)
  }, [])

  const handleSave = useCallback(async () => {
    if (!isDirty || saving || modified === null) return
    setSaving(true)
    try {
      await writeCodingWorkspaceFile(workspace, file.path, modified)
      setContent(modified)
      onSaved?.()
    } catch {
      // Error silently — user can retry
    } finally {
      setSaving(false)
    }
  }, [isDirty, saving, modified, workspace, file.path, onSaved])

  const handleDiscard = useCallback(() => {
    setModified(null)
    if (editorRef.current && content !== null) {
      editorRef.current.setValue(content)
    }
  }, [content])

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

  // Show inline diff when agent suggests changes
  if (pendingDiff) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-(--color-border) bg-(--bg-key) px-3 py-2">
          <span className="text-xs font-medium text-(--color-text-muted)">Agent suggested changes</span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onAcceptDiff}
              className="flex items-center gap-1 rounded-md bg-(--color-success)/15 px-2.5 py-1 text-xs font-medium text-(--color-success) hover:bg-(--color-success)/25"
            >
              <Check size={12} /> Accept
            </button>
            <button
              type="button"
              onClick={onRejectDiff}
              className="flex items-center gap-1 rounded-md bg-(--color-error)/15 px-2.5 py-1 text-xs font-medium text-(--color-error) hover:bg-(--color-error)/25"
            >
              <X size={12} /> Reject
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <DiffEditor
            className="h-full w-full"
            theme={theme}
            language={language}
            original={pendingDiff.original}
            modified={pendingDiff.modified}
            loading={<div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>}
            options={{
              readOnly: true,
              renderSideBySide: false,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 12,
              lineHeight: 20,
              fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
              glyphMargin: false,
              folding: false,
              wordWrap: 'on',
              scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8, useShadows: false },
              overviewRulerLanes: 0,
              padding: { top: 8, bottom: 8 },
              automaticLayout: true,
            }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Dirty indicator bar */}
      {editing && isDirty && (
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-(--color-border) bg-(--bg-key) px-3 py-1.5">
          <span className="text-xs text-(--color-text-muted)">Unsaved changes</span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleDiscard}
              disabled={saving}
              className="flex items-center gap-1 rounded-xs px-2 py-0.5 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-page) hover:text-(--color-text)"
            >
              <Undo2 size={11} /> Discard
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className="flex items-center gap-1 rounded-md bg-(--color-accent) px-2.5 py-0.5 text-xs font-medium text-(--color-text-on-accent) hover:opacity-90 disabled:opacity-50"
            >
              {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />} Save
            </button>
          </div>
        </div>
      )}
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
          contextmenu: true,
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
      <img src={url} alt={file.name} className="block max-h-full max-w-full rounded-xs border border-(--color-border) object-contain" />
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
    <div className="h-full min-h-0 w-full overflow-hidden" style={{ contain: 'layout paint size' }}>
      <pre className="h-full min-h-0 w-full max-w-full overflow-auto bg-(--bg-page) p-3 font-mono text-xs leading-relaxed">
        {diff.split('\n').map((line, index) => (
          <span key={index} className={cn('block max-w-full whitespace-pre-wrap break-all px-1', diffLineClass(line))}>{line || ' '}</span>
        ))}
      </pre>
    </div>
  )
}

/* -------------------------------------------------------------------------
 * RichPreview component for HTML and Markdown rendering
 * ------------------------------------------------------------------------- */
function RichPreview({ workspace, file, isHtml }: { workspace: string; file: WorkspaceFileInfo; isHtml: boolean }) {
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch(codingWorkspaceFileUrl(workspace, file.path))
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.text()
      })
      .then((text) => {
        if (!cancelled) { setContent(text); setLoading(false) }
      })
      .catch((e) => {
        if (!cancelled) { setError(e instanceof Error ? e.message : String(e)); setLoading(false) }
      })
    return () => { cancelled = true }
  }, [workspace, file.path])

  if (loading) return <div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>
  if (error) return <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">Failed to load: {error}</div>
  if (content === null) return null

  if (isHtml) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-white">
        <iframe
          srcDoc={content}
          title={file.name}
          className="h-full w-full border-0"
          sandbox="allow-scripts allow-same-origin allow-popups"
        />
      </div>
    )
  }

  return (
    <div className="h-full min-h-0 overflow-auto bg-(--bg-page)">
      <div className="markdown-body" style={{ padding: '24px', backgroundColor: 'transparent' }}>
        <ReactMarkdown 
          remarkPlugins={[remarkGfm]}
          components={{
            code({ inline, className, children, ...props }: any) {
              const match = /language-(\w+)/.exec(className || '')
              return !inline && match ? (
                <SyntaxHighlighter
                  style={vscDarkPlus as any}
                  language={match[1]}
                  PreTag="div"
                  {...props}
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              ) : (
                <code className={className} {...props}>
                  {children}
                </code>
              )
            }
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------
 * Main File Viewer Panel
 * ------------------------------------------------------------------------- */
export function CodingFileViewerPanel({
  workspace,
  file,
  onClose,
  onAddComment,
  onSendToChat,
  onAddCodeToChat,
  pendingDiff,
  onAcceptDiff,
  onRejectDiff,
  mobile = false,
  desktopOverlay = true,
  desktopOverlayInner = false,
  initialViewMode = 'file',
}: {
  workspace: string
  file: WorkspaceFileInfo | null
  onClose: () => void
  onAddComment?: (path: string, startLine: number, endLine: number) => void
  /** Editor → Chat: user triggers an action on selected code */
  onSendToChat?: (action: string, code: string, path: string, startLine: number, endLine: number) => void
  /** Append selected code block to the chat composer. */
  onAddCodeToChat?: (code: string, path: string, startLine: number, endLine: number) => void
  /** Show inline diff from agent suggestion (original vs modified) */
  pendingDiff?: { original: string; modified: string } | null
  /** Accept the pending diff — apply modified content */
  onAcceptDiff?: () => void
  /** Reject the pending diff — keep original */
  onRejectDiff?: () => void
  mobile?: boolean
  /** Dock into AppShell's body row instead of covering it. */
  desktopOverlay?: boolean
  desktopOverlayInner?: boolean
  /** Preferred pane when opening (e.g. Changes deep-link → diff). */
  initialViewMode?: 'file' | 'diff' | 'preview'
}) {
  const [viewMode, setViewMode] = useState<'file' | 'diff' | 'preview'>(initialViewMode)
  const [editing, setEditing] = useState(false)

  const scopedDiff = useQuery({
    queryKey: [...queryKeys.coding.diff(workspace), file?.path ?? null] as const,
    queryFn: () => getCodingWorkspaceGitDiff(workspace, file ? [file.path] : []),
    enabled: file !== null && viewMode === 'diff',
    staleTime: 5_000,
  })

  // Control preview mode fallback
  const kind = file ? kindOf(file) : 'binary'
  const ext = file ? extOf(file.name) : ''
  const isHtml = ext === 'html' || ext === 'htm'
  const isMarkdown = ext === 'md' || ext === 'markdown'
  const canPreview = isHtml || isMarkdown

  useEffect(() => {
    if (viewMode === 'preview' && !canPreview) {
      setViewMode('file')
    }
  }, [file?.path, canPreview, viewMode])

  if (!file) return null

  return (
    <SidePanel
      storageKey={STORAGE_KEYS.panels.codingFileViewer}
      defaultWidth={560}
      minWidth={420}
      maxWidth={Math.min(880, Math.max(420, Math.floor((typeof window === 'undefined' ? 880 : window.innerWidth) - 320)))}
      mobileOverlay
      desktopOverlay={desktopOverlay}
      desktopOverlayInner={desktopOverlayInner}
      mobile={mobile}
      resizeLabel="Resize file viewer"
      ariaLabel="File viewer"
      className="bg-(--bg-card)"
    >
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-(--color-text)" title={file.path}>{file.path}</h2>
          <p className="mt-0.5 text-xs text-(--color-text-subtle)">{formatBytes(file.size)} · {file.mime}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <div className="mr-1 flex rounded-md border border-(--color-border) p-0.5">
            <button 
              type="button" 
              onClick={() => { setViewMode('file'); setEditing(false) }} 
              className={cn('h-8 rounded-xs px-2 text-xs md:h-auto md:py-1', viewMode === 'file' && !editing ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
            >
              File
            </button>
            
            {canPreview && (
              <button 
                type="button" 
                onClick={() => { setViewMode('preview'); setEditing(false) }} 
                className={cn('flex h-8 items-center gap-1 rounded-xs px-2 text-xs md:h-auto md:py-1', viewMode === 'preview' ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
              >
                <Eye size={11} /> Preview
              </button>
            )}
            
            {kind === 'text' && (
              <button 
                type="button" 
                onClick={() => { setViewMode('file'); setEditing(true) }} 
                className={cn('flex h-8 items-center gap-1 rounded-xs px-2 text-xs md:h-auto md:py-1', editing ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
              >
                <Pencil size={11} /> Edit
              </button>
            )}
            <button 
              type="button" 
              onClick={() => { setViewMode('diff'); setEditing(false) }} 
              className={cn('flex h-8 items-center gap-1 rounded-xs px-2 text-xs md:h-auto md:py-1', viewMode === 'diff' ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
            >
              <GitCompare size={11} /> Diff
            </button>
          </div>
          <button type="button" onClick={() => void downloadCodingWorkspaceFile(workspace, file)} title="Download" className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)">
            <Download size={14} />
          </button>
          {(kind === 'text' || kind === 'drawio') && <CopyButton workspace={workspace} file={file} />}
          <button type="button" onClick={onClose} className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)" aria-label="Close file viewer" title="Close">
            <X size={16} />
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-hidden">
        {viewMode === 'diff' ? (
          <div className="h-full min-h-0 w-full overflow-hidden">
            {scopedDiff.isLoading ? <div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>
              : scopedDiff.isError ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">Failed to load diff</div>
                : !scopedDiff.data?.is_git_repo ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-text-subtle)">Not a git repository</div>
                  : !scopedDiff.data.diff ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-text-subtle)">No diff for this file</div>
                    : <DiffPreview diff={scopedDiff.data.diff} />}
          </div>
        ) : viewMode === 'preview' && canPreview ? (
          <RichPreview workspace={workspace} file={file} isHtml={isHtml} />
        ) : kind === 'image' ? (
          <ImagePreview workspace={workspace} file={file} />
        ) : kind === 'drawio' ? (
          <DrawioPreview key={file.path} workspace={workspace} file={file} />
        ) : kind === 'text' ? (
          <TextPreview
            key={file.path}
            workspace={workspace}
            file={file}
            onAddComment={onAddComment}
            onSendToChat={onSendToChat}
            onAddCodeToChat={onAddCodeToChat}
            editing={editing}
            pendingDiff={pendingDiff}
            onAcceptDiff={onAcceptDiff}
            onRejectDiff={onRejectDiff}
          />
        ) : (
          <BinaryPreview workspace={workspace} file={file} />
        )}
      </div>
    </SidePanel>
  )
}