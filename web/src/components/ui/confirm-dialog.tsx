import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { ConfirmRequest } from '@/hooks/use-confirm'

/**
 * A confirmation the app owns, instead of `window.confirm`.
 *
 * The native dialog blocks the renderer while it is up, is unstyled and
 * unthemed, and cannot say which of several destructive actions it is
 * guarding beyond one line of plain text. For anything that cannot be
 * undone, this also puts the safe choice under Escape and the outside
 * click, and gives the confirm button a destructive colour.
 */
export function ConfirmDialog({
  request,
  busy = false,
  onClose,
}: {
  request: ConfirmRequest | null
  busy?: boolean
  onClose: () => void
}) {
  // The dialog animates out after the request clears, and rendering
  // `null?.title` for those frames flashed an empty box. Keep the last
  // request so the closing frames still show what was being confirmed.
  const [shown, setShown] = useState<ConfirmRequest | null>(null)
  if (request && request !== shown) setShown(request)

  return (
    <Dialog
      open={request !== null}
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
    >
      <DialogContent showCloseButton={false} className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            {shown?.destructive && (
              <AlertTriangle size={17} className="shrink-0 text-(--color-error)" />
            )}
            <DialogTitle>{shown?.title}</DialogTitle>
          </div>
          <DialogDescription>{shown?.description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            {shown?.cancelLabel ?? 'Cancel'}
          </Button>
          <Button
            autoFocus
            variant={shown?.destructive ? 'destructive' : 'default'}
            disabled={busy}
            onClick={() => {
              request?.onConfirm()
              onClose()
            }}
          >
            {shown?.confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
