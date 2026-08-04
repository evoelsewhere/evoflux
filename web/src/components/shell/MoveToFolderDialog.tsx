/**
 * MoveToFolderDialog — the keyboard/touch path for filing a session.
 *
 * Drag-and-drop covers the mouse case, but touch drags don't fire HTML5 drag
 * events, so the session context menu and the mobile actions sheet route
 * "Move to folder…" here.
 */

import { useState } from 'react'
import { Check, Folder, FolderPlus, Inbox } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { SessionFolder, SessionResponse } from '@/api/types'

interface MoveToFolderDialogProps {
  /** Session being filed; null closes the dialog. */
  session: SessionResponse | null
  folders: SessionFolder[]
  onClose: () => void
  /** `null` un-files the session. */
  onSelect: (folderId: string | null) => void
  /** Creates a folder and files the session into it. */
  onCreateAndSelect: (name: string) => void
  isPending?: boolean
}

export function MoveToFolderDialog({
  session,
  folders,
  onClose,
  onSelect,
  onCreateAndSelect,
  isPending = false,
}: MoveToFolderDialogProps) {
  const [newName, setNewName] = useState('')
  const currentFolderId = session?.folder_id ?? null

  const close = () => {
    setNewName('')
    onClose()
  }

  return (
    <Dialog
      open={session !== null}
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Move to folder</DialogTitle>
          <DialogDescription>
            Chats in the same folder can share context with each other.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-64 overflow-y-auto px-3 py-2">
          <button
            type="button"
            onClick={() => onSelect(null)}
            disabled={isPending}
            className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm text-(--color-text) hover:bg-(--bg-key) disabled:opacity-50"
          >
            <Inbox size={14} aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">No folder</span>
            {currentFolderId === null && <Check size={14} className="text-(--color-accent)" />}
          </button>
          {folders.map((folder) => (
            <button
              key={folder.id}
              type="button"
              onClick={() => onSelect(folder.id)}
              disabled={isPending}
              className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm text-(--color-text) hover:bg-(--bg-key) disabled:opacity-50"
            >
              <Folder size={14} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{folder.name}</span>
              {currentFolderId === folder.id && (
                <Check size={14} className="text-(--color-accent)" />
              )}
            </button>
          ))}
          <form
            className="mt-2 flex items-center gap-2 border-t border-(--color-border) pt-2"
            onSubmit={(event) => {
              event.preventDefault()
              const name = newName.trim()
              if (!name) return
              onCreateAndSelect(name)
            }}
          >
            <FolderPlus size={14} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="New folder…"
              aria-label="New folder name"
              maxLength={120}
              className="h-8 min-w-0 flex-1 rounded-md border border-(--color-border) bg-(--bg-page) px-2 text-sm text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
            />
            <Button type="submit" size="sm" disabled={!newName.trim() || isPending}>
              Create
            </Button>
          </form>
        </div>
        <DialogFooter className="p-3">
          <Button type="button" variant="outline" onClick={close}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
