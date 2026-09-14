import { useEffect } from 'react'

import { apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { getPlatform } from '@/hooks/use-platform'
import { useUIStore } from '@/stores/useUIStore'
import { loadBrowserPreferences } from './browserPreferences'

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
            // Where an agent's page appears is the user's call. The panel
            // shares its space with every other tool, so opening one there
            // puts away whatever they were using; the preview does not.
            if (loadBrowserPreferences().agentBrowsingSurface === 'preview') {
              useUIStore.getState().openBrowserPip(sessionId)
            } else {
              useUIStore.getState().openWorkbenchTool('browser')
            }
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
  return withTokenParam(
    `${apiWsBaseUrl()}/team/${encodeURIComponent(sessionId)}/browser/presence`,
  )
}
