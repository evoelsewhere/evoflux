import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export interface LspRenameRequest {
  currentName: string
  line: number
  column: number
}

export function LspRenameDialog({
  request,
  onClose,
  onRename,
}: {
  request: LspRenameRequest | null
  onClose: () => void
  onRename: (newName: string) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setName(request?.currentName ?? '')
    setError(null)
  }, [request])

  const submit = async () => {
    if (!request || busy) return
    const nextName = name.trim()
    if (!nextName) {
      setError('Enter a new symbol name.')
      return
    }
    if (nextName === request.currentName) {
      setError('Choose a different symbol name.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onRename(nextName)
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Rename could not be prepared.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={request !== null}
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
    >
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Rename symbol</DialogTitle>
          <DialogDescription>
            LSP calculates a repository-local ChangeSet. Review the diff before anything is written.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
        >
          <div>
            <label htmlFor="lsp-rename-name" className="text-xs font-medium text-(--color-text)">
              New name
            </label>
            <input
              id="lsp-rename-name"
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
              spellCheck={false}
              className="mt-1.5 h-10 w-full rounded-lg border border-(--color-border) bg-(--bg-input) px-3 font-mono text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-3 focus:ring-(--focus-ring)/20 disabled:opacity-60"
            />
            {request?.currentName && (
              <p className="mt-1.5 text-[11px] text-(--color-text-muted)">
                Current symbol: <code className="font-mono text-(--color-text-2)">{request.currentName}</code>
              </p>
            )}
            {error && (
              <p role="alert" className="mt-2 text-xs text-(--color-error)">{error}</p>
            )}
          </div>
          <DialogFooter className="mx-0 mb-0">
            <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
              {busy ? 'Preparing…' : 'Rename'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
