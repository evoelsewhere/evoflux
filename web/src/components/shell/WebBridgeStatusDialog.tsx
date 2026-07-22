/**
 * WebBridgeStatusDialog — extension-connection status and install steps.
 * Shared by the sidebar nav item and the chat composer WebBridge control.
 *
 * Owns status fetching: refreshed every time the dialog opens, plus a
 * manual refresh button. ``onStatusChange`` lets the nav item keep its
 * status dot in sync without owning a second fetch.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, Download, KeyRound, Loader2, RefreshCw, Unplug } from 'lucide-react'
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
  issueWebBridgePairingCode,
  listWebBridgePairings,
  revokeWebBridgePairing,
} from '@/api/client'
import { apiBaseUrl } from '@/api/base-url'
import { useToastStore } from '@/stores/useToastStore'
import type {
  WebBridgeAuditEntry,
  WebBridgePairingInfo,
  WebBridgeStatusResponse,
} from '@/api/types'

/** Relay URL the extension needs, derived from the app's own connection. */
function deriveRelayUrl(): string {
  let origin = apiBaseUrl().replace(/\/api$/, '')
  if (!origin || origin.startsWith('/')) {
    origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8000'
  }
  return origin.replace(/^http/i, 'ws')
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
      <span className="w-24 shrink-0 text-xs text-(--color-text-subtle)">{label}</span>
      <code className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap rounded bg-(--bg-2) px-1.5 py-0.5 font-mono text-xs text-(--color-text)" title={value}>
        {value}
      </code>
      <button
        onClick={copy}
        className="shrink-0 rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:bg-(--bg-2) hover:text-(--color-text-muted)"
        aria-label={`Copy ${label}`}
        title={copied ? "Copied!" : `Copy ${label}`}
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
  const [downloading, setDownloading] = useState(false)
  const [pairingCode, setPairingCode] = useState<string | null>(null)
  const [pairings, setPairings] = useState<WebBridgePairingInfo[]>([])
  const [pairing, setPairing] = useState(false)
  const [revokingPairingId, setRevokingPairingId] = useState<string | null>(null)
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
    try {
      setPairings(await listWebBridgePairings())
    } catch {
      setPairings([])
    }
  }, [])

  // Refetch every time the dialog opens so the status is current.
  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

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

  const handlePairingCode = useCallback(async () => {
    setPairing(true)
    try {
      const result = await issueWebBridgePairingCode()
      setPairingCode(result.code)
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Could not create pairing code',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setPairing(false)
    }
  }, [pushToast])

  const extension = status?.extensions[0]
  const connected = status?.connected ?? false
  const relayUrl = deriveRelayUrl()
  const hasLegacyConnection = Boolean(
    status?.extensions.some((activeExtension) => !activeExtension.paired),
  )

  const handleRevoke = useCallback(async (pairingId: string) => {
    setRevokingPairingId(pairingId)
    try {
      await revokeWebBridgePairing(pairingId)
      await refresh()
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Could not revoke pairing',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setRevokingPairingId(null)
    }
  }, [pushToast, refresh])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md min-w-0 w-[400px]">
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
            {hasLegacyConnection && (
              <div className="space-y-2 rounded-md bg-(--bg-key) px-3 py-2">
                <p className="text-xs text-(--color-text-muted)">
                  This extension uses the legacy token connection. Pair it to
                  replace that token with a scoped credential.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handlePairingCode()}
                  disabled={pairing}
                  className="w-full"
                >
                  {pairing ? (
                    <Loader2 className="animate-spin" aria-hidden="true" />
                  ) : (
                    <KeyRound aria-hidden="true" />
                  )}
                  Generate secure pairing code
                </Button>
                {pairingCode && <CopyRow label="Pairing code" value={pairingCode} />}
              </div>
            )}
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

            <Button
              type="button"
              variant="outline"
              onClick={() => void handlePairingCode()}
              disabled={pairing}
              className="w-full"
            >
              {pairing ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <KeyRound aria-hidden="true" />
              )}
              Generate secure pairing code
            </Button>

            {pairingCode && (
              <div className="min-w-0 space-y-1.5 rounded-md bg-(--bg-key) px-3 py-2">
                <CopyRow label="Pairing code" value={pairingCode} />
                <p className="text-xs text-(--color-text-subtle)">
                  One-time code. Expires in 5 minutes.
                </p>
              </div>
            )}

            <div className="min-w-0 space-y-1.5 rounded-md bg-(--bg-key) px-3 py-2">
              <p className="text-xs font-medium text-(--color-text-muted)">
                Connection address
              </p>
              <CopyRow label="Relay URL" value={relayUrl} />
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
                Generate a pairing code, then open the WebBridge toolbar popup,
                enter the relay URL and pair securely.
              </li>
            </ol>
          </div>
        )}

        {pairings.length > 0 && (
          <div className="min-w-0 space-y-2">
            <p className="text-xs font-medium text-(--color-text-muted)">
              Secure pairings
            </p>
            <ul className="space-y-1 rounded-md bg-(--bg-key) px-2 py-1.5">
              {pairings.map((paired) => (
                <li key={paired.pairing_id} className="flex min-w-0 items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-(--color-text)">
                      {paired.label}
                    </p>
                    <p className="truncate text-xs text-(--color-text-subtle)">
                      {paired.browser} · v{paired.version}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleRevoke(paired.pairing_id)}
                    disabled={revokingPairingId === paired.pairing_id}
                    className="shrink-0 rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:bg-(--bg-2) hover:text-(--color-error) disabled:opacity-50"
                    aria-label={`Revoke ${paired.label}`}
                    title={`Revoke ${paired.label}`}
                  >
                    {revokingPairingId === paired.pairing_id ? (
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    ) : (
                      <Unplug size={14} aria-hidden="true" />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {audit.length > 0 && (
          <div className="min-w-0">
            <p className="mb-2 text-xs font-medium text-(--color-text-muted)">
              Recent actions
            </p>
            <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md bg-(--bg-key) px-2 py-1.5">
              {audit.map((e, i) => (
                <li
                  key={i}
                  className="flex min-w-0 items-center gap-2 text-xs"
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
                  <span className="min-w-0 flex-1 truncate text-(--color-text-subtle)">
                    {e.error ? e.error : e.url}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <Button type="button" variant="outline" onClick={() => onOpenChange(false)} className="w-full">
          Close
        </Button>
      </DialogContent>
    </Dialog>
  )
}
