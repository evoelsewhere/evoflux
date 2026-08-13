/**
 * SessionContextMenu — the per-session action surfaces shared by the mode
 * sidebars, extracted from Sidebar.tsx (identical copies also lived in
 * CodingSidebar.tsx):
 *
 *   - `SessionContextMenu`: desktop right-click menu — a fixed-position
 *     floating card anchored at the pointer, dismissed by clicking the
 *     backdrop, pressing Escape, or right-clicking again.
 *   - `SessionActionsDialog`: mobile counterpart — a modal Dialog with the
 *     same actions, triggered by long-press.
 *
 * Both expose Edit title / Delete session; pass `pinned` + `onTogglePin` to
 * add a Pin/Unpin item above the destructive action (hidden unless
 * `onTogglePin` is provided).
 */

import { useEffect, useMemo, useRef } from 'react'
import { Copy, FolderInput, Pencil, Pin, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { SessionResponse } from '@/api/types'

export interface SessionMenuAnchor {
  session: SessionResponse
  x: number
  y: number
}

interface SessionMenuActions {
  onEdit: (session: SessionResponse) => void
  onDelete: (session: SessionResponse) => void
  /** The "Duplicate" item renders only when this is provided. */
  onDuplicate?: (session: SessionResponse) => void
  /** Pin state of the target session — controls the Pin/Unpin label. */
  pinned?: boolean
  /** The Pin/Unpin item renders only when this is provided. */
  onTogglePin?: () => void
  /** The "Move to folder…" item renders only when this is provided. */
  onMoveToFolder?: (session: SessionResponse) => void
}

interface SessionContextMenuProps extends SessionMenuActions {
  /** Anchor position; null closes the menu. */
  anchor: SessionMenuAnchor | null
  onClose: () => void
}

/** Approximate menu size for viewport clamping before first paint. */
const MENU_WIDTH = 176
const MENU_HEIGHT = 148
const MENU_ITEM_HEIGHT = 34

function clampMenuPosition(
  x: number,
  y: number,
  menuHeight: number,
): { left: number; top: number } {
  const maxLeft = Math.max(8, window.innerWidth - MENU_WIDTH - 8)
  const maxTop = Math.max(8, window.innerHeight - menuHeight - 8)
  return {
    left: Math.min(Math.max(8, x), maxLeft),
    top: Math.min(Math.max(8, y), maxTop),
  }
}

export function SessionContextMenu({
  anchor,
  onClose,
  onEdit,
  onDelete,
  onDuplicate,
  pinned,
  onTogglePin,
  onMoveToFolder,
}: SessionContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const position = useMemo(() => {
    if (!anchor) return null
    const height = MENU_HEIGHT
      + (onDuplicate ? MENU_ITEM_HEIGHT : 0)
      + (onMoveToFolder ? MENU_ITEM_HEIGHT : 0)
    return clampMenuPosition(anchor.x, anchor.y, height)
  }, [anchor, onDuplicate, onMoveToFolder])

  useEffect(() => {
    if (!anchor) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [anchor, onClose])

  useEffect(() => {
    if (!anchor) return
    // Prefer the first action so keyboard users land inside the menu.
    const firstItem = menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')
    firstItem?.focus()
  }, [anchor])

  if (!anchor || !position) return null
  const { session } = anchor

  return (
    <div
      className="fixed inset-0 z-(--z-modal)"
      onClick={onClose}
      onContextMenu={(event) => {
        event.preventDefault()
        onClose()
      }}
    >
      <div
        ref={menuRef}
        role="menu"
        aria-label={`Actions for ${session.title || 'Untitled'}`}
        className="fixed min-w-44 rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-sm text-(--color-text) shadow-xl"
        style={{ left: position.left, top: position.top }}
        onClick={(event) => event.stopPropagation()}
      >
        {onTogglePin && (
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
            onClick={() => {
              onClose()
              onTogglePin()
            }}
          >
            <Pin size={14} aria-hidden="true" />
            {pinned ? 'Unpin' : 'Pin'}
          </button>
        )}
        <button
          type="button"
          role="menuitem"
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
          onClick={() => {
            onClose()
            onEdit(session)
          }}
        >
          <Pencil size={14} aria-hidden="true" />
          Edit title
        </button>
        {onDuplicate && (
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
            onClick={() => {
              onClose()
              onDuplicate(session)
            }}
          >
            <Copy size={14} aria-hidden="true" />
            Duplicate
          </button>
        )}
        {onMoveToFolder && (
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
            onClick={() => {
              onClose()
              onMoveToFolder(session)
            }}
          >
            <FolderInput size={14} aria-hidden="true" />
            Move to folder…
          </button>
        )}
        <button
          type="button"
          role="menuitem"
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-(--color-error) hover:bg-(--color-error-subtle) focus-visible:bg-(--color-error-subtle) focus-visible:outline-none"
          onClick={() => {
            onClose()
            onDelete(session)
          }}
        >
          <Trash2 size={14} aria-hidden="true" />
          Delete session
        </button>
      </div>
    </div>
  )
}

interface SessionActionsDialogProps extends SessionMenuActions {
  /** Session the dialog acts on; null closes the dialog. */
  session: SessionResponse | null
  onClose: () => void
}

export function SessionActionsDialog({
  session,
  onClose,
  onEdit,
  onDelete,
  onDuplicate,
  pinned,
  onTogglePin,
  onMoveToFolder,
}: SessionActionsDialogProps) {
  return (
    <Dialog
      open={session !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{session?.title || 'Untitled'}</DialogTitle>
          <DialogDescription>Choose a session action.</DialogDescription>
        </DialogHeader>
        <DialogFooter className="flex-col items-stretch gap-2 p-3 sm:flex-col">
          {onTogglePin && (
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                onClose()
                onTogglePin()
              }}
            >
              <Pin size={14} aria-hidden="true" />
              {pinned ? 'Unpin' : 'Pin'}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            className="justify-start"
            onClick={() => {
              onClose()
              if (session) onEdit(session)
            }}
          >
            <Pencil size={14} aria-hidden="true" />
            Edit title
          </Button>
          {onDuplicate && (
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                onClose()
                if (session) onDuplicate(session)
              }}
            >
              <Copy size={14} aria-hidden="true" />
              Duplicate
            </Button>
          )}
          {onMoveToFolder && (
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                onClose()
                if (session) onMoveToFolder(session)
              }}
            >
              <FolderInput size={14} aria-hidden="true" />
              Move to folder…
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            className="justify-start text-(--color-error)"
            onClick={() => {
              onClose()
              if (session) onDelete(session)
            }}
          >
            <Trash2 size={14} aria-hidden="true" />
            Delete session
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
