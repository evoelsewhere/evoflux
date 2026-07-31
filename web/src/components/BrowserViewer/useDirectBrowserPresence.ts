import { useEffect } from 'react'

import { apiBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { getPlatform } from '@/hooks/use-platform'
import { useUIStore } from '@/stores/useUIStore'

export function useDirectBrowserPresence(sessionId: string | null): void {
  useEffect(() => {
    if (!sessionId || !getPlatform().isTauri) return
    let alive = true
    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (!alive) return
      socket = new WebSocket(presenceUrl(sessionId))
      socket.onmessage = (event) => {
        if (typeof event.data !== 'string') return
        try {
          const message = JSON.parse(event.data) as { action?: string }
          if (message.action === 'open') {
            useUIStore.getState().openWorkbenchTool('browser')
          }
        } catch {
          // Ignore malformed bridge messages.
        }
      }
      socket.onclose = () => {
        socket = null
        if (alive) reconnectTimer = setTimeout(connect, 1000)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      alive = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [sessionId])
}

function presenceUrl(sessionId: string): string {
  const apiBase = apiBaseUrl()
  const wsBase = apiBase.startsWith('http')
    ? apiBase.replace(/^http/, 'ws')
    : `ws://${window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname}:4082/api`
  return withTokenParam(
    `${wsBase}/team/${encodeURIComponent(sessionId)}/browser/presence`,
  )
}
