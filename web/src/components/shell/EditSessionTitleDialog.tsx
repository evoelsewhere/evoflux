/**
 * EditSessionTitleDialog — the rename-session modal shared by the mode
 * sidebars (identical copies lived in Sidebar.tsx and CodingSidebar.tsx).
 *
 * The input is controlled by the caller so the parent keeps owning the
 * mutation lifecycle: submit hands back the trimmed title and the parent
 * closes the dialog on mutation success.
 */

import { useEffect, useRef } from 'react'
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

interface EditSessionTitleDialogProps {
  /** Session being renamed; null closes the dialog. */
  session: SessionResponse | null
  title: string
  onTitleChange: (title: string) => void
  onClose: () => void
  /** Called with the trimmed title; empty titles never submit. */
  onSubmit: (title: string) => void
  isPending?: boolean
  isError?: boolean
}

export function EditSessionTitleDialog({
  session,
  title,
  onTitleChange,
  onClose,
  onSubmit,
  isPending = false,
  isError = false,
}: EditSessionTitleDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (session) inputRef.current?.focus()
  }, [session])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!session) return
    const trimmed = title.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  return (
    <Dialog
      open={session !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent showCloseButton={false}>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Edit session title</DialogTitle>
            <DialogDescription>
              Rename this session in the sidebar.
            </DialogDescription>
          </DialogHeader>
          <div className="px-3 py-2">
            <input
              ref={inputRef}
              value={title}
              onChange={(e) => onTitleChange(e.target.value)}
              className="h-9 w-full min-w-0 rounded-[10px] border border-(--color-border) bg-(--bg-page) px-3 py-1 text-sm text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
              aria-label="Session title"
              maxLength={255}
            />
            {isError && (
              <p className="mt-2 text-xs text-(--color-error)">
                Failed to update title.
              </p>
            )}
          </div>
          <DialogFooter className="p-3">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!title.trim() || isPending}>
              {isPending ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
