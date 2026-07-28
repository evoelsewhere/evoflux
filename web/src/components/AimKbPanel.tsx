import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Editor, { useMonaco } from '@monaco-editor/react'
import {
  ArrowLeft,
  BookOpen,
  Columns2,
  Copy,
  Database,
  Eye,
  FileText,
  FolderOpen,
  Loader2,
  LockKeyhole,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  Undo2,
} from 'lucide-react'
import {
  codingWorkspaceFileUrl,
  createAimKbDocument,
  getAimKbDocument,
  listCodingWorkspaceFiles,
  reindexAimProject,
  searchAimKb,
  updateAimKbDocument,
} from '@/api/client'
import { takeAimKbOpenPath } from '@/lib/aimHandoff'
import { resolveAimRolePath, splitFrontmatter } from '@/lib/aim-kb'
import { queryKeys } from '@/queries/keys'
import { MarkdownBlock } from '@/utils/markdown'
import { buildTree } from '@/utils/workspaceFileTree'
import { TreeNodeView } from '@/components/CodingWorkspacePanel'
import { ListEnter } from '@/components/motion'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { languageForExt, useMonacoTheme } from '@/hooks/useMonacoTheme'
import { cn } from '@/lib/utils'
import { formatBytes } from '@/utils/format'
import type { AimKbDocument, CodingProject, WorkspaceFileInfo } from '@/api/types'

const EMPTY_CHANGED_PATHS = new Set<string>()
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'])
const TEXT_EXTENSIONS = new Set([
  '', 'csv', 'ini', 'json', 'jsonl', 'md', 'py', 'rst', 'sh', 'sql', 'toml', 'txt',
  'xml', 'yaml', 'yml',
])
const SEARCH_SCOPES = [
  { value: 'all', label: 'Everywhere', prefix: undefined },
  { value: 'modules', label: 'Unit docs', prefix: 'modules' },
  { value: 'business-rules', label: 'Business rules', prefix: 'business-rules' },
  { value: 'mapping', label: 'Mappings', prefix: 'mapping' },
  { value: 'decisions', label: 'Decisions', prefix: 'decisions' },
  { value: 'rulebook', label: 'Rulebook', prefix: 'rulebook' },
] as const

type ViewMode = 'preview' | 'edit' | 'split'
type NewDocumentTemplate = 'note' | 'decision' | 'mapping' | 'yaml'

function extensionOf(path: string): string {
  const name = path.split('/').pop() ?? path
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : ''
}

function templateContent(template: NewDocumentTemplate): string {
  if (template === 'decision') {
    return '# Decision\n\n## Context\n\n## Decision\n\n## Consequences\n\n'
  }
  if (template === 'mapping') {
    return '# Target mapping\n\n## Source behavior\n\n## Target design\n\n## Verification\n\n'
  }
  if (template === 'yaml') return '# Configuration\n'
  return '# New document\n\n'
}

