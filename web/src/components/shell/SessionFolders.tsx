/**
 * SessionFolders — the FOLDERS tree at the top of the work sidebar.
 *
 * A folder is a user-made grouping of chat sessions. Rows are filed by
 * dragging them onto a folder block (or via "Move to folder…" for touch,
 * see MoveToFolderDialog), and each folder can start a new chat that is
 * created inside it.
 *
 * Sessions filed together also share context: the backend gives every
 * session in a sharing folder a digest of its siblings, so a follow-up chat
 * knows what the others established. The link icon on the folder row toggles
 * that per folder.
 *
 * Session rows themselves are rendered by the parent through
 * `renderSession`, so the sidebar keeps owning rename/delete/pin state and
 * folders never grow a second copy of that logic.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderPlus,
  Link2,
  Link2Off,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { CollapsibleSection } from '@/components/shell/CollapsibleSection'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  useCreateSessionFolderMutation,
  useDeleteSessionFolderMutation,
  useUpdateSessionFolderMutation,
} from '@/queries'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import {
  clearSessionDropTarget,
  isSessionDrag,
  markSessionDropHandled,
  readSessionDragPayload,
  setSessionDropTarget,
} from '@/components/shell/session-drag'
import type { SessionFolder, SessionResponse } from '@/api/types'

interface FolderMenuAnchor {
  folder: SessionFolder
  x: number
  y: number
}

const FOLDER_MENU_WIDTH = 224
const FOLDER_MENU_HEIGHT = 174

function folderMenuPosition(anchor: FolderMenuAnchor): { left: number; top: number } {
  return {
    left: Math.min(
      Math.max(8, anchor.x),
      Math.max(8, window.innerWidth - FOLDER_MENU_WIDTH - 8),
    ),
    top: Math.min(
      Math.max(8, anchor.y),
      Math.max(8, window.innerHeight - FOLDER_MENU_HEIGHT - 8),
    ),
  }
}

function loadExpanded(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.work.foldersExpanded)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

function saveExpanded(ids: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEYS.work.foldersExpanded, JSON.stringify(ids))
  } catch {
    // ignore storage failures
  }
}

interface SessionFoldersProps {
  folders: SessionFolder[]
  isLoading?: boolean
  isError?: boolean
  isMobile?: boolean
  /** Renders one session row — supplied by the sidebar. */
  renderSession: (session: SessionResponse) => ReactNode
  /** Start a new chat filed inside this folder. */
  onNewChatInFolder: (folder: SessionFolder) => void
  /** Called after a row is dropped anywhere on a folder block. */
  onDropSession: (sessionId: string, folderId: string) => void
  /** Load the next page of older chats in a large folder. */
  onLoadMore: (folder: SessionFolder) => void
  loadingFolderId?: string | null
  onRetry?: () => void
}

