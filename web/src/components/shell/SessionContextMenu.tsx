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
import { Pencil, Pin, Trash2 } from 'lucide-react'
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
  /** Pin state of the target session — controls the Pin/Unpin label. */
  pinned?: boolean
  /** The Pin/Unpin item renders only when this is provided. */
  onTogglePin?: () => void
}

interface SessionContextMenuProps extends SessionMenuActions {
  /** Anchor position; null closes the menu. */
  anchor: SessionMenuAnchor | null
  onClose: () => void
}

/** Approximate menu size for viewport clamping before first paint. */
const MENU_WIDTH = 176
const MENU_EDGE_PAD = 8
/** One `py-1.5 text-sm` row plus the menu's own `p-1`. */
const MENU_ITEM_HEIGHT = 32
const MENU_VERTICAL_PADDING = 8

function clampMenuPosition(
  x: number,
  y: number,
  itemCount: number,
): { left: number; top: number } {
  // Derived from the rendered item count: a fixed over-estimate lifted menus
  // opened near the bottom edge well above the pointer.
  const menuHeight = itemCount * MENU_ITEM_HEIGHT + MENU_VERTICAL_PADDING
  const maxLeft = Math.max(MENU_EDGE_PAD, window.innerWidth - MENU_WIDTH - MENU_EDGE_PAD)
  const maxTop = Math.max(MENU_EDGE_PAD, window.innerHeight - menuHeight - MENU_EDGE_PAD)
  return {
    left: Math.min(Math.max(MENU_EDGE_PAD, x), maxLeft),
    top: Math.min(Math.max(MENU_EDGE_PAD, y), maxTop),
  }
}

export function SessionContextMenu({
  anchor,
  onClose,
  onEdit,
  onDelete,
  pinned,
  onTogglePin,
}: SessionContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  // Set by the items themselves: an action opens its own focus target (rename
  // dialog, delete confirmation), so restoring the trigger would steal it.
  const actionTakenRef = useRef(false)
  const itemCount = onTogglePin ? 3 : 2
  const position = useMemo(
    () => (anchor ? clampMenuPosition(anchor.x, anchor.y, itemCount) : null),
    [anchor, itemCount],
  )

  // Callers pass an inline `onClose`, so keeping it out of the effect's deps is
  // what stops an unrelated parent re-render from re-running the effect below
  // and yanking focus back to the first item mid-navigation.
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!anchor) return
    actionTakenRef.current = false
    const trigger = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const items = () =>
      Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])
    // Prefer the first action so keyboard users land inside the menu.
    items()[0]?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      // Arrow/Home/End navigation is what `role="menu"` promises; the menu
      // previously only responded to Escape and the pointer.
      const focusable = items()
      if (focusable.length === 0) return
      const current = focusable.indexOf(document.activeElement as HTMLElement)
      let next: number | null = null
      if (event.key === 'ArrowDown') next = (current + 1) % focusable.length
      else if (event.key === 'ArrowUp') next = current <= 0 ? focusable.length - 1 : current - 1
      else if (event.key === 'Home') next = 0
      else if (event.key === 'End') next = focusable.length - 1
      if (next === null) return
      event.preventDefault()
      focusable[next]?.focus()
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      if (!actionTakenRef.current && trigger?.isConnected) trigger.focus()
    }
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
            // The rename dialog takes focus on open — don't restore the row.
            actionTakenRef.current = true
            onClose()
            onEdit(session)
          }}
        >
          <Pencil size={14} aria-hidden="true" />
          Edit title
        </button>
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
  pinned,
  onTogglePin,
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
