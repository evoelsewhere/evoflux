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
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { useUIStore } from '@/stores/useUIStore'

/** Close codes the bridge uses to say why it hung up. */
const WS_UNAUTHORIZED = 4401
const WS_DISPLACED = 4409
const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 15_000
const OPEN_CARDS_KEY = STORAGE_KEYS.computerApp.openCards

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
  const bridge = useRef<ComputerAppBridge | null>(null)

  // One bridge for the component's lifetime, so switching chats (or a card
  // opening or closing) only opens and closes the sockets that changed.
  useEffect(() => {
    if (!computerAppSupported()) return
    const created = createComputerAppBridge()
    bridge.current = created
    const stopSaving = restoreOpenCards()
    return () => {
      stopSaving()
      created.dispose()
      if (bridge.current === created) bridge.current = null
    }
  }, [])

  useEffect(() => {
    bridge.current?.sync(sessionKey ? sessionKey.split('\u0000') : [])
  }, [sessionKey])
}

/**
 * Reopen the cards this window had open before a reload, and keep the list
 * saved from now on. Returns a function that stops saving.
 *
 * The desktop keeps an app attached across a reload of the UI, but the
 * cards lived only in memory: they vanished, the agent kept driving an app
 * nobody could see, and a hidden app stayed off-screen until EvoFlux quit.
 * The list is kept in sessionStorage — per window, so a second EvoFlux
 * window does not open (and take over the socket of) another's cards — and
 * a card only comes back for a session the desktop still has attached or
 * stopped.
 */
export function restoreOpenCards(): () => void {
  let saved: unknown = []
  try {
    saved = JSON.parse(sessionStorage.getItem(OPEN_CARDS_KEY) ?? '[]')
  } catch {
    saved = []
  }
  const sessionIds = Array.isArray(saved)
    ? saved.filter((id): id is string => typeof id === 'string')
    : []
  for (const sessionId of sessionIds) {
    void invoke<{ attached?: boolean; stopped?: boolean }>('app_computer_action', {
      sessionId,
      action: 'status',
      params: {},
    })
      .then((status) => {
        if (status?.attached || status?.stopped) useUIStore.getState().openComputerPip(sessionId)
      })
      .catch(() => undefined)
  }
  return useUIStore.subscribe((state, previous) => {
    if (state.computerPipSessionIds === previous.computerPipSessionIds) return
    try {
      sessionStorage.setItem(OPEN_CARDS_KEY, JSON.stringify(state.computerPipSessionIds))
    } catch {
      // Storage unavailable: a reload then loses the cards, as before.
    }
  })
}

export interface ComputerAppBridge {
  /** Keep a socket open for exactly these sessions. */
  sync(sessionIds: readonly string[]): void
  dispose(): void
}

interface BridgeEntry {
  socket: WebSocket | null
  timer: ReturnType<typeof setTimeout> | null
  delay: number
  queue: Promise<void>
  /** Commands received and not yet answered. */
  pending: number
}

/**
 * The set of bridge sockets, one per session.
 *
 * A session that is no longer wanted (its chat is off screen and it has no
 * card) keeps its socket until the commands it already received have been
 * answered: closing mid-command would lose the reply while the desktop
 * still carried the input out, and the agent's retry would do it twice.
 */
export function createComputerAppBridge(): ComputerAppBridge {
  const entries = new Map<string, BridgeEntry>()
  let wanted = new Set<string>()
  let disposed = false

  const retire = (sessionId: string, entry: BridgeEntry) => {
    if (entry.timer) clearTimeout(entry.timer)
    entry.timer = null
    entries.delete(sessionId)
    entry.socket?.close()
  }

  const connect = (sessionId: string) => {
    if (disposed || !wanted.has(sessionId)) return
    const entry = entries.get(sessionId)
      ?? { socket: null, timer: null, delay: RECONNECT_BASE_MS, queue: Promise.resolve(), pending: 0 }
    entries.set(sessionId, entry)
    entry.timer = null
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
      entry.pending += 1
      // One command at a time, in order: the native side is sequential
      // anyway, and a click must not overtake the attach before it.
      entry.queue = entry.queue.then(async () => {
        const reply = await runComputerAppCommand(sessionId, action, params)
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ id, ...reply }))
        entry.pending -= 1
        if (entry.pending === 0 && !wanted.has(sessionId) && entries.get(sessionId) === entry) {
          retire(sessionId, entry)
        }
      })
    }
    socket.onclose = (event) => {
      if (entry.socket === socket) entry.socket = null
      if (disposed || !wanted.has(sessionId) || entries.get(sessionId) !== entry) return
      // Another window took this session, or the token was refused:
      // reconnecting would only fight it or hammer the auth gate.
      if (event.code === WS_DISPLACED || event.code === WS_UNAUTHORIZED) return
      entry.delay = Math.min(entry.delay * 2, RECONNECT_MAX_MS)
      entry.timer = setTimeout(() => connect(sessionId), entry.delay)
    }
    socket.onerror = () => socket.close()
  }

  return {
    sync(sessionIds) {
      if (disposed) return
      wanted = new Set(sessionIds)
      for (const sessionId of wanted) {
        const entry = entries.get(sessionId)
        if (!entry) connect(sessionId)
        else if (!entry.socket && !entry.timer) connect(sessionId)
      }
      for (const [sessionId, entry] of [...entries]) {
        if (!wanted.has(sessionId) && entry.pending === 0) retire(sessionId, entry)
      }
    },
    dispose() {
      disposed = true
      wanted = new Set()
      for (const [sessionId, entry] of [...entries]) retire(sessionId, entry)
    },
  }
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