export function AimKbPanel({ project }: { project: CodingProject }) {
  const queryClient = useQueryClient()
  const kbPath = resolveAimRolePath(project, 'kb')
  const [selected, setSelected] = useState<WorkspaceFileInfo | null>(null)
  const [selectedLine, setSelectedLine] = useState(0)
  const [viewMode, setViewMode] = useState<ViewMode>('preview')
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search.trim())
  const [searchScope, setSearchScope] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [isDirty, setIsDirty] = useState(false)
  const [pendingOpenPath, setPendingOpenPath] = useState<string | null>(() => takeAimKbOpenPath())

  const filesQuery = useQuery({
    queryKey: ['aim-kb-files', kbPath ?? ''],
    queryFn: () => listCodingWorkspaceFiles(kbPath as string),
    enabled: Boolean(kbPath),
    staleTime: 10_000,
  })
  const files = useMemo(() => filesQuery.data?.files ?? [], [filesQuery.data])
  const tree = useMemo(() => buildTree(files), [files])
  const extension = selected ? extensionOf(selected.path) : ''
  const isImage = Boolean(selected && IMAGE_EXTENSIONS.has(extension))
  const isText = Boolean(
    selected &&
      (TEXT_EXTENSIONS.has(extension) || selected.mime.startsWith('text/')) &&
      !isImage,
  )

  const documentQuery = useQuery({
    queryKey: ['aim-kb-document', project.id, selected?.path ?? ''],
    queryFn: () => getAimKbDocument(project.id, selected!.path),
    enabled: Boolean(selected && isText),
    staleTime: 5_000,
  })
  const selectedScope = SEARCH_SCOPES.find((scope) => scope.value === searchScope)
  const searchQuery = useQuery({
    queryKey: ['aim-kb-search', project.id, deferredSearch, searchScope],
    queryFn: () => searchAimKb(project.id, deferredSearch, { pathPrefix: selectedScope?.prefix }),
    enabled: deferredSearch.length >= 2,
    staleTime: 5_000,
  })
  const reindex = useMutation({
    mutationFn: () => reindexAimProject(project.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.aimSummary(project.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.aimUnits(project.id, undefined) })
      void queryClient.invalidateQueries({ queryKey: ['projects', 'detail', project.id, 'aim-traceability'] })
    },
  })

  const selectFile = useCallback((file: WorkspaceFileInfo, line = 0) => {
    if (isDirty && selected?.path !== file.path && !window.confirm('Discard unsaved changes?')) return
    setSelected(file)
    setSelectedLine(line)
    setIsDirty(false)
    const protectedDocument = ['state/', 'runs/', '.aim-actuals/'].some((prefix) => file.path.startsWith(prefix))
    if (protectedDocument) setViewMode('preview')
    else if (line > 0) setViewMode('edit')
  }, [isDirty, selected?.path])

  useEffect(() => {
    if (!pendingOpenPath || files.length === 0) return
    const file = files.find((item) => item.path === pendingOpenPath)
    // One-shot navigation handoff after the async listing resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (file) selectFile(file)
    setPendingOpenPath(null)
  }, [files, pendingOpenPath, selectFile])

  if (!kbPath) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-xs text-(--color-text-muted)">
        No KB repo is mapped on this machine. Rejoin the project to restore it.
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-(--color-border) px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-accent)">
            <BookOpen size={15} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-(--color-text)">Knowledge Base</h1>
            <p className="truncate text-[10px] text-(--color-text-subtle)">
              {kbPath.split(/[\\/]/).filter(Boolean).pop()} · {files.length} files · editable workspace
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setCreateOpen(true)}>
            <Plus size={12} /> New document
          </Button>
          <Button size="sm" variant="ghost" onClick={() => reindex.mutate()} disabled={reindex.isPending} title="Rebuild unit, run, and link indexes from the KB">
            {reindex.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Reindex
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className={cn('min-h-0 min-w-0 flex-1 flex-col border-r border-(--color-border) bg-(--bg-subtle)/25 lg:flex lg:w-80 lg:flex-none', selected ? 'hidden lg:flex' : 'flex')}>
          <div className="shrink-0 space-y-2 border-b border-(--color-border) p-2.5">
            <div className="relative">
              <Search size={12} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-(--color-text-subtle)" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search paths and contents…"
                className="h-8 pl-8 text-xs"
                aria-label="Search knowledge base"
              />
            </div>
            <Select value={searchScope} onValueChange={(value) => setSearchScope(value ?? 'all')}>
              <SelectTrigger size="sm" className="w-full" aria-label="Search scope">
                <SelectValue>{selectedScope?.label ?? 'Everywhere'}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {SEARCH_SCOPES.map((scope) => <SelectItem key={scope.value} value={scope.value}>{scope.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {deferredSearch.length > 0 ? (
              <SearchResults
                query={deferredSearch}
                loading={searchQuery.isFetching}
                results={searchQuery.data?.results ?? []}
                files={files}
                onSelect={selectFile}
              />
            ) : filesQuery.isLoading ? (
              <KbTreeSkeleton />
            ) : files.length === 0 ? (
              <p className="px-2 py-4 text-xs text-(--color-text-subtle)">KB is empty. Run assessment or create a document.</p>
            ) : (
              <TreeNodeView
                node={tree}
                depth={0}
                selectedPath={selected?.path ?? null}
                onFileSelect={(file) => file && selectFile(file)}
                changedPaths={EMPTY_CHANGED_PATHS}
              />
            )}
          </div>
        </aside>

        <main className={cn('min-h-0 min-w-0 flex-1 flex-col', selected ? 'flex' : 'hidden lg:flex')}>
          {!selected ? (
            <KbHome files={files} onOpen={selectFile} />
          ) : (
            <>
              <div className="flex min-h-11 shrink-0 items-center gap-2 border-b border-(--color-border) px-3 py-2">
                <button type="button" onClick={() => { if (!isDirty || window.confirm('Discard unsaved changes?')) { setSelected(null); setIsDirty(false) } }} className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) lg:hidden" aria-label="Back to Knowledge Base explorer">
                  <ArrowLeft size={14} />
                </button>
                <FileText size={13} className="shrink-0 text-(--color-text-subtle)" />
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-(--color-text-2)" title={selected.path}>{selected.path}</span>
                {documentQuery.data && (
                  <span className="hidden shrink-0 text-[9px] text-(--color-text-subtle) sm:inline">
                    {formatBytes(documentQuery.data.size)} · {documentQuery.data.content.split(/\r?\n/).length} lines
                  </span>
                )}
                {documentQuery.data?.writable === false && (
                  <span className="inline-flex items-center gap-1 rounded bg-(--bg-key) px-1.5 py-0.5 text-[9px] text-(--color-text-subtle)"><LockKeyhole size={9} /> generated</span>
                )}
                {isText && documentQuery.data && (
                  <ViewModeControl mode={viewMode} onChange={setViewMode} writable={documentQuery.data.writable} />
                )}
                <button type="button" onClick={() => void navigator.clipboard.writeText(selected.path)} className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key)" title="Copy KB path" aria-label="Copy KB path"><Copy size={12} /></button>
              </div>

              <div className="min-h-0 flex-1">
                {isImage ? (
                  <div className="flex h-full items-center justify-center overflow-auto p-4"><img src={codingWorkspaceFileUrl(kbPath, selected.path)} alt={selected.path} className="max-h-full max-w-full rounded-md border border-(--color-border) object-contain" /></div>
                ) : !isText ? (
                  <div className="flex h-full items-center justify-center px-6 text-center"><div><Database size={24} className="mx-auto text-(--color-text-subtle)" /><p className="mt-2 text-xs text-(--color-text-muted)">Binary files can be inspected externally but are not editable here.</p></div></div>
                ) : documentQuery.isLoading ? (
                  <div className="p-4"><FileContentSkeleton /></div>
                ) : documentQuery.isError || !documentQuery.data ? (
                  <div className="flex h-full items-center justify-center px-6 text-center text-xs text-(--color-error)">This document could not be loaded.</div>
                ) : (
                  <DocumentWorkspace
                    key={`${documentQuery.data.path}:${documentQuery.data.revision}`}
                    projectId={project.id}
                    document={documentQuery.data}
                    extension={extension}
                    mode={viewMode}
                    selectedLine={selectedLine}
                    onDirtyChange={setIsDirty}
                    onOpenPath={(path) => {
                      const file = files.find((item) => item.path === path)
                      if (file) selectFile(file)
                    }}
                  />
                )}
              </div>
            </>
          )}
        </main>
      </div>

      <NewDocumentDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        projectId={project.id}
        kbPath={kbPath}
        onCreated={(file) => selectFile(file)}
      />
    </div>
  )
}

