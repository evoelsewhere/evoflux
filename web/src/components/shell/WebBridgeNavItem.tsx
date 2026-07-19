/**
 * WebBridgeNavItem — sidebar nav entry for WebBridge plus its status dialog.
 *
 * Owns the extension-connection status: prefetched once on mount (not
 * polled) so the dot on the nav item is meaningful, and refreshed every
 * time the dialog opens (plus a manual refresh button).
 *
 * A dialog (not an anchored popover) because SidebarItem doesn't forward
 * refs — base-ui popover trigger composition would require changing that
 * shared component — and the codebase already uses dialogs for
 * sidebar-launched panels (EditSessionTitleDialog, SessionActionsDialog).
 */

import { useCallback, useEffect, useState } from 'react'
import { Globe, RefreshCw } from 'lucide-react'
import { SidebarItem } from '@/components/ui/sidebar-item'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { getWebBridgeStatus } from '@/api/client'
import type { WebBridgeStatusResponse } from '@/api/types'

interface WebBridgeNavItemProps {
  collapsed?: boolean
}

export function WebBridgeNavItem({ collapsed = false }: WebBridgeNavItemProps) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<WebBridgeStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setStatus(await getWebBridgeStatus())
    } catch {
      // Backend unreachable or unauthorized — report as "not connected".
      setStatus({ connected: false, extensions: [] })
    } finally {
      setLoading(false)
    }
  }, [])

  // One-shot prefetch so the status dot is meaningful before first click.
  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleOpenChange = useCallback(
    (next: boolean) => {
      setOpen(next)
      if (next) void refresh()
    },
    [refresh],
  )

  const extension = status?.extensions[0]
  const connected = status?.connected ?? false

  return (
    <>
      <SidebarItem
        Icon={Globe}
        label="WebBridge"
        collapsed={collapsed}
        onClick={() => handleOpenChange(true)}
        rightSlot={
          status !== null ? (
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                connected ? 'bg-(--color-success)' : 'bg-(--color-text-subtle)'
              }`}
              title={connected ? 'Extension connected' : 'Extension not connected'}
            />
          ) : undefined
        }
      />
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>WebBridge</DialogTitle>
            <DialogDescription>
              Lets the agent drive your real Chrome/Edge browser through the
              WebBridge extension.
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <span
                className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                  connected ? 'bg-(--color-success)' : 'bg-(--color-text-subtle)'
                }`}
              />
              <span className="truncate text-sm text-(--color-text)">
                {connected && extension
                  ? `Extension connected (${extension.browser}, v${extension.version})`
                  : 'Not connected'}
              </span>
            </div>
            <button
              onClick={() => void refresh()}
              className="rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-muted)"
              aria-label="Refresh status"
              title="Refresh status"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>

          {connected && extension ? (
            <>
              {(extension.current_url || extension.current_title) && (
                <div className="rounded-md bg-(--bg-key) px-3 py-2">
                  {extension.current_title && (
                    <p className="truncate text-xs font-medium text-(--color-text)">
                      {extension.current_title}
                    </p>
                  )}
                  {extension.current_url && (
                    <p className="truncate text-xs text-(--color-text-subtle)">
                      {extension.current_url}
                    </p>
                  )}
                </div>
              )}
              <p className="text-xs text-(--color-text-muted)">
                Ask the agent to browse — it can now use your real browser.
              </p>
            </>
          ) : (
            <ol className="list-decimal space-y-1.5 pl-4 text-xs text-(--color-text-2)">
              <li>
                Open{' '}
                <code className="rounded bg-(--bg-key) px-1 font-mono">
                  chrome://extensions
                </code>{' '}
                and enable Developer mode.
              </li>
              <li>
                Click Load unpacked and select the{' '}
                <code className="rounded bg-(--bg-key) px-1 font-mono">
                  extensions/webbridge
                </code>{' '}
                folder from the EvoFlux repository.
              </li>
              <li>
                Click the WebBridge toolbar icon and set the relay URL and
                access token.
              </li>
            </ol>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
