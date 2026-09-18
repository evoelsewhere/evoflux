import { useEffect } from 'react'

import { apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { getPlatform } from '@/hooks/use-platform'
import { useUIStore } from '@/stores/useUIStore'

export function useDirectBrowserPresence(
  sessionIds: string | null | readonly (string | null)[],
): void {
  const normalizedSessionIds = typeof sessionIds === 'string' || sessionIds === null
    ? sessionIds ? [sessionIds] : []
    : [...new Set(sessionIds.filter((id): id is string => Boolean(id)))]
  const sessionKey = normalizedSessionIds.join('\u0000')

  useEffect(() => {
    if (!sessionKey || !getPlatform().isTauri) return
    let alive = true
    const sockets = new Map<string, {
      socket: WebSocket | null
      reconnectTimer: ReturnType<typeof setTimeout> | null
    }>()

    const connect = (sessionId: string) => {
      if (!alive) return
      const entry = sockets.get(sessionId) ?? { socket: null, reconnectTimer: null }
      sockets.set(sessionId, entry)
      entry.socket = new WebSocket(presenceUrl(sessionId))
      entry.socket.onmessage = (event) => {
        if (typeof event.data !== 'string') return
        try {
          const message = JSON.parse(event.data) as { action?: string }
          if (message.action === 'open') {
            // Agent browsing never steals the user's workbench. Each session
            // gets its own floating preview, and the chat stacks multiple
            // previews when agents in different sessions are active.
            useUIStore.getState().openBrowserPip(sessionId)
          }
        } catch {
          // Ignore malformed bridge messages.
        }
      }
      entry.socket.onclose = () => {
        entry.socket = null
        if (alive) entry.reconnectTimer = setTimeout(() => connect(sessionId), 1000)
      }
      entry.socket.onerror = () => entry.socket?.close()
    }

    for (const sessionId of sessionKey.split('\u0000')) connect(sessionId)
    return () => {
      alive = false
      for (const entry of sockets.values()) {
        if (entry.reconnectTimer) clearTimeout(entry.reconnectTimer)
        entry.socket?.close()
      }
    }
  }, [sessionKey])
}

function presenceUrl(sessionId: string): string {
  return withTokenParam(
    `${apiWsBaseUrl()}/team/${encodeURIComponent(sessionId)}/browser/presence`,
  )
}
