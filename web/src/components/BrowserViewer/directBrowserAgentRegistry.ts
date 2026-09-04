import { apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'

export interface DirectBrowserSurfaceTab {
  url: string
  title?: string
}

export interface DirectBrowserSurfaceRegistration {
  instanceId: string
  order: number
  isActive: () => boolean
  getTab: () => DirectBrowserSurfaceTab | null
  execute: (action: string, params: Record<string, unknown>) => Promise<unknown>
  activate: () => void | Promise<void>
  close: () => void
}

interface BrowserSessionRegistry {
  sessionId: string
  surfaces: Map<string, DirectBrowserSurfaceRegistration>
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
  registry.surfaces.set(surface.instanceId, surface)
  registry.listeners.add(onConnectionChange)
  onConnectionChange(registry.connected)
  connectRegistry(registry)

  return () => {
    registry.listeners.delete(onConnectionChange)
    if (registry.surfaces.get(surface.instanceId) === surface) {
      registry.surfaces.delete(surface.instanceId)
    }
    if (registry.surfaces.size === 0) disposeRegistry(registry)
  }
}

export async function runDirectBrowserSessionCommand(
  surfaces: DirectBrowserSurfaceRegistration[],
  action: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  const available = surfaces
    .filter((surface) => surface.getTab() !== null)
    .sort((left, right) => left.order - right.order)
  const selected = available.find((surface) => surface.isActive())
  const active = selected ?? available[0]

  if (action === 'get_tabs') {
    return available.length
      ? available.map((surface, index) => {
          const tab = surface.getTab()
          return `[${index}]${surface === active ? '*' : ''} ${tab?.url ?? ''}`
        }).join('\n')
      : 'No tabs open.'
  }
  if (action === 'switch_tab' || action === 'close_tab') {
    const index = Number(params.index)
    const target = available[index]
    if (!target) throw new Error(`Invalid tab index ${params.index}`)
    const tab = target.getTab()
    if (action === 'switch_tab') {
      await target.activate()
      return `Switched to tab ${index}: ${tab?.url ?? ''}`
    }
    await target.execute('stop', {})
    target.close()
    return `Closed tab ${index}: ${tab?.url ?? ''}`
  }
  if (!active) throw new Error('Desktop browser is unavailable')
  if (action === 'status') {
    const status = await active.execute(action, params)
    return {
      ...(status && typeof status === 'object' ? status : {}),
      tabs: available.map((surface, index) => ({
        index,
        url: surface.getTab()?.url ?? '',
        title: surface.getTab()?.title ?? '',
        active: surface === active,
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