export function SessionFolders({
  folders,
  isLoading = false,
  isError = false,
  isMobile = false,
  renderSession,
  onNewChatInFolder,
  onDropSession,
  onLoadMore,
  loadingFolderId = null,
  onRetry,
}: SessionFoldersProps) {
  const [sectionCollapsed, setSectionCollapsed] = useState(false)
  const [expanded, setExpanded] = useState<string[]>(() => loadExpanded())
  const [dragOverId, setDragOverId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [renameTarget, setRenameTarget] = useState<SessionFolder | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<SessionFolder | null>(null)
  const [menuAnchor, setMenuAnchor] = useState<FolderMenuAnchor | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const createFolder = useCreateSessionFolderMutation()
  const updateFolder = useUpdateSessionFolderMutation()
  const deleteFolder = useDeleteSessionFolderMutation()

  const expandedSet = useMemo(() => new Set(expanded), [expanded])

  useEffect(() => {
    saveExpanded(expanded)
  }, [expanded])

  useEffect(() => {
    const clearDropTarget = () => setDragOverId(null)
    document.addEventListener('dragend', clearDropTarget)
    document.addEventListener('drop', clearDropTarget)
    return () => {
      document.removeEventListener('dragend', clearDropTarget)
      document.removeEventListener('drop', clearDropTarget)
    }
  }, [])

  useEffect(() => {
    if (!menuAnchor) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setMenuAnchor(null)
        return
      }
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
      const items = Array.from(
        menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [],
      )
      if (items.length === 0) return
      event.preventDefault()
      const current = items.indexOf(document.activeElement as HTMLButtonElement)
      const next =
        event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? items.length - 1
            : event.key === 'ArrowUp'
              ? current <= 0
                ? items.length - 1
                : current - 1
              : current >= items.length - 1
                ? 0
                : current + 1
      items[next]?.focus()
    }
    window.addEventListener('keydown', onKeyDown)
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [menuAnchor])

  const toggleFolder = useCallback((id: string) => {
    setExpanded((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [])

  const submitCreate = () => {
    const name = newName.trim()
    if (!name || createFolder.isPending) return
    createFolder.mutate(name, {
      onSuccess: (folder) => {
        setExpanded((prev) => [...prev, folder.id])
        setNewName('')
        setCreating(false)
      },
    })
  }
  const labelClass = isMobile
    ? 'px-2 pb-0.5 pt-2 text-xs text-(--color-text-subtle)'
    : 'px-2 pb-0.5 pt-1 text-[11px] font-medium text-(--color-text-subtle)'

  return (
    <div className={isMobile ? 'pb-1' : 'pb-0.5'}>
      <CollapsibleSection
        label="Folders"
        collapsed={sectionCollapsed}
        onToggle={() => setSectionCollapsed((v) => !v)}
        count={folders.length || undefined}
        onAdd={() => {
          setSectionCollapsed(false)
          setCreating(true)
        }}
        addLabel="New folder"
        AddIcon={FolderPlus}
        size={isMobile ? 'large' : 'default'}
        className={isMobile ? 'px-2' : 'px-1.5 pb-0.5'}
      />

      {!sectionCollapsed && (
        <div className="space-y-0.5">
          {creating && (
            <div className="px-1.5 pb-1">
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    submitCreate()
                  }
                  if (e.key === 'Escape') {
                    setCreating(false)
                    setNewName('')
                  }
                }}
                onBlur={() => {
                  if (!createFolder.isPending) submitCreate()
                }}
                disabled={createFolder.isPending}
                placeholder="Folder name"
                aria-label="New folder name"
                maxLength={120}
                className="h-7 w-full min-w-0 rounded-md border border-(--color-border) bg-(--bg-page) px-2 text-xs text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
              />
            </div>
          )}

          {isLoading && folders.length === 0 && (
            <p className={labelClass}>Loading folders…</p>
          )}

          {isError && folders.length === 0 && (
            <div className={cn(labelClass, 'flex items-center justify-between gap-2')}>
              <span>Could not load folders</span>
              {onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="rounded-xs p-1 hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label="Retry loading folders"
                >
                  <RefreshCw size={12} aria-hidden="true" />
                </button>
              )}
            </div>
          )}

          {(createFolder.isError || updateFolder.isError || deleteFolder.isError) && (
            <p className="px-3 py-1 text-xs text-(--color-error)" role="status">
              Could not update folders. Please try again.
            </p>
          )}

          {!isLoading && !isError && folders.length === 0 && !creating && (
            <p className={cn(labelClass, 'leading-relaxed')}>
              No folders yet. Create one, then drag chats into it.
            </p>
          )}

          {folders.map((folder) => {
            const isExpanded = expandedSet.has(folder.id)
            const isDropTarget = dragOverId === folder.id
            return (
              <div
                key={folder.id}
                data-session-folder-drop-zone={folder.id}
                className={cn(
                  'rounded-lg transition-colors',
                  isMobile ? 'py-1' : 'py-0.5',
                  isDropTarget && 'bg-(--bg-key)/60 ring-1 ring-(--color-accent)',
                )}
                onDragEnter={(event) => {
                  if (!isSessionDrag(event)) return
                  event.preventDefault()
                  setSessionDropTarget(folder.id)
                  setDragOverId(folder.id)
                }}
                onDragOver={(event) => {
                  if (!isSessionDrag(event)) return
                  event.preventDefault()
                  event.dataTransfer.dropEffect = 'move'
                  setSessionDropTarget(folder.id)
                }}
                onDragLeave={(event) => {
                  // Keep the target active while moving between the header and
                  // any session rows inside an expanded folder.
                  if (event.currentTarget.contains(event.relatedTarget as Node)) return
                  clearSessionDropTarget(folder.id)
                  setDragOverId((prev) => (prev === folder.id ? null : prev))
                }}
                onDrop={(event) => {
                  if (!isSessionDrag(event)) return
                  event.preventDefault()
                  markSessionDropHandled()
                  setDragOverId(null)
                  const sessionId = readSessionDragPayload(event)
                  if (!sessionId) return
                  setExpanded((prev) =>
                    prev.includes(folder.id) ? prev : [...prev, folder.id],
                  )
                  onDropSession(sessionId, folder.id)
                }}
              >
                <div
                  className={cn(
                    'group/folder relative flex items-center rounded-lg pr-1 transition-colors',
                    isMobile ? 'min-h-11' : 'min-h-8',
                    isDropTarget
                      ? 'bg-(--bg-key)'
                      : 'hover:bg-(--bg-key)/50',
                  )}
                  onContextMenu={(event) => {
                    event.preventDefault()
                    setMenuAnchor({ folder, x: event.clientX, y: event.clientY })
                  }}
                >
                  <button
                    type="button"
                    onClick={() => toggleFolder(folder.id)}
                    aria-expanded={isExpanded}
                    className={cn(
                      'flex min-w-0 flex-1 items-center rounded-lg text-left text-(--color-text-2) hover:text-(--color-text)',
                      isMobile
                        ? 'gap-2 px-2.5 py-2.5 text-sm'
                        : 'gap-1.5 px-2.5 py-2 text-xs',
                    )}
                  >
                    {isExpanded ? (
                      <ChevronDown size={isMobile ? 14 : 12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                    ) : (
                      <ChevronRight size={isMobile ? 14 : 12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                    )}
                    <Folder size={isMobile ? 17 : 15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate font-medium">{folder.name}</span>
                    {folder.share_context && (
                      <span title="Shared context on" aria-label="Shared context on">
                        <Link2 size={12} className="shrink-0 text-(--color-accent)" aria-hidden="true" />
                      </span>
                    )}
                    <span className="min-w-4 shrink-0 text-right text-xs tabular-nums text-(--color-text-subtle)">
                      {folder.session_count}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={(event) => {
                      const rect = event.currentTarget.getBoundingClientRect()
                      setMenuAnchor({
                        folder,
                        x: rect.right - FOLDER_MENU_WIDTH,
                        y: rect.bottom + 4,
                      })
                    }}
                    className={cn(
                      'shrink-0 rounded-md text-(--color-text-subtle) opacity-0 transition-opacity hover:bg-(--bg-key) hover:text-(--color-text) group-hover/folder:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100',
                      isMobile ? 'p-1.5' : 'p-1',
                    )}
                    aria-label={`More actions for ${folder.name}`}
                    aria-haspopup="menu"
                    aria-expanded={menuAnchor?.folder.id === folder.id}
                  >
                    <MoreHorizontal size={isMobile ? 15 : 13} aria-hidden="true" />
                  </button>
                </div>

                {isExpanded && (
                  <div className={isMobile ? 'pb-1 pl-5' : 'pb-0.5 pl-1.5'}>
                    {folder.sessions.length === 0 ? (
                      <p className={cn(
                        'text-(--color-text-subtle)',
                        isMobile ? 'px-2.5 py-2 text-sm' : 'px-2 py-1 text-[11px]',
                      )}>
                        Drag chats here
                      </p>
                    ) : (
                      folder.sessions.map((session) => renderSession(session))
                    )}
                    {folder.has_more && (
                      <button
                        type="button"
                        onClick={() => onLoadMore(folder)}
                        disabled={loadingFolderId === folder.id}
                        className={cn(
                          'flex w-full items-center justify-center gap-1.5 rounded-md px-2 text-(--color-text-muted) hover:bg-(--bg-key)/50 hover:text-(--color-text) disabled:opacity-60',
                          isMobile ? 'py-1.5 text-xs' : 'py-1 text-[11px]',
                        )}
                      >
                        {loadingFolderId === folder.id && (
                          <Loader2 size={11} className="animate-spin" aria-hidden="true" />
                        )}
                        {loadingFolderId === folder.id
                          ? 'Loading…'
                          : `Load older chats (${folder.session_count - folder.sessions.length})`}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {menuAnchor && (
        <div
          className="fixed inset-0 z-(--z-modal)"
          onClick={() => setMenuAnchor(null)}
          onContextMenu={(event) => {
            event.preventDefault()
            setMenuAnchor(null)
          }}
        >
          <div
            ref={menuRef}
            role="menu"
            aria-label={`Actions for ${menuAnchor.folder.name}`}
            className="fixed w-56 rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-sm text-(--color-text) shadow-xl"
            style={folderMenuPosition(menuAnchor)}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
              onClick={() => {
                const folder = menuAnchor.folder
                setMenuAnchor(null)
                onNewChatInFolder(folder)
              }}
            >
              <Plus size={15} aria-hidden="true" />
              New chat in folder
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={updateFolder.isPending}
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none disabled:opacity-50"
              onClick={() => {
                const folder = menuAnchor.folder
                setMenuAnchor(null)
                updateFolder.mutate({
                  id: folder.id,
                  share_context: !folder.share_context,
                })
              }}
            >
              {menuAnchor.folder.share_context ? (
                <Link2Off size={15} aria-hidden="true" />
              ) : (
                <Link2 size={15} aria-hidden="true" />
              )}
              {menuAnchor.folder.share_context
                ? 'Turn off shared context'
                : 'Turn on shared context'}
            </button>
            <div className="my-1 border-t border-(--color-border)" role="separator" />
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
              onClick={() => {
                const folder = menuAnchor.folder
                setMenuAnchor(null)
                setRenameTarget(folder)
                setRenameValue(folder.name)
              }}
            >
              <Pencil size={15} aria-hidden="true" />
              Rename folder
            </button>
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-(--color-error) hover:bg-(--color-error-subtle) focus-visible:bg-(--color-error-subtle) focus-visible:outline-none"
              onClick={() => {
                const folder = menuAnchor.folder
                setMenuAnchor(null)
                setDeleteTarget(folder)
              }}
            >
              <Trash2 size={15} aria-hidden="true" />
              Delete folder
            </button>
          </div>
        </div>
      )}

      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRenameTarget(null)
        }}
      >
        <DialogContent showCloseButton={false}>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              const name = renameValue.trim()
              if (!renameTarget || !name) return
              updateFolder.mutate(
                { id: renameTarget.id, name },
                { onSuccess: () => setRenameTarget(null) },
              )
            }}
          >
            <DialogHeader>
              <DialogTitle>Rename folder</DialogTitle>
              <DialogDescription>Folders group related chats in the sidebar.</DialogDescription>
            </DialogHeader>
            <div className="px-3 py-2">
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                aria-label="Folder name"
                maxLength={120}
                className="h-9 w-full min-w-0 rounded-[10px] border border-(--color-border) bg-(--bg-page) px-3 py-1 text-sm text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
              />
            </div>
            <DialogFooter className="p-3">
              <Button type="button" variant="outline" onClick={() => setRenameTarget(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!renameValue.trim() || updateFolder.isPending}>
                {updateFolder.isPending ? 'Saving…' : 'Save'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete “{deleteTarget?.name}”?</DialogTitle>
            <DialogDescription>
              The {deleteTarget?.session_count ?? 0} chat(s) inside move back to the ungrouped
              list — nothing is deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleteFolder.isPending}
              onClick={() => {
                if (!deleteTarget) return
                deleteFolder.mutate(deleteTarget.id, {
                  onSuccess: () => setDeleteTarget(null),
                })
              }}
            >
              {deleteFolder.isPending ? 'Deleting…' : 'Delete folder'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