function SearchResults({ query, loading, results, files, onSelect }: { query: string; loading: boolean; results: { path: string; line: number; excerpt: string }[]; files: WorkspaceFileInfo[]; onSelect: (file: WorkspaceFileInfo, line?: number) => void }) {
  if (query.length < 2) return <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Type at least two characters to search content.</p>
  if (loading && results.length === 0) return <div className="space-y-2 p-1">{Array.from({ length: 7 }, (_, index) => <Skeleton key={index} className="h-12" />)}</div>
  if (results.length === 0) return <p className="px-2 py-4 text-xs text-(--color-text-subtle)">No paths or content match “{query}”.</p>
  return (
    <div className="space-y-1">
      <p className="px-2 pb-1 text-[9px] uppercase text-(--color-text-subtle)">{results.length} {results.length === 1 ? 'match' : 'matches'}</p>
      {results.map((result, index) => {
        const file = files.find((item) => item.path === result.path)
        return (
          <ListEnter key={`${result.path}:${result.line}:${index}`} index={index}>
          <button type="button" disabled={!file} onClick={() => file && onSelect(file, result.line)} className="w-full rounded-md px-2 py-2 text-left transition-colors hover:bg-(--bg-key) disabled:opacity-50">
            <span className="block truncate font-mono text-[10px] font-medium text-(--color-text-2)">{result.path}{result.line > 0 ? `:${result.line}` : ''}</span>
            <span className="mt-1 block line-clamp-2 text-[9px] leading-4 text-(--color-text-subtle)">{result.excerpt}</span>
          </button>
          </ListEnter>
        )
      })}
    </div>
  )
}

