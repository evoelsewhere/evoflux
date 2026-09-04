import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Editor from '@monaco-editor/react'
import {
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  FileArchive,
  FilePlus2,
  FolderPlus,
  Loader2,
  PackagePlus,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Save,
  Trash2,
} from 'lucide-react'

import {
  createPluginWorkspaceEntry,
  deletePluginWorkspaceEntry,
  inspectPlugin,
  listPluginWorkspace,
  packPlugin,
  readPluginWorkspaceFile,
  writePluginWorkspaceFile,
} from '@/api/client'
import type { PluginInspection, PluginWorkspaceEntry } from '@/api/types'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useConfirm } from '@/hooks/use-confirm'
import { Input } from '@/components/ui/input'
import { FileTypeIcon, FolderTypeIcon } from '@/components/FileTypeIcon'
import { languageForExt, useMonacoTheme, useSafeMonaco } from '@/hooks/useMonacoTheme'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'

function extension(path: string): string {
  const name = path.split('/').at(-1) ?? path
  const index = name.lastIndexOf('.')
  return index > 0 ? name.slice(index + 1) : name.toLowerCase()
}

interface PluginTreeNode {
  name: string
  path: string
  entry?: PluginWorkspaceEntry
  children: Map<string, PluginTreeNode>
}

function buildPluginTree(entries: PluginWorkspaceEntry[]): PluginTreeNode {
  const root: PluginTreeNode = { name: '/', path: '', children: new Map() }
  for (const entry of entries) {
    const parts = entry.path.split('/')
    let node = root
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join('/')
      let child = node.children.get(part)
      if (!child) {
        child = { name: part, path, children: new Map() }
        node.children.set(part, child)
      }
      if (index === parts.length - 1) child.entry = entry
      node = child
    })
  }
  return root
}

function parentDirectories(path: string): string[] {
  const parts = path.split('/')
  return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'))
}

function PluginTreeNodeView({
  node,
  depth,
  expanded,
  selectedPath,
  onToggle,
  onSelect,
}: {
  node: PluginTreeNode
  depth: number
  expanded: Set<string>
  selectedPath: string
  onToggle: (path: string) => void
  onSelect: (entry: PluginWorkspaceEntry) => void
}) {
  const children = [...node.children.values()].sort((left, right) => {
    const leftDirectory = left.entry?.kind !== 'file'
    const rightDirectory = right.entry?.kind !== 'file'
    if (leftDirectory !== rightDirectory) return leftDirectory ? -1 : 1
    return left.name.localeCompare(right.name)
  })

  return children.map((child) => {
    const isDirectory = child.entry?.kind !== 'file'
    const isExpanded = expanded.has(child.path)
    const isSelected = selectedPath === child.path
    const entry = child.entry ?? {
      path: child.path,
      name: child.name,
      kind: 'directory' as const,
      size: 0,
    }
    return (
      <div key={child.path}>
        <button
          type="button"
          onClick={() => {
            onSelect(entry)
            if (isDirectory) onToggle(child.path)
          }}
          className={cn(
            'flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left font-mono text-xs transition-colors',
            isSelected
              ? 'bg-(--bg-key) text-(--color-accent)'
              : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
          )}
          style={{ paddingLeft: 6 + depth * 14 }}
          title={child.path}
          aria-expanded={isDirectory ? isExpanded : undefined}
        >
          {isDirectory ? (
            <>
              <ChevronRight
                size={11}
                className={cn('shrink-0 transition-transform', isExpanded && 'rotate-90')}
                aria-hidden="true"
              />
              <FolderTypeIcon open={isExpanded} size={14} />
            </>
          ) : (
            <>
              <span className="w-[11px] shrink-0" />
              <FileTypeIcon name={child.name} size={14} />
            </>
          )}
          <span className="min-w-0 flex-1 truncate">{child.name}</span>
        </button>
        {isDirectory && isExpanded && (
          <PluginTreeNodeView
            node={child}
            depth={depth + 1}
            expanded={expanded}
            selectedPath={selectedPath}
            onToggle={onToggle}
            onSelect={onSelect}
          />
        )}
      </div>
    )
  })
}

