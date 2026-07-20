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
import { Check, Copy, Download, Loader2, Plus, RefreshCw } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  downloadWebBridgeExtension,
  getWebBridgeAudit,
  getWebBridgeStatus,
  resolveTeamSession,
} from '@/api/client'
import { apiBaseUrl } from '@/api/base-url'
import { getConnectionToken } from '@/api/auth'
import { prependSession } from '@/stores/cache-invalidation-bridge'
import { useToastStore } from '@/stores/useToastStore'
import type { WebBridgeAuditEntry, WebBridgeStatusResponse } from '@/api/types'

/** Relay URL + token the extension needs, derived from the app's own
 *  connection — so the popup shows exactly what to paste in. */
function deriveConnection(): { relayUrl: string; token: string } {
  let origin = apiBaseUrl().replace(/\/api$/, '')
  if (!origin || origin.startsWith('/')) {
    origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8000'
  }
  return { relayUrl: origin.replace(/^http/i, 'ws'), token: getConnectionToken() ?? '' }
}

/** A labelled, monospace, one-click-copy value row. */
function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(() => {
    void navigator.clipboard?.writeText(value).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }, [value])
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-xs text-(--color-text-subtle)">{label}</span>
      <code className="min-w-0 flex-1 truncate rounded bg-(--bg-2) px-1.5 py-0.5 font-mono text-xs text-(--color-text)">
        {value}
      </code>
      <button
        onClick={copy}
        className="shrink-0 rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:bg-(--bg-2) hover:text-(--color-text-muted)"
        aria-label={`Copy ${label}`}
        title={`Copy ${label}`}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
      </button>
    </div>
  )
}

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
  const [audit, setAudit] = useState<WebBridgeAuditEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [downloading, setDownloading] = useState(false)
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
    // Best-effort: the audit trail is auxiliary, never block status on it.
    try {
      setAudit((await getWebBridgeAudit(12)).entries)
    } catch {
      setAudit([])
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

  const handleDownload = useCallback(async () => {
    setDownloading(true)
    try {
      await downloadWebBridgeExtension()
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Failed to download extension',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setDownloading(false)
    }
  }, [pushToast])

  const extension = status?.extensions[0]
  const connected = status?.connected ?? false
  const conn = deriveConnection()

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
          <div className="space-y-3">
            <Button
              onClick={() => void handleDownload()}
              disabled={downloading}
              className="w-full"
            >
              {downloading ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Download aria-hidden="true" />
              )}
              Download extension package
            </Button>

            <div className="min-w-0 space-y-1.5 rounded-md bg-(--bg-key) px-3 py-2">
              <p className="text-xs font-medium text-(--color-text-muted)">
                Configure the extension with
              </p>
              <CopyRow label="Relay URL" value={conn.relayUrl} />
              {conn.token ? (
                <CopyRow label="Access token" value={conn.token} />
              ) : (
                <p className="text-xs text-(--color-text-subtle)">
                  No access token needed — this backend runs without a key.
                </p>
              )}
            </div>

            <ol className="list-decimal space-y-1.5 pl-4 text-xs text-(--color-text-2)">
              <li>Download the package above and unzip it.</li>
              <li>
                Open{' '}
                <code className="rounded bg-(--bg-key) px-1 font-mono">
                  chrome://extensions
                </code>
                , enable Developer mode, click Load unpacked, and select the
                unzipped{' '}
                <code className="rounded bg-(--bg-key) px-1 font-mono">
                  webbridge
                </code>{' '}
                folder.
              </li>
              <li>
                Click the WebBridge toolbar icon and paste the relay URL and
                access token above.
              </li>
            </ol>
          </div>
        )}

        {audit.length > 0 && (
          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium text-(--color-text-muted)">
              Recent actions
            </p>
            <ul className="max-h-40 space-y-0.5 overflow-y-auto">
              {audit.map((e, i) => (
                <li
                  key={i}
                  className="flex min-w-0 items-center gap-1.5 text-xs"
                  title={e.error ?? e.url}
                >
                  <span
                    className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${
                      e.success ? 'bg-(--color-success)' : 'bg-(--color-error)'
                    }`}
                  />
                  <span className="shrink-0 font-mono text-(--color-text-2)">
                    {e.action}
                  </span>
                  <span className="truncate text-(--color-text-subtle)">
                    {e.error ? e.error : e.url}
                  </span>
                </li>
              ))}
            </ul>
          </div>
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
