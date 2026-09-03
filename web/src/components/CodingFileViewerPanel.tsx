import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Check, Copy, Download, ExternalLink, FileText, GitCompare, Lightbulb, Loader2, PanelRightClose, PanelRightOpen, Pencil, Save, Undo2, X, Eye } from 'lucide-react'
import Editor, { DiffEditor } from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'

import { codingWorkspaceFileUrl, createChangeSet, getCodingWorkspaceDiagnostics, getCodingWorkspaceGitDiff, getCodingWorkspaceSemanticResult, writeCodingWorkspaceFile } from '@/api/client'
import { isTauriAvailable, tauriOpenWorkspaceFile } from '@/api/tauri-workspace'
import { downloadCodingWorkspaceFile } from '@/lib/coding-workspace-download'
import { openExternalUrl } from '@/lib/open-external'
import { cn } from '@/lib/utils'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { isWorkspaceDocumentKind, workspaceFileKind, type WorkspaceFileKind } from '@/lib/workspace-file-kind'
import { formatBytes } from '@/utils/format'
import { MarkdownBlock } from '@/utils/markdown'
import { useMonacoTheme, languageForExt, useSafeMonaco } from '@/hooks/useMonacoTheme'
import { queryKeys } from '@/queries'
import { SidePanel } from './shell/SidePanel'
import { EditorAiActionDialog } from './EditorAiActionDialog'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'
import { useChangeSetStore } from '@/stores/useChangeSetStore'
import { useToastStore } from '@/stores/useToastStore'
import { LspRenameDialog, type LspRenameRequest } from './LspRenameDialog'
import type {
  CodingLspDiagnostic,
  EditorActionRequest,
  EditorAiAction,
  WorkspaceFileInfo,
} from '@/api/types'

const DocumentPreview = lazy(() =>
  import('./workspace-document-preview').then((module) => ({ default: module.WorkspaceDocumentPreview })),
)

const DRAWIO_EXTENSIONS = new Set(['drawio', 'dio'])
const MAX_TEXT_PREVIEW_BYTES = 512 * 1024
// Viewer URL length limit — diagrams above ~400KB XML fall back to text
const MAX_DRAWIO_VIEWER_BYTES = 400 * 1024

function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

type FileKind = WorkspaceFileKind | 'drawio'

function kindOf(file: WorkspaceFileInfo): FileKind {
  const ext = extOf(file.name)
  if (DRAWIO_EXTENSIONS.has(ext)) return 'drawio'
  const sharedKind = workspaceFileKind(file)
  return sharedKind
}

