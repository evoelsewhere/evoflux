/**
 * WebBridgeStatusDialog — extension-connection status and install steps.
 * Shared by the sidebar nav item and the chat composer WebBridge control.
 *
 * Owns status fetching: refreshed every time the dialog opens, plus a
 * manual refresh button. ``onStatusChange`` lets the nav item keep its
 * status dot in sync without owning a second fetch.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, Download, Loader2, Play, RefreshCw, Trash2 } from 'lucide-react'
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
  ApiValidationError,
  approveWebBridgeTeachDraft,
  deleteWebBridgeTeachDraft,
  getWebBridgeAudit,
  getWebBridgeStatus,
  listWebBridgeTeachDrafts,
  replayWebBridgeTeachDraft,
  resolveWebBridgeTeachReplay,
} from '@/api/client'
import { apiBaseUrl } from '@/api/base-url'
import { WEBBRIDGE_EXTENSION_DOWNLOAD_URL } from '@/lib/downloads'
import { openExternalUrl } from '@/lib/open-external'
import { useToastStore } from '@/stores/useToastStore'
import type {
  WebBridgeAuditEntry,
  WebBridgeStatusResponse,
  WebBridgeTeachAction,
  WebBridgeTeachDraft,
} from '@/api/types'

/** Relay URL the extension needs, derived from the app's own connection. */
function deriveRelayUrl(): string {
  let origin = apiBaseUrl().replace(/\/api$/, '')
  if (!origin || origin.startsWith('/')) {
    origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:4082'
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
  const [teachDrafts, setTeachDrafts] = useState<WebBridgeTeachDraft[]>([])
  const [approvingDraftId, setApprovingDraftId] = useState<string | null>(null)
  const [replayingDraftId, setReplayingDraftId] = useState<string | null>(null)
  const [resolvingDraftId, setResolvingDraftId] = useState<string | null>(null)
  const [deletingDraftId, setDeletingDraftId] = useState<string | null>(null)
  const [draftParameters, setDraftParameters] = useState<Record<string, Record<string, string>>>({})
  const replayRequestKeysRef = useRef<Record<string, string>>({})
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
      await openExternalUrl(WEBBRIDGE_EXTENSION_DOWNLOAD_URL)
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Failed to open extension download',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setDownloading(false)
    }
  }, [pushToast])

  const extension = status?.extensions[0]
  const connected = status?.connected ?? false
  const relayUrl = deriveRelayUrl()

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
    const restart = draft.replay_state === 'completed'
    const executionId = restart || !draft.replay_execution_id
      ? crypto.randomUUID()
      : draft.replay_execution_id
    const startStep = restart ? 0 : draft.replay_next_step
    const requestIdentity = `${draft.id}:${executionId}:${startStep}:${restart}`
    const idempotencyKey = replayRequestKeysRef.current[requestIdentity] ?? crypto.randomUUID()
    replayRequestKeysRef.current[requestIdentity] = idempotencyKey
    try {
      const result = await replayWebBridgeTeachDraft(
        draft.id,
        draftParameters[draft.id] ?? {},
        executionId,
        startStep,
        idempotencyKey,
        restart,
      )
      delete replayRequestKeysRef.current[requestIdentity]
      if (result.next_step === null) {
        setDraftParameters((current) => {
          const next = { ...current }
          delete next[draft.id]
          return next
        })
      }
      await refresh()
      pushToast({
        tone: 'success',
        title: result.next_step === null
          ? 'Teach draft replay completed'
          : `Teach step ${result.next_step} completed`,
      })
    } catch (err) {
      if (err instanceof ApiValidationError) {
        delete replayRequestKeysRef.current[requestIdentity]
      }
      await refresh()
      pushToast({
        tone: 'error',
        title: 'Teach draft replay stopped',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setReplayingDraftId(null)
    }
  }, [draftParameters, pushToast, refresh])

  const handleResolveReplay = useCallback(async (
    draft: WebBridgeTeachDraft,
    outcome: 'completed' | 'not_completed',
  ) => {
    if (!draft.replay_execution_id) return
    setResolvingDraftId(draft.id)
    try {
      await resolveWebBridgeTeachReplay(
        draft.id,
        draft.replay_execution_id,
        outcome,
      )
      await refresh()
      pushToast({
        tone: 'success',
        title: outcome === 'completed'
          ? 'Teach step marked as completed'
          : 'Teach step marked as not completed',
      })
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Could not resolve Teach step',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setResolvingDraftId(null)
    }
  }, [pushToast, refresh])

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
                Connection address
              </p>
              <CopyRow label="Address" value={relayUrl} />
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
                Click the WebBridge toolbar icon, enter the connection address,
                then save and reconnect.
              </li>
            </ol>
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
                  {(draft.replay_state === 'ambiguous' || draft.replay_state === 'in_flight') && (
                    <div className="space-y-1">
                      <p className="text-xs text-(--color-warning)">
                        Check the browser before confirming whether this step ran.
                      </p>
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => void handleResolveReplay(draft, 'completed')}
                          disabled={resolvingDraftId === draft.id}
                          className="flex-1"
                        >
                          <Check aria-hidden="true" />
                          It ran
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => void handleResolveReplay(draft, 'not_completed')}
                          disabled={resolvingDraftId === draft.id}
                          className="flex-1"
                        >
                          <RefreshCw aria-hidden="true" />
                          It did not run
                        </Button>
                      </div>
                    </div>
                  )}
                  <details className="text-xs text-(--color-text-subtle)">
                    <summary className="cursor-pointer">Workflow YAML</summary>
                    <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap rounded bg-(--bg-2) p-2 font-mono text-[10px]">{draft.workflow_yaml}</pre>
                  </details>
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
                    ) : draft.replay_state !== 'ambiguous' && draft.replay_state !== 'in_flight' ? (
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
                        {draft.replay_state === 'completed'
                          ? 'Run again from step 1'
                          : draft.replay_next_step > 0
                            ? `Run step ${draft.replay_next_step + 1}`
                            : 'Run first step'}
                      </Button>
                    ) : null}
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
                    {e.direction === 'browser_in' ? 'in' : 'out'} · {e.action}
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
