/**
 * WebBridgeStatusDialog — extension-connection status, install steps, and
 * the "New WebBridge chat" entry point. Shared by the sidebar nav item
 * (WebBridgeNavItem) and the in-chat WebBridgeBanner's "Install guide".
 *
 * Owns status fetching: refreshed every time the dialog opens, plus a
 * manual refresh button. ``onStatusChange`` lets the nav item keep its
 * status dot in sync without owning a second fetch.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, RefreshCw } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { getWebBridgeStatus, resolveTeamSession } from '@/api/client'
import { prependSession } from '@/stores/cache-invalidation-bridge'
import { useToastStore } from '@/stores/useToastStore'
import type { WebBridgeStatusResponse } from '@/api/types'

interface WebBridgeStatusDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onStatusChange?: (status: WebBridgeStatusResponse) => void
}

export function WebBridgeStatusDialog({
  open,
  onOpenChange,
  onStatusChange,
}: WebBridgeStatusDialogProps) {
  const [status, setStatus] = useState<WebBridgeStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const pushToast = useToastStore((s) => s.push)

  // Ref-synced so `refresh` stays referentially stable for the open-effect
  // below regardless of how callers pass the callback.
  const onStatusChangeRef = useRef(onStatusChange)
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange
  })

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const next = await getWebBridgeStatus()
      setStatus(next)
      onStatusChangeRef.current?.(next)
    } catch {
      // Backend unreachable or unauthorized — report as "not connected".
      const fallback: WebBridgeStatusResponse = { connected: false, extensions: [] }
      setStatus(fallback)
      onStatusChangeRef.current?.(fallback)
    } finally {
      setLoading(false)
    }
  }, [])

  // Refetch every time the dialog opens so the status is current.
  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  const handleNewChat = useCallback(async () => {
    setCreating(true)
    try {
      const session = await resolveTeamSession({
        mode: 'forge',
        create: true,
        tags: ['webbridge'],
      })
      if (session.created) prependSession(queryClient, session)
      onOpenChange(false)
      navigate({ to: '/$sessionId', params: { sessionId: session.id } })
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Failed to create WebBridge chat',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setCreating(false)
    }
  }, [navigate, onOpenChange, queryClient, pushToast])

  const extension = status?.extensions[0]
  const connected = status?.connected ?? false

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
              // min-w-0: as a grid item this card's automatic minimum is its
              // content's min-content width — and `truncate` uses nowrap, so a
              // long URL would otherwise blow the dialog's fixed-width grid
              // out horizontally (children stretch to the oversized track).
              <div className="min-w-0 rounded-md bg-(--bg-key) px-3 py-2">
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

        <Button
          onClick={() => void handleNewChat()}
          disabled={creating}
          className="w-full"
        >
          {creating ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <Plus aria-hidden="true" />
          )}
          New WebBridge chat
        </Button>
      </DialogContent>
    </Dialog>
  )
}
