/**
 * WebBridgeBrowserInfo — compact browser status indicator for WebBridge sessions.
 *
 * Shows the current domain the agent is browsing and the number of connected
 * tabs via the WebBridge extension. Placed in the ChatTopbar center area for
 * WebBridge-tagged sessions. Polls the status endpoint periodically.
 */

import { useEffect, useState, useCallback } from 'react'
import { Globe } from 'lucide-react'
import { getWebBridgeStatus } from '@/api/client'
import type { WebBridgeStatusResponse } from '@/api/types'

const POLL_INTERVAL = 5_000 // 5 seconds

export function WebBridgeBrowserInfo() {
  const [status, setStatus] = useState<WebBridgeStatusResponse | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      setStatus(await getWebBridgeStatus())
    } catch {
      setStatus(null)
    }
  }, [])

  useEffect(() => {
    void fetchStatus()
    const id = setInterval(() => void fetchStatus(), POLL_INTERVAL)
    return () => clearInterval(id)
  }, [fetchStatus])

  const ext = status?.extensions[0]
  const tabCount = status?.extensions.length ?? 0

  if (!status?.connected || !ext?.current_url) return null

  // Extract hostname for compact display
  let hostname = ''
  try {
    hostname = new URL(ext.current_url).hostname
  } catch {
    hostname = ext.current_url.slice(0, 20)
  }

  return (
    <div
      className="flex min-w-0 items-center gap-1 rounded-md bg-(--bg-key) px-1.5 py-0.5"
      title={ext.current_url}
    >
      <Globe size={11} className="shrink-0 text-(--color-success)" aria-hidden="true" />
      <span className="truncate font-mono text-[11px] text-(--color-text-muted)">
        {hostname}
      </span>
      {tabCount > 1 && (
        <span className="shrink-0 rounded bg-(--bg-card) px-1 font-mono text-[10px] text-(--color-text-muted)">
          {tabCount}
        </span>
      )}
    </div>
  )
}
