/**
 * Relays `computer_app` commands from the backend to EvoFlux Desktop.
 *
 * One WebSocket per chat session, opened while the chat (or its preview
 * card) is on screen in the Windows or macOS desktop app. Each command becomes a
 * Tauri `invoke`; the native side does the capture and input. A successful
 * `attach` opens the session's preview card so the user sees the app the
 * agent is about to drive before anything else happens to it.
 */

import { useEffect, useRef } from 'react'
import { invoke } from '@tauri-apps/api/core'

import { apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { getPlatform } from '@/hooks/use-platform'
import { useUIStore } from '@/stores/useUIStore'

/** Close codes the bridge uses to say why it hung up. */
const WS_UNAUTHORIZED = 4401
const WS_DISPLACED = 4409
const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 15_000

export const COMPUTER_APP_COMMANDS = [
  'status', 'list_windows', 'attach', 'detach', 'screenshot', 'snapshot', 'find',
  'click', 'hover', 'scroll', 'drag', 'type', 'key', 'invoke', 'set_value', 'restore',
] as const

/** Computer App Control is native desktop work (Win32 or macOS
 * Accessibility); nothing else can serve it. */
export function computerAppSupported(): boolean {
  const platform = getPlatform()
  return platform.isTauri && (platform.os === 'windows' || platform.os === 'macos')
}

export function useComputerAppBridge(
  sessionIds: readonly (string | null)[],
): void {
  const unique = [...new Set(sessionIds.filter((id): id is string => Boolean(id)))]
  const sessionKey = unique.join('\u0000')

  useEffect(() => {
    if (!sessionKey || !computerAppSupported()) return
    let alive = true
    const sockets = new Map<string, {
      socket: WebSocket | null
      timer: ReturnType<typeof setTimeout> | null
      delay: number
      queue: Promise<void>
    }>()

    const connect = (sessionId: string) => {
      if (!alive) return
      const entry = sockets.get(sessionId)
        ?? { socket: null, timer: null, delay: RECONNECT_BASE_MS, queue: Promise.resolve() }
      sockets.set(sessionId, entry)
      const socket = new WebSocket(bridgeUrl(sessionId))
      entry.socket = socket
      socket.onopen = () => {
        entry.delay = RECONNECT_BASE_MS
        socket.send(JSON.stringify({
          type: 'ready',
          protocol_version: 1,
          capabilities: { commands: COMPUTER_APP_COMMANDS, features: ['background_input', 'cancel'] },
        }))
      }
      socket.onmessage = (event) => {
        if (typeof event.data !== 'string') return
        let message: { id?: unknown; type?: unknown; action?: unknown; params?: unknown }
        try {
          message = JSON.parse(event.data) as typeof message
        } catch {
          return
        }
        if (message.type === 'cancel') {
          // The backend stopped waiting for the action in progress: end it
          // now (not behind it in the queue) so a retry cannot repeat it.
          void invoke('app_computer_interrupt', { sessionId }).catch(() => undefined)
          return
        }
        const { id, action } = message
        if (typeof id !== 'string' || typeof action !== 'string') return
        const params = message.params && typeof message.params === 'object'
          ? message.params as Record<string, unknown>
          : {}
        // One command at a time, in order: the native side is sequential
        // anyway, and a click must not overtake the attach before it.
        entry.queue = entry.queue.then(async () => {
          const reply = await runComputerAppCommand(sessionId, action, params)
          if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ id, ...reply }))
        })
      }
      socket.onclose = (event) => {
        if (entry.socket === socket) entry.socket = null
        if (!alive) return
        // Another window took this session, or the token was refused:
        // reconnecting would only fight it or hammer the auth gate.
        if (event.code === WS_DISPLACED || event.code === WS_UNAUTHORIZED) return
        entry.delay = Math.min(entry.delay * 2, RECONNECT_MAX_MS)
        entry.timer = setTimeout(() => connect(sessionId), entry.delay)
      }
      socket.onerror = () => socket.close()
    }

    for (const sessionId of sessionKey.split('\u0000')) connect(sessionId)
    return () => {
      alive = false
      for (const entry of sockets.values()) {
        if (entry.timer) clearTimeout(entry.timer)
        entry.socket?.close()
      }
    }
  }, [sessionKey])
}

/**
 * Release the session's app when its turn ends.
 *
 * An agent between turns is not using the app, and a hidden app stays
 * off-screen for as long as it is attached — so a finished turn hands it
 * back (and closes the card) instead of leaving both behind. The agent
 * attaches again when it next needs the app.
 */
export function useReleaseComputerAppWhenIdle(
  sessionId: string | null,
  working: boolean,
): void {
  const previous = useRef<{ sessionId: string | null; working: boolean }>({
    sessionId: null,
    working: false,
  })
  useEffect(() => {
    // Switching to another chat is not that chat's turn ending.
    const finished = previous.current.sessionId === sessionId
      && previous.current.working
      && !working
    previous.current = { sessionId, working }
    if (!finished || !sessionId || !computerAppSupported()) return
    if (!useUIStore.getState().computerPipSessionIds.includes(sessionId)) return
    void runComputerAppCommand(sessionId, 'detach', {})
  }, [sessionId, working])
}

export async function runComputerAppCommand(
  sessionId: string,
  action: string,
  params: Record<string, unknown>,
): Promise<{ ok: true; result: unknown } | { ok: false; error: string }> {
  try {
    const result = await invoke('app_computer_action', { sessionId, action, params })
    // The card and the attachment live and die together: it opens when an
    // app is attached and closes when it is released.
    if (action === 'attach') useUIStore.getState().openComputerPip(sessionId)
    if (action === 'detach') useUIStore.getState().closeComputerPip(sessionId)
    return { ok: true, result }
  } catch (error) {
    if (action === 'attach') await reopenIfStopped(sessionId)
    return { ok: false, error: error instanceof Error ? error.message : String(error) }
  }
}

/**
 * An attach refused because the user pressed Stop earlier tells the agent to
 * ask for "Allow again" in the preview card — but that card may have been
 * closed since, and it only opens on a successful attach. Show it (in its
 * stopped state) so the user has the button the agent is asking about.
 */
async function reopenIfStopped(sessionId: string): Promise<void> {
  try {
    const status = await invoke<{ stopped?: boolean }>('app_computer_action', {
      sessionId,
      action: 'status',
      params: {},
    })
    if (status?.stopped) useUIStore.getState().openComputerPip(sessionId)
  } catch {
    // Nothing to show: the desktop could not say.
  }
}

function bridgeUrl(sessionId: string): string {
  return withTokenParam(
    `${apiWsBaseUrl()}/team/${encodeURIComponent(sessionId)}/computer/agent`,
  )
}
