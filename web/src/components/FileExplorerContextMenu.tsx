/**
 * FileExplorerContextMenu — the right-click menu shared by every file tree.
 *
 * One menu serves Work mode (``WorkspaceFilesPanel``), Code mode's HTTP tree
 * (``CodingWorkspacePanel``/``MultiRepoFileTree``) and Code mode's native
 * Tauri tree (``NativeFileTree``). Each tree passes the clicked entry plus
 * the capabilities it can actually provide; items with no handler are hidden
 * rather than shown disabled, so a tree that cannot rename never advertises
 * renaming.
 *
 * Naming and destructive prompts live here too — that keeps three trees from
 * growing three inline rename editors and three delete confirmations.
 */
import { useState, type ReactNode } from 'react'
import {
  AppWindow,
  AtSign,
  Copy,
  CopyPlus,
  Download,
  Eye,
  ExternalLink,
  FilePlus2,
  FileText,
  FolderPlus,
  Loader2,
  LocateFixed,
  Pencil,
  RefreshCw,
  Trash2,
} from 'lucide-react'

import { tauriOpenWorkspaceWith, type WorkspaceOpener } from '@/api/tauri-workspace'
import { usePlatform } from '@/hooks/use-platform'
import { useConfirm } from '@/hooks/use-confirm'
import {
  absoluteWorkspacePath,
  openerDescription,
  revealLabel,
  saveCopyLabel,
} from '@/lib/workspace-openers'
import { useWorkspaceOpenersQuery } from '@/queries/useWorkspaceOpenersQuery'
import { useToastStore } from '@/stores/useToastStore'
import { errorMessage } from '@/utils/errors'
import { Button } from './ui/button'
import { ConfirmDialog } from './ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'
import { OpenerIcon } from './workbench/OpenerIcon'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from './ui/context-menu'

/** The tree row the menu was opened on. */
export interface FileExplorerEntry {
  /** POSIX path relative to the tree's root. */
  path: string
  name: string
  isDirectory: boolean
  /** Metadata the tree already knows, when it has it (native listings do). */
  size?: number
  mtime?: number
  mime?: string
}

export interface FileExplorerMenuActions {
  /** Absolute workspace root — enables absolute paths, reveal and "Open in". */
  root?: string | null
  /** Show the entry in the panel's preview pane. */
  onPreview?: (entry: FileExplorerEntry) => void
  /** Hand the entry to the OS default application. */
  onOpenExternally?: (entry: FileExplorerEntry) => void | Promise<void>
  /** Reveal the entry in Finder / File Explorer. */
  onReveal?: (entry: FileExplorerEntry) => void | Promise<void>
  /** Read the entry's text for "Copy contents"; omit to hide that item. */
  readText?: (entry: FileExplorerEntry) => Promise<string>
  onDownload?: (entry: FileExplorerEntry) => void | Promise<void>
  /** Create ``name`` inside ``parentDir`` (empty string = tree root). */
  onCreate?: (parentDir: string, name: string, kind: 'file' | 'directory') => Promise<void>
  /** Rename in place — ``name`` is a bare filename, not a path. */
  onRename?: (entry: FileExplorerEntry, name: string) => Promise<void>
  /** Copy the entry beside itself under ``name``. */
  onDuplicate?: (entry: FileExplorerEntry, name: string) => Promise<void>
  onDelete?: (entry: FileExplorerEntry) => Promise<void>
}

interface NamePrompt {
  title: string
  confirmLabel: string
  initialValue: string
  /** Preselect only this many leading characters (the name without extension). */
  selectionEnd?: number
  run: (name: string) => Promise<void>
}

/** POSIX dirname — empty string when the path has no directory part. */
function parentDirectory(path: string): string {
  const index = path.lastIndexOf('/')
  return index < 0 ? '' : path.slice(0, index)
}

/** Index where a filename's extension starts (its length when there is none). */
function nameSelectionEnd(name: string): number {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? dot : name.length
}

/** ``report.md`` becomes ``report copy.md``. */
function duplicateName(name: string): string {
  const dot = nameSelectionEnd(name)
  return `${name.slice(0, dot)} copy${name.slice(dot)}`
}

