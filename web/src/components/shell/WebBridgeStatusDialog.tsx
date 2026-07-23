/**
 * WebBridgeStatusDialog — extension-connection status and install steps.
 * Shared by the sidebar nav item and the chat composer WebBridge control.
 *
 * Owns status fetching: refreshed every time the dialog opens, plus a
 * manual refresh button. ``onStatusChange`` lets the nav item keep its
 * status dot in sync without owning a second fetch.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, Download, KeyRound, Link2, Loader2, Play, RefreshCw, Trash2, Unplug } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  assignWebBridgeSessionToPairing,
  approveWebBridgeTeachDraft,
  deleteWebBridgeTeachDraft,
  downloadWebBridgeExtension,
  getWebBridgeAudit,
  getWebBridgeStatus,
  issueWebBridgePairingCode,
  listWebBridgePairings,
  listTeamSessions,
  listWebBridgeTeachDrafts,
  revokeWebBridgePairing,
  replayWebBridgeTeachDraft,
} from '@/api/client'
import { apiBaseUrl } from '@/api/base-url'
import { useToastStore } from '@/stores/useToastStore'
import type {
  WebBridgeAuditEntry,
  SessionResponse,
  WebBridgePairingInfo,
  WebBridgeStatusResponse,
  WebBridgeTeachAction,
  WebBridgeTeachDraft,
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

function teachActionLabel(action: WebBridgeTeachAction): string {
  if (action.kind === 'navigate') return `Navigate to ${action.url ?? 'page'}`
  if (action.kind === 'fill') {
    return action.secret
      ? `Fill ${action.selector ?? 'field'} from ${action.parameter ?? 'secret parameter'}`
      : `Fill ${action.selector ?? 'field'} with ${JSON.stringify(action.value ?? '')}`
  }
  if (action.kind === 'select') {
    return `Select ${(action.values ?? []).map((value) => JSON.stringify(value)).join(', ')} in ${action.selector ?? 'field'}`
  }
  if (action.kind === 'set_checked') return `${action.checked ? 'Enable' : 'Disable'} ${action.selector ?? 'field'}`
  return `Click ${action.selector ?? 'element'}`
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
  const [webBridgeSessions, setWebBridgeSessions] = useState<SessionResponse[]>([])
  const [selectedSessionByPairing, setSelectedSessionByPairing] = useState<Record<string, string>>({})
  const [pairing, setPairing] = useState(false)
  const [revokingPairingId, setRevokingPairingId] = useState<string | null>(null)
  const [assigningPairingId, setAssigningPairingId] = useState<string | null>(null)
  const [teachDrafts, setTeachDrafts] = useState<WebBridgeTeachDraft[]>([])
  const [approvingDraftId, setApprovingDraftId] = useState<string | null>(null)
  const [replayingDraftId, setReplayingDraftId] = useState<string | null>(null)
  const [deletingDraftId, setDeletingDraftId] = useState<string | null>(null)
  const [draftParameters, setDraftParameters] = useState<Record<string, Record<string, string>>>({})
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
      const [nextPairings, page] = await Promise.all([
        listWebBridgePairings(),
        listTeamSessions(undefined, 100),
      ])
      setPairings(nextPairings)
      setWebBridgeSessions(
        page.data.filter((session) => session.tags?.includes('webbridge')),
      )
    } catch {
      setPairings([])
      setWebBridgeSessions([])
    }
    try {
      setTeachDrafts(await listWebBridgeTeachDrafts())
    } catch {
      setTeachDrafts([])
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

  const handleAssign = useCallback(async (pairingId: string) => {
    const sessionId = selectedSessionByPairing[pairingId]
    if (!sessionId) {
      pushToast({
        tone: 'error',
        title: 'Choose a WebBridge session',
      })
      return
    }
    setAssigningPairingId(pairingId)
    try {
      await assignWebBridgeSessionToPairing(pairingId, sessionId)
      await refresh()
      pushToast({
        tone: 'success',
        title: 'Session granted to browser pairing',
      })
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Could not grant session access',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setAssigningPairingId(null)
    }
  }, [pushToast, refresh, selectedSessionByPairing])

  const handleApproveDraft = useCallback(async (draftId: string) => {
    setApprovingDraftId(draftId)
    try {
      await approveWebBridgeTeachDraft(draftId)
      await refresh()
      pushToast({ tone: 'success', title: 'Teach draft approved for supervised replay' })
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Could not approve Teach draft',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setApprovingDraftId(null)
    }
  }, [pushToast, refresh])

  const handleReplayDraft = useCallback(async (draft: WebBridgeTeachDraft) => {
    setReplayingDraftId(draft.id)
    try {
      await replayWebBridgeTeachDraft(draft.id, draftParameters[draft.id] ?? {})
      setDraftParameters((current) => {
        const next = { ...current }
        delete next[draft.id]
        return next
      })
      await refresh()
      pushToast({ tone: 'success', title: 'Teach draft replay completed' })
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Teach draft replay stopped',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setReplayingDraftId(null)
    }
  }, [draftParameters, pushToast, refresh])

  const handleDeleteDraft = useCallback(async (draftId: string) => {
    setDeletingDraftId(draftId)
    try {
      await deleteWebBridgeTeachDraft(draftId)
      await refresh()
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Could not delete Teach draft',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setDeletingDraftId(null)
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
                Same device
              </p>
              <p className="text-xs text-(--color-text-subtle)">
                Click the WebBridge toolbar icon, open Settings, then choose
                Pair local EvoFlux. No code is generated.
              </p>
            </div>

            <div className="min-w-0 space-y-2 rounded-md border border-(--color-border) px-3 py-2">
              <p className="text-xs font-medium text-(--color-text-muted)">
                Manual or remote pairing
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
                Generate one-time pairing code
              </Button>

              {pairingCode && (
                <div className="min-w-0 space-y-1.5">
                  <CopyRow label="Pairing code" value={pairingCode} />
                  <p className="text-xs text-(--color-text-subtle)">
                    Single use. Expires in 5 minutes.
                  </p>
                </div>
              )}
            </div>

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
                Click the WebBridge toolbar icon and pair locally. Use the
                one-time code only when local pairing is unavailable.
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
                <li key={paired.pairing_id} className="min-w-0 space-y-2 border-b border-(--color-border-subtle) py-1.5 last:border-b-0">
                  <div className="flex min-w-0 items-center gap-2">
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
                  </div>
                  {webBridgeSessions.length > 0 ? (
                    <div className="flex min-w-0 items-center gap-2">
                      <Select
                        value={selectedSessionByPairing[paired.pairing_id] ?? null}
                        onValueChange={(value) => setSelectedSessionByPairing((current) => ({
                          ...current,
                          [paired.pairing_id]: value ?? '',
                        }))}
                      >
                        <SelectTrigger size="sm" className="min-w-0 flex-1">
                          <SelectValue placeholder="Grant a WebBridge session" />
                        </SelectTrigger>
                        <SelectContent>
                          {webBridgeSessions.map((session) => (
                            <SelectItem key={session.id} value={session.id}>
                              {session.title || 'Untitled session'}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void handleAssign(paired.pairing_id)}
                        disabled={assigningPairingId === paired.pairing_id}
                      >
                        {assigningPairingId === paired.pairing_id ? (
                          <Loader2 className="animate-spin" aria-hidden="true" />
                        ) : (
                          <Link2 aria-hidden="true" />
                        )}
                        Grant
                      </Button>
                    </div>
                  ) : (
                    <p className="text-xs text-(--color-text-subtle)">
                      Enable WebBridge in a chat session to grant it to this browser.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {teachDrafts.length > 0 && (
          <div className="min-w-0 space-y-2">
            <p className="text-xs font-medium text-(--color-text-muted)">
              Teach drafts
            </p>
            <ul className="max-h-72 space-y-1 overflow-y-auto rounded-md bg-(--bg-key) px-2 py-1.5">
              {teachDrafts.map((draft) => (
                <li key={draft.id} className="min-w-0 space-y-2 border-b border-(--color-border-subtle) py-2 last:border-b-0">
                  <div className="flex min-w-0 items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-(--color-text)">{draft.title}</p>
                      <p className="truncate text-xs text-(--color-text-subtle)" title={draft.start_url}>
                        {draft.actions.length} semantic step{draft.actions.length === 1 ? '' : 's'} · {draft.status}
                      </p>
                      <p className="truncate text-xs text-(--color-text-subtle)" title={draft.start_url}>
                        {draft.start_url}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleDeleteDraft(draft.id)}
                      disabled={deletingDraftId === draft.id}
                      className="shrink-0 rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:bg-(--bg-2) hover:text-(--color-error) disabled:opacity-50"
                      aria-label={`Delete ${draft.title}`}
                      title={`Delete ${draft.title}`}
                    >
                      {deletingDraftId === draft.id ? (
                        <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                      ) : (
                        <Trash2 size={14} aria-hidden="true" />
                      )}
                    </button>
                  </div>
                  <ol className="space-y-0.5 text-xs text-(--color-text-subtle)">
                    {draft.actions.map((action, index) => (
                      <li key={`${draft.id}-${index}`} className="truncate" title={teachActionLabel(action)}>
                        {index + 1}. {teachActionLabel(action)}
                      </li>
                    ))}
                  </ol>
                  {draft.capture_warnings.map((warning) => (
                    <p key={warning} className="text-xs text-(--color-warning)">{warning}</p>
                  ))}
                  {draft.parameter_names.map((parameter) => (
                    <Input
                      key={parameter}
                      type="password"
                      value={draftParameters[draft.id]?.[parameter] ?? ''}
                      onChange={(event) => setDraftParameters((current) => ({
                        ...current,
                        [draft.id]: { ...current[draft.id], [parameter]: event.target.value },
                      }))}
                      placeholder={parameter}
                      aria-label={`Value for ${parameter}`}
                      className="h-8 text-xs"
                    />
                  ))}
                  {draft.last_error && (
                    <p className="text-xs text-(--color-error)">{draft.last_error}</p>
                  )}
                  <div className="flex gap-2">
                    {draft.status !== 'approved' ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void handleApproveDraft(draft.id)}
                        disabled={approvingDraftId === draft.id}
                        className="flex-1"
                      >
                        {approvingDraftId === draft.id ? (
                          <Loader2 className="animate-spin" aria-hidden="true" />
                        ) : (
                          <Check aria-hidden="true" />
                        )}
                        Approve
                      </Button>
                    ) : (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => void handleReplayDraft(draft)}
                        disabled={replayingDraftId === draft.id}
                        className="flex-1"
                      >
                        {replayingDraftId === draft.id ? (
                          <Loader2 className="animate-spin" aria-hidden="true" />
                        ) : (
                          <Play aria-hidden="true" />
                        )}
                        Replay
                      </Button>
                    )}
                  </div>
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
