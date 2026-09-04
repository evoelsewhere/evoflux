import { useState } from 'react'

export type ConfirmRequest = {
  title: string
  /** What the action does, and what survives it. */
  description: string
  confirmLabel: string
  cancelLabel?: string
  destructive?: boolean
  onConfirm: () => void
}

/**
 * Holds the pending confirmation, so a caller only writes `confirm({...})`
 * and renders one `<ConfirmDialog>` at the bottom of the component.
 */
export function useConfirm() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null)
  return {
    request,
    confirm: setRequest,
    close: () => setRequest(null),
  }
}
