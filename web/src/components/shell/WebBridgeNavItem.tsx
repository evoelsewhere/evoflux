/**
 * WebBridgeNavItem — sidebar nav entry for WebBridge.
 *
 * Shows a status dot (one-shot prefetch on mount; kept in sync with the
 * dialog's refreshes via ``onStatusChange``) and opens the shared
 * WebBridgeStatusDialog on click.
 *
 * A dialog (not an anchored popover) because SidebarItem doesn't forward
 * refs — base-ui popover trigger composition would require changing that
 * shared component — and the codebase already uses dialogs for
 * sidebar-launched panels (EditSessionTitleDialog, SessionActionsDialog).
 */

import { useCallback, useEffect, useState } from 'react'
import { Globe } from 'lucide-react'
import { SidebarItem } from '@/components/ui/sidebar-item'
import { WebBridgeStatusDialog } from './WebBridgeStatusDialog'
import { getWebBridgeStatus } from '@/api/client'
import type { WebBridgeStatusResponse } from '@/api/types'

interface WebBridgeNavItemProps {
  collapsed?: boolean
}

export function WebBridgeNavItem({ collapsed = false }: WebBridgeNavItemProps) {
  const [open, setOpen] = useState(false)
  const [connected, setConnected] = useState<boolean | null>(null)

  // One-shot prefetch so the status dot is meaningful before first click.
  useEffect(() => {
    let cancelled = false
    getWebBridgeStatus()
      .then((status) => {
        if (!cancelled) setConnected(status.connected)
      })
      .catch(() => {
        // Backend unreachable or unauthorized — report as "not connected".
        if (!cancelled) setConnected(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleStatusChange = useCallback(
    (status: WebBridgeStatusResponse) => setConnected(status.connected),
    [],
  )

  return (
    <>
      <SidebarItem
        Icon={Globe}
        label="WebBridge"
        collapsed={collapsed}
        onClick={() => setOpen(true)}
        rightSlot={
          connected !== null ? (
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                connected ? 'bg-(--color-success)' : 'bg-(--color-text-subtle)'
              }`}
              title={connected ? 'Extension connected' : 'Extension not connected'}
            />
          ) : undefined
        }
      />
      <WebBridgeStatusDialog
        open={open}
        onOpenChange={setOpen}
        onStatusChange={handleStatusChange}
      />
    </>
  )
}