export function PluginWorkspaceEditor({
  root,
  name,
  linked,
  onBack,
  onInspection,
  onLink,
}: {
  root: string
  name: string
  linked: boolean
  onBack: () => void
  onInspection: (inspection: PluginInspection) => void
  onLink: () => Promise<void>
}) {
  const pushToast = useToastStore((state) => state.push)
  const monaco = useSafeMonaco()
  const theme = useMonacoTheme(monaco)
  const [selectedPath, setSelectedPath] = useState('plugin.json')
  const [savedContent, setSavedContent] = useState('')
  const [content, setContent] = useState('')
  const [fileLoading, setFileLoading] = useState(true)
  const [fileError, setFileError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [newKind, setNewKind] = useState<'file' | 'directory' | null>(null)
  const [newPath, setNewPath] = useState('')
  const [treeVisible, setTreeVisible] = useState(true)
  const [expandedDirectories, setExpandedDirectories] = useState<Set<string>>(new Set())
  const [treeInitializedFor, setTreeInitializedFor] = useState<string | null>(null)
  const [focusedPath, setFocusedPath] = useState('plugin.json')
  const {
    request: confirmRequest,
    confirm: confirmAction,
    close: closeConfirm,
  } = useConfirm()

  const tree = useQuery({
    queryKey: ['plugin-workspace', root],
    queryFn: () => listPluginWorkspace(root),
  })
  const focusedEntry = useMemo(
    () => (tree.data ?? []).find((entry) => entry.path === focusedPath),
    [focusedPath, tree.data],
  )
  const entries = useMemo(() => tree.data ?? [], [tree.data])
  const pluginTree = useMemo(() => buildPluginTree(entries), [entries])
  const dirty = content !== savedContent

  useEffect(() => {
    if (!tree.data || treeInitializedFor === root) return
    setExpandedDirectories(new Set(
      tree.data.filter((entry) => entry.kind === 'directory').map((entry) => entry.path),
    ))
    setTreeInitializedFor(root)
  }, [root, tree.data, treeInitializedFor])

  // The dialog answers asynchronously, so a discard guard cannot return a
  // boolean the way `window.confirm` did. It takes the continuation
  // instead, and runs it straight away when there is nothing to lose.
  const guardDiscard = useCallback((proceed: () => void) => {
    if (!dirty) {
      proceed()
      return
    }
    confirmAction({
      title: 'Discard unsaved changes?',
      description: `${selectedPath} has edits that were never saved. They are lost if you leave now.`,
      confirmLabel: 'Discard changes',
      cancelLabel: 'Keep editing',
      destructive: true,
      onConfirm: proceed,
    })
  }, [confirmAction, dirty, selectedPath])

  const selectFile = useCallback((path: string) => {
    if (path === selectedPath) return
    guardDiscard(() => {
      setFocusedPath(path)
      setSelectedPath(path)
    })
  }, [guardDiscard, selectedPath])

  const selectTreeEntry = useCallback((entry: PluginWorkspaceEntry) => {
    setFocusedPath(entry.path)
    if (entry.kind === 'file') selectFile(entry.path)
  }, [selectFile])

  const toggleDirectory = useCallback((path: string) => {
    setExpandedDirectories((previous) => {
      const next = new Set(previous)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  useEffect(() => {
    const parents = parentDirectories(selectedPath)
    if (parents.length === 0) return
    setExpandedDirectories((previous) => {
      if (parents.every((path) => previous.has(path))) return previous
      return new Set([...previous, ...parents])
    })
  }, [selectedPath])

  useEffect(() => {
    if (!dirty) return
    const preventUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', preventUnload)
    return () => window.removeEventListener('beforeunload', preventUnload)
  }, [dirty])

  useEffect(() => {
    let cancelled = false
    setFileLoading(true)
    setFileError(null)
    readPluginWorkspaceFile(root, selectedPath)
      .then((result) => {
        if (cancelled) return
        setSavedContent(result.content)
        setContent(result.content)
        setFileLoading(false)
      })
      .catch((error) => {
        if (cancelled) return
        setSavedContent('')
        setContent('')
        setFileError(error instanceof Error ? error.message : String(error))
        setFileLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [root, selectedPath])

  const run = async (label: string, action: () => Promise<void>) => {
    setBusy(label)
    try {
      await action()
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Plugin development action failed',
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    if (!dirty || busy) return
    await run('save', async () => {
      const result = await writePluginWorkspaceFile(root, selectedPath, content)
      setSavedContent(content)
      onInspection(result.inspection)
      pushToast({ tone: 'success', title: `${selectedPath} saved` })
      await tree.refetch()
    })
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void save()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  })

  const createEntry = () => {
    const path = newPath.trim().replace(/^\/+|\/+$/g, '')
    if (!newKind || !path) return
    const create = () => void run('create-entry', async () => {
      const result = await createPluginWorkspaceEntry(root, path, newKind)
      onInspection(result.inspection)
      setNewKind(null)
      setNewPath('')
      await tree.refetch()
      if (newKind === 'file') {
        setFocusedPath(path)
        setSelectedPath(path)
      }
    })
    // Creating a file opens it, which would drop the current buffer.
    if (newKind === 'file') guardDiscard(create)
    else create()
  }

  const requestDeleteEntry = () => {
    if (!focusedEntry || focusedEntry.path === 'plugin.json') return
    confirmAction({
      title: `Delete ${focusedEntry.path}?`,
      description: focusedEntry.kind === 'directory'
        ? 'The folder and everything inside it are removed from the plugin package. This cannot be undone.'
        : 'The file is removed from the plugin package. This cannot be undone.',
      confirmLabel: 'Delete',
      destructive: true,
      onConfirm: () => void deleteEntry(),
    })
  }

  const deleteEntry = async () => {
    if (!focusedEntry || focusedEntry.path === 'plugin.json') return
    await run('delete-entry', async () => {
      const result = await deletePluginWorkspaceEntry(root, focusedEntry.path)
      onInspection(result.inspection)
      if (focusedEntry.kind === 'file') setSelectedPath('plugin.json')
      setFocusedPath('plugin.json')
      await tree.refetch()
    })
  }

  const validate = async () => {
    await run('validate', async () => {
      const result = await inspectPlugin(root)
      onInspection(result)
      pushToast({
        tone: result.valid ? 'success' : 'error',
        title: result.valid ? 'Plugin is valid' : 'Plugin validation failed',
      })
    })
  }

  const pack = async () => {
    await run('pack', async () => {
      const result = await packPlugin(root)
      pushToast({ tone: 'success', title: 'Plugin archive created', description: result.path })
    })
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <div className="border-b border-(--color-border) px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => guardDiscard(onBack)}
              className="mb-1 inline-flex items-center gap-1 text-xs text-(--color-text-muted) hover:text-(--color-text)"
            >
              <ArrowLeft size={13} /> Plugin Center
            </button>
            <h3 className="truncate font-semibold text-(--color-text)">{name}</h3>
            <p className="truncate font-mono text-[11px] text-(--color-text-subtle)" title={root}>{root}</p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {!linked && (
              <Button size="sm" onClick={() => void run('link', onLink)} disabled={busy !== null || dirty}>
                <PackagePlus /> Link
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => void validate()} disabled={busy !== null || dirty}>
              <CheckCircle2 /> Validate
            </Button>
            <Button size="sm" variant="outline" onClick={() => void pack()} disabled={busy !== null || dirty}>
              <FileArchive /> Pack
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => setTreeVisible((visible) => !visible)}
              aria-label={treeVisible ? 'Hide plugin file tree' : 'Show plugin file tree'}
              title={treeVisible ? 'Hide file tree' : 'Show file tree'}
              aria-pressed={treeVisible}
            >
              {treeVisible ? <PanelRightClose /> : <PanelRightOpen />}
            </Button>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
        <main className="order-1 flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex min-h-10 items-center justify-between gap-2 border-b border-(--color-border) px-3 py-1.5">
            <div className="min-w-0">
              <span className="truncate font-mono text-xs text-(--color-text-2)">{selectedPath}</span>
              {dirty && <span className="ml-2 text-[11px] text-(--color-warning)">unsaved</span>}
            </div>
            <div className="flex shrink-0 gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={requestDeleteEntry}
                disabled={!focusedEntry || focusedPath === 'plugin.json' || busy !== null}
                aria-label="Delete selected plugin entry"
              >
                <Trash2 />
              </Button>
              <Button size="sm" onClick={() => void save()} disabled={!dirty || busy !== null || fileLoading || !!fileError}>
                {busy === 'save' ? <Loader2 className="animate-spin" /> : <Save />} Save
              </Button>
            </div>
          </div>
          <div className="min-h-80 flex-1 overflow-hidden">
            {fileLoading ? (
              <div className="flex h-full items-center justify-center"><Loader2 className="animate-spin text-(--color-text-subtle)" /></div>
            ) : fileError ? (
              <div className="flex h-full items-center justify-center p-6 text-center text-sm text-(--color-error)">{fileError}</div>
            ) : (
              <Editor
                height="100%"
                path={`${root}/${selectedPath}`}
                value={content}
                language={languageForExt(extension(selectedPath))}
                theme={theme}
                onChange={(value) => setContent(value ?? '')}
                options={{
                  ariaLabel: `${selectedPath} plugin source editor`,
                  automaticLayout: true,
                  fontSize: 13,
                  lineHeight: 20,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  tabSize: 2,
                  wordWrap: 'off',
                }}
              />
            )}
          </div>
        </main>

        {treeVisible && <aside className="order-3 flex min-h-40 w-full shrink-0 flex-col border-t border-(--color-border) bg-(--bg-card) md:min-h-0 md:w-60 md:border-t-0 md:border-l">
          <div className="flex items-center justify-between border-b border-(--color-border) px-2 py-1.5">
            <span className="text-[11px] font-semibold tracking-wide text-(--color-text-muted) uppercase">Files</span>
            <div className="flex gap-0.5">
              <Button variant="ghost" size="icon-sm" onClick={() => setNewKind('file')} aria-label="New plugin file">
                <FilePlus2 />
              </Button>
              <Button variant="ghost" size="icon-sm" onClick={() => setNewKind('directory')} aria-label="New plugin folder">
                <FolderPlus />
              </Button>
              <Button variant="ghost" size="icon-sm" onClick={() => void tree.refetch()} aria-label="Refresh plugin files">
                <RefreshCw className={cn(tree.isFetching && 'animate-spin')} />
              </Button>
            </div>
          </div>
          {newKind && (
            <div className="space-y-1.5 border-b border-(--color-border) p-2">
              <Input
                autoFocus
                value={newPath}
                onChange={(event) => setNewPath(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') createEntry()
                  if (event.key === 'Escape') setNewKind(null)
                }}
                placeholder={newKind === 'file' ? 'path/file.ts' : 'path/folder'}
                aria-label={`New plugin ${newKind} path`}
              />
              <div className="flex justify-end gap-1">
                <Button size="sm" variant="ghost" onClick={() => setNewKind(null)}>Cancel</Button>
                <Button size="sm" onClick={createEntry} disabled={!newPath.trim() || busy !== null}>Add</Button>
              </div>
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-auto p-1.5">
            {tree.isLoading ? (
              <div className="flex justify-center py-6"><Loader2 className="animate-spin text-(--color-text-subtle)" size={15} /></div>
            ) : tree.isError ? (
              <p className="p-2 text-xs text-(--color-error)">Could not load plugin files.</p>
            ) : (
              <PluginTreeNodeView
                node={pluginTree}
                depth={0}
                expanded={expandedDirectories}
                selectedPath={focusedPath}
                onToggle={toggleDirectory}
                onSelect={selectTreeEntry}
              />
            )}
          </div>
        </aside>}
      </div>
      <ConfirmDialog request={confirmRequest} onClose={closeConfirm} />
    </div>
  )
}