function RichFilePreviewLoading({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center gap-2 text-(--color-text-subtle)">
      <Loader2 size={17} className="animate-spin" aria-hidden="true" />
      <span className="text-xs">Loading {label} engine…</span>
    </div>
  )
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
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) disabled:cursor-not-allowed disabled:opacity-40"
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
  const [diagnostics, setDiagnostics] = useState<CodingLspDiagnostic[]>([])
  const [diagnosticStatus, setDiagnosticStatus] = useState<'idle' | 'checking' | 'ready' | 'unavailable' | 'unsupported' | 'error'>('idle')
  const [diagnosticMessage, setDiagnosticMessage] = useState<string | null>(null)
  const [aiRequest, setAiRequest] = useState<EditorActionRequest | null>(null)
  const [renameRequest, setRenameRequest] = useState<LspRenameRequest | null>(null)
  const editorRef = useRef<Parameters<NonNullable<Parameters<typeof Editor>[0]['onMount']>>[0] | null>(null)
  const sessionId = useTeamStore((state) => state.sessionId)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const openSettings = useUIStore((state) => state.openSettings)
  const setChangeSet = useChangeSetStore((state) => state.setActive)
  const pushToast = useToastStore((state) => state.push)

  const monaco = useSafeMonaco()
  const theme = useMonacoTheme(monaco)
  const isDirty = modified !== null && modified !== content
  const diagnosticContent = modified ?? content

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

  // Keep the LSP in sync with the Monaco buffer, including unsaved edits.
  // Debouncing avoids starting a request for every keystroke while keeping
  // feedback close enough to feel live during normal typing.
  useEffect(() => {
    if (tooLarge || diagnosticContent === null) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setDiagnosticStatus('checking')
      setDiagnosticMessage(null)
      void getCodingWorkspaceDiagnostics(workspace, file.path, diagnosticContent, controller.signal)
        .then((response) => {
          if (controller.signal.aborted) return
          setDiagnostics(response.diagnostics)
          setDiagnosticStatus(response.status)
          setDiagnosticMessage(response.message)
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return
          setDiagnostics([])
          setDiagnosticStatus('error')
          setDiagnosticMessage(reason instanceof Error ? reason.message : 'Unable to check this file.')
        })
    }, 450)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [workspace, file.path, diagnosticContent, tooLarge])

  // Use Monaco's native markers so errors appear on the gutter, overview
  // ruler, hover tooltip, and the inline editor surface automatically.
  useEffect(() => {
    if (!monaco || !editorMounted || !editorRef.current) return
    const model = editorRef.current.getModel()
    if (!model) return
    const markers = diagnostics.map((diagnostic) => {
      const range = diagnostic.range ?? {}
      const start = range.start ?? {}
      const end = range.end ?? start
      const startLine = Math.max(1, (start.line ?? 0) + 1)
      const startColumn = Math.max(1, (start.character ?? 0) + 1)
      const endLine = Math.max(startLine, (end.line ?? start.line ?? 0) + 1)
      const endColumn = Math.max(startColumn + 1, (end.character ?? start.character ?? 0) + 1)
      const severity = {
        1: monaco.MarkerSeverity.Error,
        2: monaco.MarkerSeverity.Warning,
        3: monaco.MarkerSeverity.Info,
        4: monaco.MarkerSeverity.Hint,
      }[diagnostic.severity ?? 3] ?? monaco.MarkerSeverity.Info
      return {
        severity,
        message: diagnostic.message,
        source: diagnostic.source ?? 'LSP',
        code: diagnostic.code !== undefined ? String(diagnostic.code) : undefined,
        startLineNumber: startLine,
        startColumn,
        endLineNumber: endLine,
        endColumn,
      }
    })
    monaco.editor.setModelMarkers(model, 'evoflux-lsp', markers)
    return () => monaco.editor.setModelMarkers(model, 'evoflux-lsp', [])
  }, [monaco, editorMounted, diagnostics])

  const runSemanticAction = useCallback(async (
    action: 'hover' | 'code_actions' | 'rename' | 'format' | 'organize_imports',
    options: {
      line?: number
      column?: number
      endLine?: number
      endColumn?: number
      newName?: string
      diagnostic?: CodingLspDiagnostic
    } = {},
  ): Promise<{ ok: boolean; message?: string }> => {
    if (diagnosticContent === null) return { ok: false, message: 'Editor content is unavailable.' }
    try {
      const response = await getCodingWorkspaceSemanticResult(workspace, {
        action,
        path: file.path,
        content: diagnosticContent,
        line: options.line,
        column: options.column,
        end_line: options.endLine,
        end_column: options.endColumn,
        new_name: options.newName,
        diagnostics: options.diagnostic ? [options.diagnostic] : undefined,
      })
      if (response.status !== 'ready') {
        throw new Error(response.message ?? `LSP ${response.status} for ${file.path}`)
      }
      if (action === 'hover') {
        pushToast({
          tone: 'info',
          title: 'LSP hover',
          description: response.result ? JSON.stringify(response.result).slice(0, 360) : 'No hover information.',
        })
        return { ok: true }
      }
      let workspaceEdit: Record<string, unknown> | null = null
      let title = action === 'rename'
        ? `Rename symbol to ${options.newName}`
        : action === 'format'
          ? `Format ${file.path}`
          : action === 'organize_imports'
            ? `Organize imports in ${file.path}`
            : `Quick fix in ${file.path}`
      if (response.result && !Array.isArray(response.result)) {
        workspaceEdit = response.result as Record<string, unknown>
      } else if (Array.isArray(response.result)) {
        const candidate = response.result.find((item) => (
          item && typeof item === 'object' && 'edit' in item
        )) as { title?: string; edit?: Record<string, unknown> } | undefined
        workspaceEdit = candidate?.edit ?? null
        if (candidate?.title) title = candidate.title
      }
      if (!workspaceEdit) {
        const message = 'No applicable LSP edit returned.'
        pushToast({ tone: 'info', title: message })
        return { ok: false, message }
      }
      const changeSet = await createChangeSet(workspace, {
        origin: 'lsp',
        title,
        workspace_edit: workspaceEdit,
      })
      setChangeSet(changeSet)
      return { ok: true }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'LSP action failed.'
      pushToast({
        tone: 'error',
        title: 'LSP action failed',
        description: message,
      })
      return { ok: false, message }
    }
  }, [diagnosticContent, file.path, pushToast, setChangeSet, workspace])

  // Register custom context menu actions
  useEffect(() => {
    if (!monaco || !editorMounted || !editorRef.current) return
    const editor = editorRef.current
    const disposables: { dispose: () => void }[] = []

    const startAiAction = (action: EditorAiAction, ed: MonacoEditor.ICodeEditor) => {
      const model = ed.getModel()
      if (!model || !sessionId) return
      const selection = ed.getSelection()
      const selectedText = selection && !selection.isEmpty()
        ? model.getValueInRange(selection)
        : ''
      const position = ed.getPosition()
      const word = position ? model.getWordAtPosition(position)?.word ?? null : null
      setAiRequest({
        session_id: sessionId,
        action,
        active_file: file.path,
        content: model.getValue(),
        document_version: model.getVersionId(),
        selection: selection && selectedText
          ? {
              text: selectedText,
              start_line: selection.startLineNumber,
              start_column: selection.startColumn,
              end_line: selection.endLineNumber,
              end_column: selection.endColumn,
            }
          : null,
        cursor_symbol: word,
        diagnostics,
        mention_paths: [],
      })
    }

    if (!editing && sessionId) {
      const actions: Array<{ action: EditorAiAction; label: string }> = [
        { action: 'explain_code', label: 'AI: Explain code or symbol' },
        { action: 'fix_diagnostic', label: 'AI: Fix diagnostic' },
        { action: 'refactor_selection', label: 'AI: Refactor selection' },
        { action: 'generate_tests', label: 'AI: Generate tests' },
        { action: 'generate_documentation', label: 'AI: Generate documentation' },
        { action: 'find_problems', label: 'AI: Find potential problems' },
        { action: 'simplify_code', label: 'AI: Simplify code' },
        { action: 'convert_pattern', label: 'AI: Convert implementation pattern' },
        { action: 'propagate_api_change', label: 'AI: Propagate API change' },
      ]
      actions.forEach(({ action, label }, index) => {
        disposables.push(editor.addAction({
          id: `evoflux.ai.${action}`,
          label,
          contextMenuGroupId: 'evoflux-ai',
          contextMenuOrder: index + 1,
          run: (ed) => startAiAction(action, ed),
        }))
      })
    }

    if (!editing) {
      disposables.push(editor.addAction({
        id: 'evoflux.lsp.hover',
        label: 'LSP: Show hover information',
        contextMenuGroupId: 'evoflux-lsp',
        contextMenuOrder: 1,
        run: (ed) => {
          const position = ed.getPosition()
          if (position) void runSemanticAction('hover', { line: position.lineNumber, column: position.column })
        },
      }))
      disposables.push(editor.addAction({
        id: 'evoflux.lsp.rename',
        label: 'LSP: Rename symbol',
        contextMenuGroupId: 'evoflux-lsp',
        contextMenuOrder: 2,
        run: (ed) => {
          const position = ed.getPosition()
          const model = ed.getModel()
          if (!position || !model) return
          setRenameRequest({
            line: position.lineNumber,
            column: position.column,
            currentName: model.getWordAtPosition(position)?.word ?? '',
          })
        },
      }))
      disposables.push(editor.addAction({
        id: 'evoflux.lsp.format',
        label: 'LSP: Format document',
        contextMenuGroupId: 'evoflux-lsp',
        contextMenuOrder: 3,
        run: () => { void runSemanticAction('format') },
      }))
      disposables.push(editor.addAction({
        id: 'evoflux.lsp.organizeImports',
        label: 'LSP: Organize imports',
        contextMenuGroupId: 'evoflux-lsp',
        contextMenuOrder: 4,
        run: () => { void runSemanticAction('organize_imports') },
      }))
    }

    if (!editing && (onAddComment || onAddCodeToChat || onSendToChat)) {
      disposables.push(
        editor.addAction({
          id: 'evoflux.addComment',
          label: 'Add to chat as reference',
          contextMenuGroupId: 'evoflux',
          contextMenuOrder: 20,
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
          contextMenuOrder: 21,
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
  }, [monaco, editorMounted, editing, onSendToChat, onAddComment, onAddCodeToChat, file.path, sessionId, diagnostics, runSemanticAction])

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

  const jumpToDiagnostic = useCallback((diagnostic: CodingLspDiagnostic) => {
    const range = diagnostic.range ?? {}
    const start = range.start ?? {}
    const lineNumber = Math.max(1, (start.line ?? 0) + 1)
    const column = Math.max(1, (start.character ?? 0) + 1)
    editorRef.current?.revealLineInCenter(lineNumber)
    editorRef.current?.setPosition({ lineNumber, column })
    editorRef.current?.focus()
  }, [])

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
      {(diagnosticStatus !== 'idle' || diagnostics.length > 0) && (
        <div className="shrink-0 border-t border-(--color-border) bg-(--bg-key) text-xs" role="status" aria-live="polite">
          <div className="flex min-h-8 items-center gap-2 px-3 py-1.5">
            <AlertCircle size={13} className={diagnostics.length > 0 ? 'text-(--color-error)' : 'text-(--color-text-subtle)'} aria-hidden="true" />
            {diagnosticStatus === 'checking' ? (
              <span className="text-(--color-text-subtle)">Checking with LSP…</span>
            ) : diagnosticStatus === 'ready' ? (
              <span className={diagnostics.length > 0 ? 'text-(--color-error)' : 'text-(--color-success)'}>
                {diagnostics.length ? `${diagnostics.length} issue${diagnostics.length === 1 ? '' : 's'} found` : 'No issues detected'}
              </span>
            ) : diagnosticStatus === 'unsupported' ? (
              <span className="text-(--color-text-subtle)">LSP is not configured for this file type</span>
            ) : (
              <>
                <span className="min-w-0 flex-1 truncate text-(--color-text-subtle)" title={diagnosticMessage ?? undefined}>
                  {diagnosticStatus === 'error' ? 'LSP check failed' : 'LSP unavailable'}{diagnosticMessage ? ` — ${diagnosticMessage}` : ''}
                </span>
                {diagnosticStatus === 'unavailable' && (
                  <button
                    type="button"
                    onClick={() => openSettings('language-servers', { workspace })}
                    className="shrink-0 rounded px-1.5 py-0.5 font-medium text-(--color-accent) hover:bg-(--color-accent-soft)"
                  >
                    Manage
                  </button>
                )}
              </>
            )}
          </div>
          {diagnostics.length > 0 && (
            <div className="max-h-28 overflow-y-auto border-t border-(--color-border)/70">
              {diagnostics.slice(0, 20).map((diagnostic, index) => {
                const line = (diagnostic.range?.start?.line ?? 0) + 1
                const column = (diagnostic.range?.start?.character ?? 0) + 1
                return (
                  <div key={`${line}:${column}:${diagnostic.message}:${index}`} className="flex items-center hover:bg-(--bg-page)">
                    <button
                      type="button"
                      onClick={() => jumpToDiagnostic(diagnostic)}
                      className="flex min-w-0 flex-1 items-start gap-2 px-3 py-1 text-left text-(--color-text-muted)"
                    >
                      <span className="shrink-0 font-mono text-(--color-text-subtle)">{line}:{column}</span>
                      <span className="truncate">{diagnostic.message}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        const end = diagnostic.range?.end ?? diagnostic.range?.start
                        void runSemanticAction('code_actions', {
                          line,
                          column,
                          endLine: (end?.line ?? line - 1) + 1,
                          endColumn: (end?.character ?? column - 1) + 1,
                          diagnostic,
                        })
                      }}
                      className="mr-2 flex h-6 w-6 shrink-0 items-center justify-center rounded text-(--color-accent) hover:bg-(--bg-key)"
                      aria-label={`Quick fix: ${diagnostic.message}`}
                      title="Show LSP quick fix"
                    >
                      <Lightbulb size={11} />
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
      {aiRequest && (
        <EditorAiActionDialog
          workspace={workspace}
          request={aiRequest}
          onClose={() => setAiRequest(null)}
          onOpenProblems={() => openWorkbenchTool('problems')}
        />
      )}
      <LspRenameDialog
        request={renameRequest}
        onClose={() => setRenameRequest(null)}
        onRename={async (newName) => {
          if (!renameRequest) throw new Error('Rename position is unavailable.')
          const result = await runSemanticAction('rename', {
            line: renameRequest.line,
            column: renameRequest.column,
            newName,
          })
          if (!result.ok) throw new Error(result.message ?? 'Rename could not be prepared.')
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

/**
 * Resolve an image path relative to the Markdown file being previewed.
 *
 * Chat Markdown resolves relative media through a session workspace. Coding
 * workspaces use a different API, so this adapter supplies the same
 * ``MarkdownBlock`` with the correct authenticated file URL.
 */
function codingMarkdownMediaUrl(workspace: string, markdownPath: string, src: string): string {
  if (
    /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(src)
    || src.startsWith('/')
  ) {
    return src
  }

  const sourcePath = src.split(/[?#]/, 1)[0]
  if (!sourcePath) return src

  let decodedPath: string
  try {
    decodedPath = decodeURIComponent(sourcePath)
  } catch {
    return src
  }

  const resolvedParts = markdownPath.split('/').slice(0, -1)
  for (const part of decodedPath.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (resolvedParts.length === 0) return src
      resolvedParts.pop()
      continue
    }
    resolvedParts.push(part)
  }

  return codingWorkspaceFileUrl(workspace, resolvedParts.join('/'))
}

function dirname(path: string): string {
  const index = path.lastIndexOf('/')
  return index < 0 ? '' : path.slice(0, index)
}

function resolveRelativePath(baseFilePath: string, reference: string): string | null {
  const trimmed = reference.trim()
  if (!trimmed || trimmed.startsWith('#') || trimmed.startsWith('//') || /^[a-z][a-z\d+.-]*:/i.test(trimmed)) {
    return null
  }
  let pathname = trimmed
  try { pathname = decodeURIComponent(trimmed) } catch { /* keep as-is */ }
  const queryIndex = pathname.indexOf('?')
  const hashIndex = pathname.indexOf('#')
  const suffixIndex = [queryIndex, hashIndex].filter((i) => i >= 0).sort((a, b) => a - b)[0]
  const cleanPath = suffixIndex === undefined ? pathname : pathname.slice(0, suffixIndex)
  const suffix = suffixIndex === undefined ? '' : pathname.slice(suffixIndex)
  const parts = cleanPath.startsWith('/') ? [] : dirname(baseFilePath).split('/').filter(Boolean)
  for (const part of cleanPath.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') { if (parts.length === 0) return null; parts.pop(); continue }
    parts.push(part)
  }
  if (parts.length === 0) return null
  return parts.join('/') + suffix
}

function resolveCodingRef(workspace: string, baseFilePath: string, reference: string): string | null {
  const resolved = resolveRelativePath(baseFilePath, reference)
  if (!resolved) return null
  const pathOnly = resolved.split('?')[0].split('#')[0]
  return codingWorkspaceFileUrl(workspace, pathOnly)
}

function rewriteCssUrlsForCoding(css: string, workspace: string, baseFilePath: string): string {
  const rewrite = (ref: string) => resolveCodingRef(workspace, baseFilePath, ref) ?? ref
  return css
    .replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/gi, (_m, _q, ref) => `url("${rewrite(ref)}")`)
    .replace(/@import\s+(['"])([^'"]+)\1/gi, (_m, q, ref) => `@import ${q}${rewrite(ref)}${q}`)
}

async function prepareHtmlForCoding(workspace: string, file: WorkspaceFileInfo, source: string): Promise<string> {
  const doc = new DOMParser().parseFromString(source, 'text/html')

  // Inline external stylesheets
  const links = Array.from(doc.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"][href]'))
  await Promise.all(links.map(async (link) => {
    const href = link.getAttribute('href') ?? ''
    const resolved = resolveRelativePath(file.path, href)
    if (!resolved) return
    try {
      const res = await fetch(codingWorkspaceFileUrl(workspace, resolved))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const css = await res.text()
      const style = doc.createElement('style')
      style.textContent = rewriteCssUrlsForCoding(css, workspace, resolved)
      style.dataset.workspacePreviewResolved = 'true'
      link.replaceWith(style)
    } catch {
      const rewritten = resolveCodingRef(workspace, file.path, href)
      if (rewritten) link.setAttribute('href', rewritten)
    }
  }))

  // Inline external scripts
  const scripts = Array.from(doc.querySelectorAll<HTMLScriptElement>('script[src]'))
  await Promise.all(scripts.map(async (script) => {
    const src = script.getAttribute('src') ?? ''
    const resolved = resolveRelativePath(file.path, src)
    if (!resolved) return
    try {
      const res = await fetch(codingWorkspaceFileUrl(workspace, resolved))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const js = await res.text()
      const inline = doc.createElement('script')
      inline.textContent = js
      for (const attr of script.attributes) {
        if (attr.name !== 'src') inline.setAttribute(attr.name, attr.value)
      }
      script.replaceWith(inline)
    } catch {
      const rewritten = resolveCodingRef(workspace, file.path, src)
      if (rewritten) script.setAttribute('src', rewritten)
    }
  }))

  // Rewrite remaining src/href/poster/data attributes
  doc.querySelectorAll<HTMLElement>('[src], [href], [poster], [data]').forEach((el) => {
    for (const attr of ['src', 'href', 'poster', 'data']) {
      const val = el.getAttribute(attr)
      if (!val) continue
      const rewritten = resolveCodingRef(workspace, file.path, val)
      if (rewritten) el.setAttribute(attr, rewritten)
    }
  })

  // Rewrite srcset
  doc.querySelectorAll<HTMLElement>('[srcset]').forEach((el) => {
    const val = el.getAttribute('srcset')
    if (!val) return
    el.setAttribute('srcset', val.split(',').map((c) => {
      const m = /^(\s*)(\S+)(.*)$/.exec(c)
      if (!m) return c
      const r = resolveCodingRef(workspace, file.path, m[2])
      return r ? `${m[1]}${r}${m[3]}` : c
    }).join(','))
  })

  // Rewrite CSS url() in inline styles
  doc.querySelectorAll<HTMLStyleElement>('style:not([data-workspace-preview-resolved])').forEach((s) => {
    s.textContent = rewriteCssUrlsForCoding(s.textContent ?? '', workspace, file.path)
  })
  doc.querySelectorAll<HTMLElement>('[style]').forEach((el) => {
    const val = el.getAttribute('style')
    if (val) el.setAttribute('style', rewriteCssUrlsForCoding(val, workspace, file.path))
  })

  return `<!doctype html>${doc.documentElement.outerHTML}`
}

/* -------------------------------------------------------------------------
 * RichPreview component for HTML and Markdown rendering
 * ------------------------------------------------------------------------- */
function RichPreview({ workspace, file, isHtml }: { workspace: string; file: WorkspaceFileInfo; isHtml: boolean }) {
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const transformImageSrc = useCallback(
    (src: string) => codingMarkdownMediaUrl(workspace, file.path, src),
    [workspace, file.path],
  )

  useEffect(() => {
    let cancelled = false
    fetch(codingWorkspaceFileUrl(workspace, file.path))
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.text()
      })
      .then(async (text) => {
        if (cancelled) return
        if (isHtml) {
          const prepared = await prepareHtmlForCoding(workspace, file, text)
          if (!cancelled) { setContent(prepared); setLoading(false) }
        } else {
          if (!cancelled) { setContent(text); setLoading(false) }
        }
      })
      .catch((e) => {
        if (!cancelled) { setError(e instanceof Error ? e.message : String(e)); setLoading(false) }
      })
    return () => { cancelled = true }
  }, [workspace, file, isHtml])

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
      <div className="p-6">
        <MarkdownBlock content={content} transformImageSrc={transformImageSrc} />
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
  embedded = false,
  fileTreeVisible = false,
  onToggleFileTree,
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
  /** Render inside the Coding Files workbench instead of creating a panel. */
  embedded?: boolean
  fileTreeVisible?: boolean
  onToggleFileTree?: () => void
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
  const isDocument = isWorkspaceDocumentKind(kind === 'drawio' ? 'binary' : kind)
  const canRichPreview = isHtml || isMarkdown
  const canPreview = canRichPreview || isDocument
  const effectiveViewMode = viewMode === 'preview' && !canPreview ? 'file' : viewMode

  const handleOpenFile = async () => {
    if (!file) return
    try {
      if (isTauriAvailable()) {
        await tauriOpenWorkspaceFile(workspace, file.path)
        return
      }
      await openExternalUrl(codingWorkspaceFileUrl(workspace, file.path))
    } catch {
      // Download remains available if the OS/browser rejects opening the file.
    }
  }

  if (!file) return null

  const content = (
    <>
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-(--color-border) px-2">
        <div
          className="flex min-w-0 flex-1 items-baseline gap-1.5"
          title={`${file.path} · ${formatBytes(file.size)} · ${file.mime}`}
        >
          <h2 className="truncate text-xs font-semibold text-(--color-text)">{file.path}</h2>
          <span className="shrink-0 text-[10px] text-(--color-text-subtle)">{formatBytes(file.size)}</span>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <div className="mr-0.5 flex rounded-md border border-(--color-border) p-0.5" role="group" aria-label="File view mode">
            <button
              type="button"
              onClick={() => { setViewMode('file'); setEditing(false) }}
              title="File"
              aria-label="View file"
              aria-pressed={effectiveViewMode === 'file' && !editing}
              className={cn('flex h-6 w-6 items-center justify-center rounded-xs', effectiveViewMode === 'file' && !editing ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
            >
              <FileText size={12} />
            </button>

            {canPreview && (
              <button
                type="button"
                onClick={() => { setViewMode('preview'); setEditing(false) }}
                title="Preview"
                aria-label="Preview file"
                aria-pressed={effectiveViewMode === 'preview'}
                className={cn('flex h-6 w-6 items-center justify-center rounded-xs', effectiveViewMode === 'preview' ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
              >
                <Eye size={12} />
              </button>
            )}

            {kind === 'text' && (
              <button
                type="button"
                onClick={() => { setViewMode('file'); setEditing(true) }}
                title="Edit"
                aria-label="Edit file"
                aria-pressed={editing}
                className={cn('flex h-6 w-6 items-center justify-center rounded-xs', editing ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
              >
                <Pencil size={12} />
              </button>
            )}
            <button
              type="button"
              onClick={() => { setViewMode('diff'); setEditing(false) }}
              title="Diff"
              aria-label="View file diff"
              aria-pressed={effectiveViewMode === 'diff'}
              className={cn('flex h-6 w-6 items-center justify-center rounded-xs', effectiveViewMode === 'diff' ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)')}
            >
              <GitCompare size={12} />
            </button>
          </div>
          <button
            type="button"
            onClick={() => void handleOpenFile()}
            title="Open file"
            aria-label="Open coding file"
            className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <ExternalLink size={13} />
          </button>
          <button type="button" onClick={() => void downloadCodingWorkspaceFile(workspace, file)} title="Download" aria-label="Download file" className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)">
            <Download size={13} />
          </button>
          {(kind === 'text' || kind === 'drawio') && <CopyButton workspace={workspace} file={file} />}
          {onToggleFileTree && (
            <button
              type="button"
              onClick={onToggleFileTree}
              className={cn(
                'flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                fileTreeVisible && 'bg-(--bg-key) text-(--color-text)',
              )}
              aria-label={fileTreeVisible ? 'Hide coding file tree' : 'Show coding file tree'}
              title={fileTreeVisible ? 'Hide file tree' : 'Show file tree'}
              aria-pressed={fileTreeVisible}
            >
              {fileTreeVisible ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
            </button>
          )}
          <button type="button" onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)" aria-label="Close file viewer" title="Close">
            <X size={14} />
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-hidden">
        {effectiveViewMode === 'diff' ? (
          <div className="h-full min-h-0 w-full overflow-hidden">
            {scopedDiff.isLoading ? <div className="flex h-full items-center justify-center"><Loader2 size={16} className="animate-spin text-(--color-text-subtle)" /></div>
              : scopedDiff.isError ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">Failed to load diff</div>
                : !scopedDiff.data?.is_git_repo ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-text-subtle)">Not a git repository</div>
                  : !scopedDiff.data.diff ? <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-text-subtle)">No diff for this file</div>
                    : <DiffPreview diff={scopedDiff.data.diff} />}
          </div>
        ) : effectiveViewMode === 'preview' && canRichPreview ? (
          <RichPreview workspace={workspace} file={file} isHtml={isHtml} />
        ) : kind === 'image' ? (
          <ImagePreview workspace={workspace} file={file} />
        ) : kind === 'drawio' ? (
          <DrawioPreview key={file.path} workspace={workspace} file={file} />
        ) : isDocument ? (
          <Suspense fallback={<RichFilePreviewLoading label="document" />}>
            <DocumentPreview
              key={`${file.path}:${file.mtime}`}
              file={file}
              workspace={workspace}
            />
          </Suspense>
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
    </>
  )

  if (embedded) {
    return (
      <section className="flex h-full min-h-0 min-w-0 flex-col bg-(--bg-card)" aria-label="File preview">
        {content}
      </section>
    )
  }

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
      {content}
    </SidePanel>
  )
}
