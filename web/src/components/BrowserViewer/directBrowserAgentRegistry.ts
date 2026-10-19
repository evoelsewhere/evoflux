import { apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'

export interface DirectBrowserSurfaceTab {
  url: string
  title?: string
  /** The page of this session's browser the user is looking at. */
  active?: boolean
}

export interface DirectBrowserSurfaceRegistration {
  /**
   * One surface per chat session — `'session'` — so the agent sees the
   * shared tab list the PiP and the panel both show, not one entry per
   * open view.
   */
  instanceId: string
  order: number
  isActive: () => boolean
  getTab: () => DirectBrowserSurfaceTab | null
  /** Every page of this session's browser, in tab order. */
  getTabs: () => DirectBrowserSurfaceTab[]
  /** Bring one of `getTabs()`'s pages to the front. */
  selectTab: (index: number) => Promise<void> | void
  /** Close one of `getTabs()`'s pages. */
  closeTab: (index: number) => Promise<void> | void
  /**
   * Why this surface has no tab, in a form worth showing the agent.
   *
   * "Desktop browser is unavailable" was the answer to every one of the
   * several distinct reasons a panel can have no WebView, and it names
   * none of them — so the only way to find out was to go and look at the
   * app.
   */
  unavailableReason: () => string
  execute: (action: string, params: Record<string, unknown>) => Promise<unknown>
  activate: () => void | Promise<void>
  close: () => void
}

interface BrowserSessionRegistry {
  sessionId: string
  surfaces: Map<string, DirectBrowserSurfaceRegistration>
  /** Live registrations per surface key — one surface per session. */
  refCounts: Map<string, number>
  listeners: Set<(connected: boolean) => void>
  socket: WebSocket | null
  reconnectTimer: ReturnType<typeof setTimeout> | null
  connected: boolean
  disposed: boolean
  /** Another window took this session's browser; do not race it back. */
  displaced: boolean
  /** The auth gate refused us; retrying cannot supply a token. */
  unauthorized: boolean
  reconnectDelay: number
  commandQueue: Promise<void>
}

/** Close codes the bridge uses to say *why* it hung up. */
const WS_UNAUTHORIZED = 4401
const WS_DISPLACED = 4409
const RECONNECT_BASE_MS = 1_000

const registries = new Map<string, BrowserSessionRegistry>()
let registrationOrder = 0
const DIRECT_BROWSER_COMMANDS = [
  'start', 'stop', 'status', 'navigate', 'back', 'forward', 'reload', 'wait',
  'snapshot', 'find', 'query', 'inspect', 'html', 'accessibility', 'extract', 'screenshot',
  'click', 'click_at', 'dblclick', 'hover', 'focus', 'fill', 'type', 'clear',
  'submit', 'press', 'select', 'set_checked', 'set_files', 'drag', 'scroll',
  'scroll_into_view', 'dispatch_event', 'console', 'network', 'dialogs', 'popups',
  'dialog_behavior', 'permission_requests', 'resolve_permission', 'performance',
  'clear_logs', 'storage', 'cookies', 'http', 'download', 'page_assets',
  'debug_summary', 'evaluate', 'resize', 'reset_viewport', 'zoom', 'print', 'save_pdf',
  'clipboard_read', 'clipboard_write', 'new_tab', 'close_tab', 'get_tabs',
  'switch_tab',
]

/**
 * Actions that need the surface actually on screen.
 *
 * A hidden WebView keeps running its page, so anything expressed against
 * the DOM works on a background tab. These do not: they capture or drive
 * real pixels, and a hidden view has none.
 */
const VISUAL_ACTIONS = new Set([
  'screenshot',
  'click_at',
  'drag',
  'print',
  'save_pdf',
  'clipboard_read',
  'clipboard_write',
])

export function nextBrowserSurfaceOrder(): number {
  registrationOrder += 1
  return registrationOrder
}

export function registerDirectBrowserSurface(
  sessionId: string,
  surface: DirectBrowserSurfaceRegistration,
  onConnectionChange: (connected: boolean) => void,
): () => void {
  const registry = getOrCreateRegistry(sessionId)
  // One surface per session: every view of the session's browser registers
  // the same session surface against the shared tab list, so the agent
  // never sees a page once per open view. Later registrations stand in for
  // earlier ones — their handlers all read the same shared state.
  const key = surface.instanceId
  registry.refCounts.set(key, (registry.refCounts.get(key) ?? 0) + 1)
  registry.surfaces.set(key, surface)
  registry.listeners.add(onConnectionChange)
  onConnectionChange(registry.connected)
  connectRegistry(registry)

  return () => {
    registry.listeners.delete(onConnectionChange)
    const remaining = (registry.refCounts.get(key) ?? 1) - 1
    registry.refCounts.set(key, remaining)
    if (remaining <= 0) {
      registry.refCounts.delete(key)
      if (registry.surfaces.get(key) === surface) {
        registry.surfaces.delete(key)
      }
    }
    if (registry.surfaces.size === 0) disposeRegistry(registry)
  }
}

/** The surfaces registered for a session — one per session by design. */
export function directBrowserSessionSurfaces(
  sessionId: string,
): DirectBrowserSurfaceRegistration[] {
  return [...(registries.get(sessionId)?.surfaces.values() ?? [])]
}

export async function runDirectBrowserSessionCommand(
  surfaces: DirectBrowserSurfaceRegistration[],
  action: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  const available = surfaces
    .filter((surface) => surface.getTabs().length > 0)
    .sort((left, right) => left.order - right.order)
  const selected = available.find((surface) => surface.isActive())
  const active = selected ?? available[0]
  // One surface per session, so its tab list is the session's pages — the
  // same list the PiP cards and the panel both show.
  const tabs = active?.getTabs() ?? []
  const activeIndex = Math.max(
    0,
    tabs.findIndex((tab) => tab.active),
  )

  if (action === 'get_tabs') {
    return tabs.length
      ? tabs.map((tab, index) => {
          return `[${index}]${index === activeIndex ? '*' : ''} ${tab.url}`
        }).join('\n')
      : 'No tabs open.'
  }
  if (action === 'switch_tab' || action === 'close_tab') {
    const index = Number(params.index)
    const tab = tabs[index]
    if (!active || !tab) throw new Error(`Invalid tab index ${params.index}`)
    if (action === 'switch_tab') {
      await active.selectTab(index)
      return `Switched to tab ${index}: ${tab.url}`
    }
    await active.execute('stop', {})
    await active.closeTab(index)
    return `Closed tab ${index}: ${tab.url}`
  }
  if (!active) {
    const reasons = [...new Set(surfaces.map((surface) => surface.unavailableReason()))]
      .filter(Boolean)
    throw new Error(
      surfaces.length === 0
        ? 'No browser panel is open in EvoFlux Desktop. Open one from the workbench, then retry.'
        : `The browser panel has no page yet: ${reasons.join('; ')}`,
    )
  }
  if (action === 'status') {
    const status = await active.execute(action, params)
    return {
      ...(status && typeof status === 'object' ? status : {}),
      tabs: tabs.map((tab, index) => ({
        index,
        url: tab.url,
        title: tab.title ?? '',
        active: index === activeIndex,
      })),
    }
  }
  // Driving a background tab used to yank the workbench over to the
  // browser mid-command, so reading a page while you worked in the
  // terminal stole your screen. A hidden child WebView still runs its
  // page, so DOM-level work needs no such interruption — only the actions
  // that read or hit real pixels do.
  if (!selected && VISUAL_ACTIONS.has(action)) await active.activate()
  return active.execute(action, params)
}

function getOrCreateRegistry(sessionId: string): BrowserSessionRegistry {
  const existing = registries.get(sessionId)
  if (existing) return existing
  const registry: BrowserSessionRegistry = {
    sessionId,
    surfaces: new Map(),
    refCounts: new Map(),
    listeners: new Set(),
    socket: null,
    reconnectTimer: null,
    connected: false,
    disposed: false,
    displaced: false,
    unauthorized: false,
    reconnectDelay: RECONNECT_BASE_MS,
    commandQueue: Promise.resolve(),
  }
  registries.set(sessionId, registry)
  return registry
}

function connectRegistry(registry: BrowserSessionRegistry): void {
  if (registry.disposed || registry.socket || registry.surfaces.size === 0) return
  if (registry.displaced || registry.unauthorized) return
  const socket = new WebSocket(directBrowserBridgeUrl(registry.sessionId))
  registry.socket = socket
  socket.onopen = () => {
    if (registry.socket !== socket || registry.disposed) return
    socket.send(JSON.stringify({
      type: 'ready',
      protocol_version: 2,
      version: 2,
      capabilities: {
        commands: DIRECT_BROWSER_COMMANDS,
        features: ['multi_tab', 'responsive_viewport', 'native_input', 'dialog_handoff'],
      },
    }))
    registry.reconnectDelay = RECONNECT_BASE_MS
    setConnected(registry, true)
  }
  socket.onmessage = (event) => {
    if (typeof event.data !== 'string') return
    let message: Record<string, unknown>
    try {
      message = JSON.parse(event.data) as Record<string, unknown>
    } catch {
      return
    }
    const id = message.id
    const action = message.action
    if (typeof id !== 'string' || typeof action !== 'string') return
    const params = message.params && typeof message.params === 'object'
      ? message.params as Record<string, unknown>
      : {}
    registry.commandQueue = registry.commandQueue.then(async () => {
      try {
        const result = await runDirectBrowserSessionCommand(
          [...registry.surfaces.values()],
          action,
          params,
        )
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ id, ok: true, result }))
        }
      } catch (error) {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            id,
            ok: false,
            error: error instanceof Error ? error.message : String(error),
          }))
        }
      }
    })
  }
  socket.onclose = (event) => {
    if (registry.socket !== socket) return
    registry.socket = null
    setConnected(registry, false)
    // A displaced socket must not reconnect: another window took this
    // session's browser, and racing it back would put the two into a
    // takeover loop, each closing the other every second.
    if (event.code === WS_DISPLACED) {
      registry.displaced = true
      return
    }
    // 4401 is the auth gate refusing us. Retrying cannot fix a missing or
    // wrong token, so a reconnect here is a hot loop against the server.
    if (event.code === WS_UNAUTHORIZED) {
      registry.unauthorized = true
      return
    }
    if (!registry.disposed && registry.surfaces.size > 0) {
      // Back off rather than hammering a server that is down or restarting.
      registry.reconnectDelay = Math.min(registry.reconnectDelay * 2, 15_000)
      registry.reconnectTimer = setTimeout(() => {
        registry.reconnectTimer = null
        connectRegistry(registry)
      }, registry.reconnectDelay)
    }
  }
  socket.onerror = () => socket.close()
}

function setConnected(registry: BrowserSessionRegistry, connected: boolean): void {
  registry.connected = connected
  for (const listener of registry.listeners) listener(connected)
}

function disposeRegistry(registry: BrowserSessionRegistry): void {
  registry.disposed = true
  if (registry.reconnectTimer) clearTimeout(registry.reconnectTimer)
  registry.socket?.close()
  registry.socket = null
  setConnected(registry, false)
  registries.delete(registry.sessionId)
}

function directBrowserBridgeUrl(sessionId: string): string {
  return withTokenParam(
    `${apiWsBaseUrl()}/team/${encodeURIComponent(sessionId)}/browser/agent`,
  )
}