function ViewModeControl({ mode, onChange, writable }: { mode: ViewMode; onChange: (mode: ViewMode) => void; writable: boolean }) {
  const items: { mode: ViewMode; label: string; Icon: typeof Eye; disabled?: boolean }[] = [
    { mode: 'preview', label: 'Preview', Icon: Eye },
    { mode: 'edit', label: 'Edit', Icon: Pencil, disabled: !writable },
    { mode: 'split', label: 'Split', Icon: Columns2, disabled: !writable },
  ]
  return (
    <div className="inline-flex rounded-md border border-(--color-border) bg-(--bg-key)/55 p-0.5">
      {items.map(({ mode: itemMode, label, Icon, disabled }) => (
        <button key={itemMode} type="button" disabled={disabled} onClick={() => onChange(itemMode)} className={cn('flex h-6 items-center gap-1 rounded px-1.5 text-[9px] transition-colors disabled:opacity-35', mode === itemMode ? 'bg-(--bg-page) text-(--color-text) shadow-sm' : 'text-(--color-text-muted) hover:text-(--color-text)')} title={label} aria-label={label} aria-pressed={mode === itemMode}>
          <Icon size={10} /><span className="hidden lg:inline">{label}</span>
        </button>
      ))}
    </div>
  )
}

function DocumentWorkspace({ projectId, document, extension, mode, selectedLine, onDirtyChange, onOpenPath }: { projectId: string; document: AimKbDocument; extension: string; mode: ViewMode; selectedLine: number; onDirtyChange: (dirty: boolean) => void; onOpenPath: (path: string) => void }) {
  const queryClient = useQueryClient()
  const monaco = useMonaco()
  const theme = useMonacoTheme(monaco)
  const [baseline, setBaseline] = useState(document.content)
  const [draft, setDraft] = useState(document.content)
  const [revision, setRevision] = useState(document.revision)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const editorRef = useRef<Parameters<NonNullable<Parameters<typeof Editor>[0]['onMount']>>[0] | null>(null)
  const dirty = draft !== baseline

  const save = useCallback(async () => {
    if (!dirty || saving || !document.writable) return
    setSaving(true)
    setSaveError(null)
    try {
      const saved = await updateAimKbDocument(projectId, document.path, draft, revision)
      setBaseline(saved.content)
      setDraft(saved.content)
      setRevision(saved.revision)
      onDirtyChange(false)
      queryClient.setQueryData(['aim-kb-document', projectId, document.path], saved)
      void queryClient.invalidateQueries({ queryKey: ['aim-kb-files'] })
      void queryClient.invalidateQueries({ queryKey: ['aim-kb-search', projectId] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.aimUnits(projectId, undefined) })
      void queryClient.invalidateQueries({ queryKey: ['projects', 'detail', projectId, 'aim-traceability'] })
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Document could not be saved.')
    } finally {
      setSaving(false)
    }
  }, [dirty, document.path, document.writable, draft, onDirtyChange, projectId, queryClient, revision, saving])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void save()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [save])

  const editor = (
    <Editor
      key={`edit:${document.path}`}
      path={`aim-kb-edit://${document.path}`}
      height="100%"
      theme={theme}
      language={languageForExt(extension)}
      value={draft}
      onChange={(value) => {
        const next = value ?? ''
        setDraft(next)
        onDirtyChange(next !== baseline)
      }}
      onMount={(instance) => {
        editorRef.current = instance
        if (selectedLine > 0) {
          instance.setPosition({ lineNumber: selectedLine, column: 1 })
          instance.revealLineInCenter(selectedLine)
          instance.focus()
        }
      }}
      options={{
        readOnly: !document.writable,
        domReadOnly: !document.writable,
        automaticLayout: true,
        minimap: { enabled: false },
        wordWrap: 'on',
        fontSize: 12,
        lineHeight: 20,
        scrollBeyondLastLine: false,
        glyphMargin: false,
        folding: true,
        overviewRulerLanes: 0,
        padding: { top: 10, bottom: 10 },
        scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8, useShadows: false },
      }}
    />
  )

  return (
    <div className="flex h-full min-h-0 flex-col">
      {(dirty || saveError) && (
        <div className={cn('flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-(--color-border) px-3 py-2', saveError ? 'bg-(--color-error-subtle)/35' : 'bg-(--color-warning-subtle)/20')}>
          <p className={cn('text-[10px]', saveError ? 'text-(--color-error)' : 'text-(--color-warning)')}>{saveError ?? 'Unsaved changes'}</p>
          <div className="flex items-center gap-1.5">
            <Button size="sm" variant="ghost" disabled={saving} onClick={() => { setDraft(baseline); editorRef.current?.setValue(baseline); onDirtyChange(false); setSaveError(null) }}><Undo2 size={11} /> Discard</Button>
            <Button size="sm" disabled={!dirty || saving} onClick={() => void save()}>{saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />} Save</Button>
          </div>
        </div>
      )}
      <div className={cn('min-h-0 flex-1', mode === 'split' && 'grid lg:grid-cols-2')}>
        {mode !== 'preview' && <div className="h-full min-h-0 overflow-hidden border-r border-(--color-border)">{editor}</div>}
        {mode !== 'edit' && (
          <div
            className={cn(
              'h-full min-h-0',
              extension === 'md' ? 'overflow-y-auto p-4' : 'overflow-hidden',
            )}
          >
            <DocumentPreview content={draft} extension={extension} path={document.path} onOpenPath={onOpenPath} />
          </div>
        )}
      </div>
    </div>
  )
}

