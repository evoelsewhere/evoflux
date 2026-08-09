import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Editor, { useMonaco } from '@monaco-editor/react'
import {
  ArrowLeft,
  CheckCircle2,
  FileArchive,
  FilePlus2,
  FolderPlus,
  Loader2,
  PackagePlus,
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
import { Input } from '@/components/ui/input'
import { FileTypeIcon, FolderTypeIcon } from '@/components/FileTypeIcon'
import { languageForExt, useMonacoTheme } from '@/hooks/useMonacoTheme'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'

function extension(path: string): string {
  const name = path.split('/').at(-1) ?? path
  const index = name.lastIndexOf('.')
  return index > 0 ? name.slice(index + 1) : name.toLowerCase()
}

function entryDepth(entry: PluginWorkspaceEntry): number {
  return Math.max(0, entry.path.split('/').length - 1)
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
  const monaco = useMonaco()
  const theme = useMonacoTheme(monaco)
  const [selectedPath, setSelectedPath] = useState('plugin.json')
  const [savedContent, setSavedContent] = useState('')
  const [content, setContent] = useState('')
  const [fileLoading, setFileLoading] = useState(true)
  const [fileError, setFileError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [newKind, setNewKind] = useState<'file' | 'directory' | null>(null)
  const [newPath, setNewPath] = useState('')

  const tree = useQuery({
    queryKey: ['plugin-workspace', root],
    queryFn: () => listPluginWorkspace(root),
  })
  const selectedEntry = useMemo(
    () => (tree.data ?? []).find((entry) => entry.path === selectedPath),
    [tree.data, selectedPath],
  )
  const entries = tree.data ?? []
  const dirty = content !== savedContent

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

  const createEntry = async () => {
    const path = newPath.trim().replace(/^\/+|\/+$/g, '')
    if (!newKind || !path) return
    await run('create-entry', async () => {
      const result = await createPluginWorkspaceEntry(root, path, newKind)
      onInspection(result.inspection)
      setNewKind(null)
      setNewPath('')
      await tree.refetch()
      if (newKind === 'file') setSelectedPath(path)
    })
  }

  const deleteEntry = async () => {
    if (!selectedEntry || selectedEntry.path === 'plugin.json') return
    if (!window.confirm(`Delete ${selectedEntry.path}?`)) return
    await run('delete-entry', async () => {
      const result = await deletePluginWorkspaceEntry(root, selectedEntry.path)
      onInspection(result.inspection)
      setSelectedPath('plugin.json')
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
              onClick={onBack}
              className="mb-1 inline-flex items-center gap-1 text-xs text-(--color-text-muted) hover:text-(--color-text)"
            >
              <ArrowLeft size={13} /> Plugin Center
            </button>
            <h3 className="truncate font-semibold text-(--color-text)">{name}</h3>
            <p className="truncate font-mono text-[11px] text-(--color-text-subtle)" title={root}>{root}</p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {!linked && (
              <Button size="sm" onClick={() => void run('link', onLink)} disabled={busy !== null}>
                <PackagePlus /> Link
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => void validate()} disabled={busy !== null}>
              <CheckCircle2 /> Validate
            </Button>
            <Button size="sm" variant="outline" onClick={() => void pack()} disabled={busy !== null}>
              <FileArchive /> Pack
            </Button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[180px_minmax(0,1fr)]">
        <aside className="flex min-h-40 flex-col border-b border-(--color-border) bg-(--bg-card) md:min-h-0 md:border-r md:border-b-0">
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
                  if (event.key === 'Enter') void createEntry()
                  if (event.key === 'Escape') setNewKind(null)
                }}
                placeholder={newKind === 'file' ? 'path/file.ts' : 'path/folder'}
                aria-label={`New plugin ${newKind} path`}
              />
              <div className="flex justify-end gap-1">
                <Button size="sm" variant="ghost" onClick={() => setNewKind(null)}>Cancel</Button>
                <Button size="sm" onClick={() => void createEntry()} disabled={!newPath.trim() || busy !== null}>Add</Button>
              </div>
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-auto p-1.5">
            {tree.isLoading ? (
              <div className="flex justify-center py-6"><Loader2 className="animate-spin text-(--color-text-subtle)" size={15} /></div>
            ) : tree.isError ? (
              <p className="p-2 text-xs text-(--color-error)">Could not load plugin files.</p>
            ) : entries.map((entry) => (
              <button
                key={entry.path}
                type="button"
                disabled={entry.kind === 'directory'}
                onClick={() => entry.kind === 'file' && setSelectedPath(entry.path)}
                className={cn(
                  'flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left font-mono text-xs',
                  selectedPath === entry.path
                    ? 'bg-(--bg-key) text-(--color-accent)'
                    : 'text-(--color-text-2) hover:bg-(--bg-key)',
                  entry.kind === 'directory' && 'cursor-default text-(--color-text-muted)',
                )}
                style={{ paddingLeft: 6 + entryDepth(entry) * 12 }}
                title={entry.path}
              >
                {entry.kind === 'directory'
                  ? <FolderTypeIcon open size={14} />
                  : <FileTypeIcon name={entry.name} size={14} />}
                <span className="truncate">{entry.name}</span>
              </button>
            ))}
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-col">
          <div className="flex min-h-10 items-center justify-between gap-2 border-b border-(--color-border) px-3 py-1.5">
            <div className="min-w-0">
              <span className="truncate font-mono text-xs text-(--color-text-2)">{selectedPath}</span>
              {dirty && <span className="ml-2 text-[11px] text-(--color-warning)">unsaved</span>}
            </div>
            <div className="flex shrink-0 gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => void deleteEntry()}
                disabled={!selectedEntry || selectedPath === 'plugin.json' || busy !== null}
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
      </div>
    </div>
  )
}
