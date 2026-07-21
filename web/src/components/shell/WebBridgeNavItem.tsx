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

/** Keyboard shortcut: Ctrl+Shift+W to toggle WebBridge dialog. */
const WEBBRIDGE_SHORTCUT = { ctrl: true, shift: true, key: 'w' }

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

  // Global keyboard shortcut: Ctrl+Shift+W to open WebBridge dialog
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === WEBBRIDGE_SHORTCUT.key) {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <>
      <SidebarItem
        Icon={Globe}
        label="WebBridge"
        collapsed={collapsed}
        onClick={() => setOpen(true)}
        rightSlot={
          !collapsed ? (
            <span className="flex shrink-0 items-center gap-1.5">
              <kbd className="rounded border border-(--color-border) bg-(--bg-page) px-1 py-0.5 font-mono text-xs text-(--color-text-subtle)">
                Ctrl+Shift+W
              </kbd>
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  connected ? 'bg-(--color-success)' : 'bg-(--color-text-subtle)'
                }`}
                title={connected ? 'Extension connected' : 'Extension not connected'}
              />
            </span>
          ) : (
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                connected ? 'bg-(--color-success)' : 'bg-(--color-text-subtle)'
              }`}
              title={connected ? 'Extension connected' : 'Extension not connected'}
            />
          )
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