function OpenWithSubmenuItems({
  root,
  entry,
}: {
  root: string
  entry: FileExplorerEntry
}) {
  const pushToast = useToastStore((state) => state.push)
  // Mounted only while the submenu is open, so app detection is paid for by
  // the users who actually reach for it. The query caches indefinitely per OS.
  const openersQuery = useWorkspaceOpenersQuery(true)
  const openers = openersQuery.data ?? []

  const openWith = async (opener: WorkspaceOpener) => {
    try {
      await tauriOpenWorkspaceWith(root, opener.id, entry.path)
    } catch (error) {
      pushToast({
        tone: 'error',
        title: `Could not open ${opener.name}`,
        description: errorMessage(error),
      })
    }
  }

  if (openersQuery.isLoading) {
    return (
      <ContextMenuItem disabled>
        <Loader2 size={14} className="animate-spin" />
        <span>Detecting apps…</span>
      </ContextMenuItem>
    )
  }
  if (openersQuery.isError && openers.length === 0) {
    return (
      <ContextMenuItem closeOnClick={false} onClick={() => void openersQuery.refetch()}>
        <RefreshCw size={14} />
        <span>Retry app detection</span>
      </ContextMenuItem>
    )
  }
  if (openers.length === 0) {
    return (
      <ContextMenuItem disabled>
        <span>No supported apps found</span>
      </ContextMenuItem>
    )
  }

  return (
    <>
      {openers.map((opener) => (
        <ContextMenuItem key={opener.id} onClick={() => void openWith(opener)} className="gap-2.5 pl-1">
          <OpenerIcon opener={opener} size={5} />
          <span className="min-w-0 flex-1">
            <span className="block truncate">{opener.name}</span>
            <span className="block text-[10px] leading-3 text-(--color-text-subtle)">
              {openerDescription(opener)}
            </span>
          </span>
        </ContextMenuItem>
      ))}
    </>
  )
}