function resolveKbLink(currentPath: string, href: string): string | null {
  if (/^(?:[a-z]+:|#|\/)/i.test(href)) return null
  const withoutAnchor = href.split(/[?#]/, 1)[0]
  if (!withoutAnchor) return null
  const parts = currentPath.split('/').slice(0, -1)
  for (const part of decodeURIComponent(withoutAnchor).split('/')) {
    if (!part || part === '.') continue
    if (part === '..') parts.pop()
    else parts.push(part)
  }
  return parts.join('/')
}

function DocumentPreview({ content, extension, path, onOpenPath }: { content: string; extension: string; path: string; onOpenPath: (path: string) => void }) {
  if (extension === 'md') {
    const { meta, body } = splitFrontmatter(content)
    return (
      <div className="mx-auto max-w-4xl">
        {meta.length > 0 && <div className="mb-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border border-(--color-border) bg-(--bg-key)/55 px-3 py-2">{meta.map(([key, value]) => <div key={key} className="contents"><span className="font-mono text-[9px] uppercase text-(--color-text-subtle)">{key}</span><span className="min-w-0 break-words text-xs text-(--color-text-2)">{value || '—'}</span></div>)}</div>}
        <div className="prose prose-sm max-w-none text-sm text-(--color-text)"><MarkdownBlock content={body} onLinkClick={(href) => { const target = resolveKbLink(path, href); if (!target) return false; onOpenPath(target); return true }} /></div>
      </div>
    )
  }
  return <ReadOnlyCodeView content={content} extension={extension} path={path} />
}

function ReadOnlyCodeView({ content, extension, path }: { content: string; extension: string; path: string }) {
  const monaco = useMonaco()
  const theme = useMonacoTheme(monaco)
  return (
    <Editor
      key={`preview:${path}`}
      path={`aim-kb-preview://${path}`}
      height="100%"
      theme={theme}
      language={languageForExt(extension)}
      value={content}
      options={{
        readOnly: true,
        domReadOnly: true,
        automaticLayout: true,
        minimap: { enabled: false },
        wordWrap: 'on',
        fontSize: 12,
        lineHeight: 20,
        lineNumbers: 'on',
        renderLineHighlight: 'none',
        scrollBeyondLastLine: false,
        glyphMargin: false,
        folding: true,
        contextmenu: true,
        overviewRulerLanes: 0,
        overviewRulerBorder: false,
        padding: { top: 10, bottom: 10 },
        scrollbar: {
          verticalScrollbarSize: 8,
          horizontalScrollbarSize: 8,
          useShadows: false,
        },
      }}
    />
  )
}

function NewDocumentDialog({ open, onOpenChange, projectId, kbPath, onCreated }: { open: boolean; onOpenChange: (open: boolean) => void; projectId: string; kbPath: string; onCreated: (file: WorkspaceFileInfo) => void }) {
  const queryClient = useQueryClient()
  const [template, setTemplate] = useState<NewDocumentTemplate>('note')
  const [path, setPath] = useState('decisions/new-document.md')
  const [error, setError] = useState<string | null>(null)
  const createMutation = useMutation({
    mutationFn: () => createAimKbDocument(projectId, path.trim(), templateContent(template)),
    onSuccess: async (document) => {
      await queryClient.invalidateQueries({ queryKey: ['aim-kb-files', kbPath] })
      queryClient.setQueryData(['aim-kb-document', projectId, document.path], document)
      onCreated({ path: document.path, name: document.path.split('/').pop() ?? document.path, size: document.size, mtime: document.mtime, mime: 'text/plain' })
      onOpenChange(false)
      setError(null)
    },
    onError: (cause) => setError(cause instanceof Error ? cause.message : 'Document could not be created.'),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(440px,calc(100vw-2rem))] max-w-none sm:max-w-none">
        <DialogTitle>New KB document</DialogTitle>
        <p className="text-xs text-(--color-text-muted)">Create an editable document in the project knowledge base.</p>
        <label className="space-y-1.5 text-xs text-(--color-text-muted)">Template<Select value={template} onValueChange={(value) => setTemplate((value ?? 'note') as NewDocumentTemplate)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="note">Markdown note</SelectItem><SelectItem value="decision">Architecture decision</SelectItem><SelectItem value="mapping">Target mapping</SelectItem><SelectItem value="yaml">YAML configuration</SelectItem></SelectContent></Select></label>
        <label className="space-y-1.5 text-xs text-(--color-text-muted)">KB-relative path<Input value={path} onChange={(event) => setPath(event.target.value)} placeholder="decisions/ADR-001.md" /></label>
        {error && <p className="text-xs text-(--color-error)">{error}</p>}
        <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!path.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>{createMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Create</Button></div>
      </DialogContent>
    </Dialog>
  )
}

function KbHome({ files, onOpen }: { files: WorkspaceFileInfo[]; onOpen: (file: WorkspaceFileInfo) => void }) {
  const groups = [
    ['modules/', 'Unit documentation'], ['business-rules/', 'Business rules'], ['mapping/', 'Target mappings'],
    ['decisions/', 'Decisions'], ['rulebook/', 'Rulebook'], ['runs/', 'Run evidence'],
  ] as const
  const recent = [...files].sort((left, right) => right.mtime - left.mtime).slice(0, 8)
  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-5xl">
        <div className="flex items-start gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-accent)"><FolderOpen size={17} /></span><div><h2 className="text-sm font-semibold text-(--color-text)">KB document workspace</h2><p className="mt-1 max-w-2xl text-xs leading-5 text-(--color-text-muted)">Search and edit project knowledge, including the local rulebook. Generated state and run evidence remain protected.</p></div></div>
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3">{groups.map(([prefix, label]) => { const count = files.filter((file) => file.path.startsWith(prefix)).length; return <div key={prefix} className="rounded-md border border-(--color-border) px-3 py-2.5"><p className="text-[10px] text-(--color-text-subtle)">{label}</p><p className="mt-1 font-mono text-base font-semibold text-(--color-text)">{count}</p><p className="mt-0.5 truncate font-mono text-[8px] text-(--color-text-subtle)">{prefix}</p></div> })}</div>
        <section className="mt-6 border-t border-(--color-border) pt-4"><h3 className="text-[10px] font-semibold uppercase text-(--color-text-subtle)">Recently changed</h3><div className="mt-2 grid gap-1 sm:grid-cols-2">{recent.map((file, index) => <ListEnter key={file.path} index={index}><button type="button" onClick={() => onOpen(file)} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left hover:bg-(--bg-key)"><FileText size={12} className="shrink-0 text-(--color-text-subtle)" /><span className="min-w-0 flex-1 truncate font-mono text-[10px] text-(--color-text-2)">{file.path}</span><span className="text-[8px] text-(--color-text-subtle)">{formatBytes(file.size)}</span></button></ListEnter>)}</div></section>
      </div>
    </div>
  )
}

function KbTreeSkeleton() {
  return <div className="space-y-1" aria-label="Loading knowledge base files">{[0, 1, 1, 2, 2, 1, 2, 2, 0].map((depth, index) => <div key={index} className="flex h-7 items-center gap-1.5" style={{ paddingLeft: `${depth * 12 + 8}px` }}><Skeleton className="h-3 w-3 shrink-0" /><Skeleton className="h-2.5" style={{ width: `${42 + (index % 4) * 11}%` }} /></div>)}</div>
}

function FileContentSkeleton() {
  return <div className="space-y-4" aria-label="Loading file content"><Skeleton className="h-20 w-full" /><Skeleton className="h-5 w-2/5" /><div className="space-y-2.5">{[100, 94, 86, 97, 72, 91, 63, 82].map((width, index) => <Skeleton key={index} className="h-3" style={{ width: `${width}%` }} />)}</div><Skeleton className="h-24 w-full" /></div>
}