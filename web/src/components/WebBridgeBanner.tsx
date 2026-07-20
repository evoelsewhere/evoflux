/**
 * WebBridgeBanner — in-chat notice for ``webbridge``-tagged sessions shown
 * while the browser extension is disconnected: without it the agent can't
 * drive the user's real browser.
 *
 * Polls the status endpoint on mount + every 30s (cleared on unmount) and
 * renders nothing when the session isn't tagged, the extension is connected,
 * or the banner was dismissed. Dismissal is persisted per session id in
 * localStorage (a JSON map) — dismissed stays dismissed for that session.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Globe, Loader2, X } from 'lucide-react'
import { getWebBridgeStatus, launchWebBridgeBrowser } from '@/api/client'
import { useTeamSessionsQuery } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { WebBridgeStatusDialog } from '@/components/shell/WebBridgeStatusDialog'
import { Button } from '@/components/ui/button'

const POLL_INTERVAL_MS = 30_000
/** After a successful launch the extension takes a few seconds to handshake —
 *  re-check once on this delay instead of waiting out the next poll. */
const LAUNCH_RECHECK_MS = 5_000

function readDismissedMap(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.webbridgeBannerDismissed)
    const parsed: unknown = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, boolean>)
      : {}
  } catch {
    return {}
  }
}

export function WebBridgeBanner({ sessionId }: { sessionId: string }) {
  const sessions = useTeamSessionsQuery('forge')
  const isTagged =
    sessions.data?.pages.some((page) =>
      page.data.some((s) => s.id === sessionId && s.tags?.includes('webbridge')),
    ) ?? false

  // Optimistic "connected" so the banner doesn't flash before the first
  // status response lands.
  const [connected, setConnected] = useState(true)
  const [dismissedMap, setDismissedMap] = useState<Record<string, boolean>>(readDismissedMap)
  const [guideOpen, setGuideOpen] = useState(false)
  const [launching, setLaunching] = useState(false)
  const pushToast = useToastStore((s) => s.push)
  const recheckTimer = useRef<number | null>(null)

  const dismissed = Boolean(dismissedMap[sessionId])
  const active = isTagged && !dismissed

  const check = useCallback(async () => {
    try {
      setConnected((await getWebBridgeStatus()).connected)
    } catch {
      // Backend unreachable or unauthorized — treat as not connected.
      setConnected(false)
    }
  }, [])

  useEffect(() => {
    if (!active) return
    void check()
    const timer = setInterval(() => void check(), POLL_INTERVAL_MS)
    return () => {
      clearInterval(timer)
      if (recheckTimer.current !== null) window.clearTimeout(recheckTimer.current)
    }
  }, [active, check])

  const handleLaunch = useCallback(async () => {
    setLaunching(true)
    try {
      const result = await launchWebBridgeBrowser()
      pushToast({ tone: result.ok ? 'success' : 'info', title: result.message })
      if (result.ok) {
        recheckTimer.current = window.setTimeout(() => void check(), LAUNCH_RECHECK_MS)
      }
    } catch (err) {
      // 404 detail carries the manual-install instructions — surface as-is.
      pushToast({
        tone: 'error',
        title: 'Could not launch browser',
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setLaunching(false)
    }
  }, [check, pushToast])

  const handleDismiss = useCallback(() => {
    const next = { ...readDismissedMap(), [sessionId]: true }
    try {
      localStorage.setItem(STORAGE_KEYS.webbridgeBannerDismissed, JSON.stringify(next))
    } catch {
      // Storage unavailable (private mode) — in-memory dismiss still works.
    }
    setDismissedMap(next)
  }, [sessionId])

  if (!active || connected) return null

  return (
    <>
      <div className="mx-3 mt-3 flex flex-col gap-3 rounded-xl border border-(--color-warning)/35 bg-(--color-warning-subtle) p-3 text-sm text-(--color-text) shadow-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <Globe
            className="mt-0.5 h-4 w-4 shrink-0 text-(--color-warning)"
            aria-hidden="true"
          />
          <div className="min-w-0">
            <p className="font-medium">WebBridge extension not connected</p>
            <p className="mt-0.5 text-xs text-(--color-text-muted)">
              The agent can't drive your real browser until the extension
              connects.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 self-start sm:self-center">
          <Button size="sm" variant="outline" onClick={() => setGuideOpen(true)}>
            Install guide
          </Button>
          <Button size="sm" onClick={() => void handleLaunch()} disabled={launching}>
            {launching && <Loader2 className="animate-spin" aria-hidden="true" />}
            Launch browser with WebBridge
          </Button>
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) md:h-8 md:w-8"
            onClick={handleDismiss}
            aria-label="Dismiss WebBridge notice"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
      <WebBridgeStatusDialog open={guideOpen} onOpenChange={setGuideOpen} />
    </>
  )
}