function NamePromptDialog({
  prompt,
  onClose,
}: {
  prompt: NamePrompt
  onClose: () => void
}) {
  const [value, setValue] = useState(prompt.initialValue)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const trimmed = value.trim()
  const invalid = !trimmed || trimmed === '.' || trimmed === '..' || /[\\/]/.test(trimmed)

  const submit = async () => {
    if (invalid || busy) return
    setBusy(true)
    setError(null)
    try {
      await prompt.run(trimmed)
      onClose()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{prompt.title}</DialogTitle>
        </DialogHeader>
        <input
          autoFocus
          value={value}
          disabled={busy}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              void submit()
            }
          }}
          onFocus={(event) => {
            // Preselect the stem so typing replaces the name but keeps the
            // extension, the way an editor's rename field behaves.
            const end = prompt.selectionEnd ?? value.length
            event.currentTarget.setSelectionRange(0, end)
          }}
          aria-label={prompt.title}
          className="w-full rounded-md border border-(--color-border) bg-(--bg-page) px-2 py-1.5 font-mono text-sm text-(--color-text) outline-none focus:border-(--focus-ring)"
        />
        {error && <p className="text-xs text-(--color-error)">{error}</p>}
        <DialogFooter>
          <Button variant="ghost" disabled={busy} onClick={onClose}>Cancel</Button>
          <Button disabled={busy || invalid} onClick={() => void submit()}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : prompt.confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function FileExplorerContextMenu({
  entry,
  actions,
  children,
  className,
}: {
  entry: FileExplorerEntry
  actions: FileExplorerMenuActions
  children: ReactNode
  className?: string
}) {
  const { isTauri, os } = usePlatform()
  const pushToast = useToastStore((state) => state.push)
  const [prompt, setPrompt] = useState<NamePrompt | null>(null)
  const [deleting, setDeleting] = useState(false)
  const { request: confirmRequest, confirm, close: closeConfirm } = useConfirm()
  const root = actions.root ?? null
  const isFile = !entry.isDirectory
  // "New file/folder" lands inside a folder, or beside a clicked file.
  const createParent = entry.isDirectory ? entry.path : parentDirectory(entry.path)

  const report = (title: string, error: unknown) => {
    pushToast({ tone: 'error', title, description: errorMessage(error) })
  }

  const copyText = async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch (error) {
      report(`Could not copy ${label}`, error)
    }
  }

  const copyContents = async () => {
    if (!actions.readText) return
    try {
      await navigator.clipboard.writeText(await actions.readText(entry))
    } catch (error) {
      report('Could not copy file contents', error)
    }
  }

  const attachAsContext = () => {
    // Reuses the terminal → composer channel, so any tree can drop an
    // @-mention into the chat draft without threading a ref through panels.
    window.dispatchEvent(
      new CustomEvent('evoflux:composer-insert', { detail: { text: `@${entry.path}` } }),
    )
  }

  const runAction = async (title: string, action: () => void | Promise<void>) => {
    try {
      await action()
    } catch (error) {
      report(title, error)
    }
  }

  const requestDelete = () => {
    const onDelete = actions.onDelete
    if (!onDelete) return
    confirm({
      title: `Delete ${entry.name}?`,
      description: entry.isDirectory
        ? `${entry.path} and everything inside it will be deleted from disk. This cannot be undone.`
        : `${entry.path} will be deleted from disk. This cannot be undone.`,
      confirmLabel: 'Delete',
      destructive: true,
      onConfirm: () => {
        setDeleting(true)
        void Promise.resolve(onDelete(entry))
          .catch((error: unknown) => report(`Could not delete ${entry.name}`, error))
          .finally(() => setDeleting(false))
      },
    })
  }

  const canReveal = isTauri && root !== null && actions.onReveal !== undefined
  const canOpenWith = isTauri && root !== null
  const hasMutations = Boolean(
    actions.onCreate || actions.onRename || actions.onDuplicate || actions.onDelete,
  )

  return (
    <>
      <ContextMenu>
        <ContextMenuTrigger className={className}>{children}</ContextMenuTrigger>
        <ContextMenuContent aria-label={`Actions for ${entry.name}`}>
          <ContextMenuItem onClick={attachAsContext}>
            <AtSign size={14} />
            Attach as context
          </ContextMenuItem>
          {isFile && actions.onPreview && (
            <ContextMenuItem onClick={() => actions.onPreview?.(entry)}>
              <Eye size={14} />
              Preview
            </ContextMenuItem>
          )}

          {(actions.onOpenExternally || canOpenWith || canReveal) && <ContextMenuSeparator />}
          {actions.onOpenExternally && isFile && (
            <ContextMenuItem
              onClick={() => void runAction(
                `Could not open ${entry.name}`,
                () => actions.onOpenExternally?.(entry),
              )}
            >
              <ExternalLink size={14} />
              Open in default app
            </ContextMenuItem>
          )}
          {canOpenWith && root && (
            <ContextMenuSub>
              <ContextMenuSubTrigger>
                <AppWindow size={14} />
                Open in
              </ContextMenuSubTrigger>
              <ContextMenuSubContent>
                <ContextMenuLabel>Open {entry.isDirectory ? 'folder' : 'file'} in</ContextMenuLabel>
                <OpenWithSubmenuItems root={root} entry={entry} />
              </ContextMenuSubContent>
            </ContextMenuSub>
          )}
          {canReveal && (
            <ContextMenuItem
              onClick={() => void runAction(
                'Could not open the file manager',
                () => actions.onReveal?.(entry),
              )}
            >
              <LocateFixed size={14} />
              {revealLabel(os)}
            </ContextMenuItem>
          )}

          <ContextMenuSeparator />
          <ContextMenuSub>
            <ContextMenuSubTrigger>
              <Copy size={14} />
              Copy
            </ContextMenuSubTrigger>
            <ContextMenuSubContent>
              <ContextMenuItem onClick={() => void copyText('the name', entry.name)}>
                <FileText size={14} />
                Name
              </ContextMenuItem>
              <ContextMenuItem onClick={() => void copyText('the path', entry.path)}>
                <Copy size={14} />
                Relative path
              </ContextMenuItem>
              {root && (
                <ContextMenuItem
                  onClick={() => void copyText('the path', absoluteWorkspacePath(root, entry.path))}
                >
                  <Copy size={14} />
                  Absolute path
                </ContextMenuItem>
              )}
              {isFile && actions.readText && (
                <ContextMenuItem onClick={() => void copyContents()}>
                  <FileText size={14} />
                  File contents
                </ContextMenuItem>
              )}
            </ContextMenuSubContent>
          </ContextMenuSub>
          {isFile && actions.onDownload && (
            <ContextMenuItem
              onClick={() => void runAction(
                `Could not download ${entry.name}`,
                () => actions.onDownload?.(entry),
              )}
            >
              <Download size={14} />
              {saveCopyLabel(isTauri)}
            </ContextMenuItem>
          )}

          {hasMutations && <ContextMenuSeparator />}
          {actions.onCreate && (
            <>
              <ContextMenuItem
                onClick={() => setPrompt({
                  title: `New file in ${createParent || 'workspace root'}`,
                  confirmLabel: 'Create',
                  initialValue: '',
                  run: (name) => actions.onCreate!(createParent, name, 'file'),
                })}
              >
                <FilePlus2 size={14} />
                New file…
              </ContextMenuItem>
              <ContextMenuItem
                onClick={() => setPrompt({
                  title: `New folder in ${createParent || 'workspace root'}`,
                  confirmLabel: 'Create',
                  initialValue: '',
                  run: (name) => actions.onCreate!(createParent, name, 'directory'),
                })}
              >
                <FolderPlus size={14} />
                New folder…
              </ContextMenuItem>
            </>
          )}
          {actions.onRename && (
            <ContextMenuItem
              onClick={() => setPrompt({
                title: `Rename ${entry.name}`,
                confirmLabel: 'Rename',
                initialValue: entry.name,
                selectionEnd: nameSelectionEnd(entry.name),
                run: (name) => actions.onRename!(entry, name),
              })}
            >
              <Pencil size={14} />
              Rename…
            </ContextMenuItem>
          )}
          {actions.onDuplicate && (
            <ContextMenuItem
              onClick={() => setPrompt({
                title: `Duplicate ${entry.name}`,
                confirmLabel: 'Duplicate',
                initialValue: duplicateName(entry.name),
                selectionEnd: nameSelectionEnd(duplicateName(entry.name)),
                run: (name) => actions.onDuplicate!(entry, name),
              })}
            >
              <CopyPlus size={14} />
              Duplicate…
            </ContextMenuItem>
          )}
          {actions.onDelete && (
            <ContextMenuItem variant="destructive" disabled={deleting} onClick={requestDelete}>
              {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              Delete…
            </ContextMenuItem>
          )}
        </ContextMenuContent>
      </ContextMenu>
      {prompt && <NamePromptDialog prompt={prompt} onClose={() => setPrompt(null)} />}
      <ConfirmDialog request={confirmRequest} onClose={closeConfirm} />
    </>
  )
}
