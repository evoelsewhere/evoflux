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
  commandQueue: Promise<void>
}

const registries = new Map<string, BrowserSessionRegistry>()
let registrationOrder = 0

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
  if (!selected) await active.activate()
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
    commandQueue: Promise.resolve(),
  }
  registries.set(sessionId, registry)
  return registry
}

function connectRegistry(registry: BrowserSessionRegistry): void {
  if (registry.disposed || registry.socket || registry.surfaces.size === 0) return
  const socket = new WebSocket(directBrowserBridgeUrl(registry.sessionId))
  registry.socket = socket
  socket.onopen = () => {
    if (registry.socket !== socket || registry.disposed) return
    socket.send(JSON.stringify({ type: 'ready', version: 2, capabilities: ['multi_tab'] }))
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
  socket.onclose = () => {
    if (registry.socket !== socket) return
    registry.socket = null
    setConnected(registry, false)
    if (!registry.disposed && registry.surfaces.size > 0) {
      registry.reconnectTimer = setTimeout(() => {
        registry.reconnectTimer = null
        connectRegistry(registry)
      }, 1000)
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
