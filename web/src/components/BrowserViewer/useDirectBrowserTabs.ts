import { useCallback, useEffect, useRef, useState } from 'react'
import type { Webview } from '@tauri-apps/api/webview'

import { apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { getPlatform } from '@/hooks/use-platform'

export interface DirectBrowserTab {
  id: string
  label: string
  url: string
}

export interface BrowserPageDialog {
  id?: number
  ts: number
  type: 'alert' | 'confirm' | 'prompt'
  message: string
  default_value?: string
  response?: 'accepted' | 'dismissed'
}

export interface BrowserViewportOverride {
  width: number
  height: number
}

interface UseDirectBrowserTabsOptions {
  sessionId: string
  instanceId?: string
  viewportRef: React.RefObject<HTMLDivElement | null>
  enabled: boolean
  visible: boolean
  bridgeEnabled?: boolean
  initialUrl?: string
  singleTab?: boolean
  zoom: number
  devtools: boolean
  onError: (message: string) => void
  onRequestNewTab?: (url: string) => void
}

export interface NativeBounds {
  x: number
  y: number
  width: number
  height: number
}

export interface BrowserViewportLayout extends NativeBounds {
  scale: number
}

export interface BrowserWaitProbe {
  attached?: boolean
  visible?: boolean
  text?: string
  url?: string
  readyState?: string
}

const NEW_TAB_URL = '/browser-new-tab.html'
const BROWSER_DATA_DIRECTORY = 'browser-profile'
const BROWSER_DATA_STORE_ID = [
  0x45, 0x76, 0x6f, 0x46, 0x6c, 0x75, 0x78, 0x42,
  0x72, 0x6f, 0x77, 0x73, 0x65, 0x72, 0x00, 0x01,
]

export function useDirectBrowserTabs({
  sessionId,
  instanceId = 'default',
  viewportRef,
  enabled,
  visible,
  bridgeEnabled = true,
  initialUrl = NEW_TAB_URL,
  singleTab = false,
  zoom,
  devtools,
  onError,
  onRequestNewTab,
}: UseDirectBrowserTabsOptions) {
  const platform = getPlatform()
  const supported = platform.isTauri && platform.os !== 'ios' && platform.os !== 'android'
  const webviewsRef = useRef(new Map<string, Webview>())
  const activeIdRef = useRef<string | null>(null)
  const tabsRef = useRef<DirectBrowserTab[]>([])
  const agentHandlerRef = useRef<(
    action: string,
    params: Record<string, unknown>,
  ) => Promise<unknown>>(async () => {
    throw new Error('Browser is not ready')
  })
  const counterRef = useRef(0)
  const boundsRef = useRef<NativeBounds | null>(null)
  const viewportOverrideRef = useRef<BrowserViewportOverride | null>(null)
  const viewportScaleRef = useRef(1)
  const lastDialogKeyRef = useRef('')
  const visibilityRef = useRef(new Map<string, boolean>())
  const creatingRef = useRef(false)
  const [tabs, setTabs] = useState<DirectBrowserTab[]>([])
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [agentConnected, setAgentConnected] = useState(false)
  const [pageDialog, setPageDialog] = useState<BrowserPageDialog | null>(null)

  activeIdRef.current = activeTabId

  const invokeFor = useCallback(async <T,>(
    command: string,
    label: string,
    args: Record<string, unknown> = {},
  ): Promise<T> => {
    const { invoke } = await import('@tauri-apps/api/core')
    return invoke<T>(command, { label, ...args })
  }, [])

  const waitForPageReady = useCallback(async (label: string) => {
    let lastError: unknown
    for (let attempt = 0; attempt < 50; attempt += 1) {
      try {
        await invokeFor('app_browser_webview_agent_action', label, {
          action: 'exists',
          params: { selector: 'html' },
        })
        await invokeFor('app_browser_webview_agent_action', label, {
          action: 'instrument',
          params: {},
        })
        return
      } catch (error) {
        lastError = error
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
    }
    throw lastError instanceof Error
      ? lastError
      : new Error('Browser page did not become ready')
  }, [invokeFor])

  const waitForNavigation = useCallback(async (
    label: string,
    requestedUrl: string,
    previousUrl: string,
  ): Promise<string> => {
    const requested = normalizeComparableUrl(requestedUrl)
    const previous = normalizeComparableUrl(previousUrl)
    let current = previousUrl
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        const status = await invokeFor<{ url?: string; readyState?: string }>(
          'app_browser_webview_agent_action',
          label,
          { action: 'status', params: {} },
        )
        current = status.url ?? current
        const normalized = normalizeComparableUrl(current)
        const committed = status.readyState === 'interactive' || status.readyState === 'complete'
        if (
          committed
          && (
            normalized === requested
            || (normalized !== previous && !isBrowserNewTab(current))
          )
        ) {
          return current
        }
      } catch {
        // Wry drops evaluation callbacks while the target document is loading.
      }
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    throw new Error(`Browser navigation did not commit: ${requestedUrl}`)
  }, [invokeFor])

  const createTab = useCallback(async (initialUrl = NEW_TAB_URL) => {
    if (!supported || !enabled || creatingRef.current) return
    if (singleTab && tabsRef.current.length > 0) return tabsRef.current[0]
    const viewport = viewportRef.current
    if (!viewport) return
    const rect = viewport.getBoundingClientRect()
    if (rect.width < 2 || rect.height < 2) return

    creatingRef.current = true
    setCreating(true)
    try {
      const [{ Webview }, { getCurrentWindow }] = await Promise.all([
        import('@tauri-apps/api/webview'),
        import('@tauri-apps/api/window'),
      ])
      const id = `${Date.now().toString(36)}-${counterRef.current++}`
      const safeSession = sessionId.replace(/[^a-zA-Z0-9_-]/g, '').slice(-18)
      const safeInstance = instanceId.replace(/[^a-zA-Z0-9_-]/g, '').slice(-18)
      const label = `browser-${safeSession}-${safeInstance}-${id}`
      const current = webviewsRef.current.get(activeIdRef.current ?? '')
      await current?.hide().catch(() => {})

      let webview = new Webview(getCurrentWindow(), label, {
        url: initialUrl,
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.max(1, Math.round(rect.width)),
        height: Math.max(1, Math.round(rect.height)),
        focus: true,
        incognito: false,
        dataDirectory: BROWSER_DATA_DIRECTORY,
        dataStoreIdentifier: BROWSER_DATA_STORE_ID,
        devtools,
        zoomHotkeysEnabled: true,
      })
      await new Promise<void>((resolve, reject) => {
        let settled = false
        const timeout = window.setTimeout(() => {
          void Webview.getByLabel(label).then((existing) => {
            if (settled) return
            if (existing) {
              webview = existing
              finish(resolve)
            } else {
              finish(() => reject(new Error('Timed out creating browser WebView')))
            }
          })
        }, 5000)
        const finish = (callback: () => void) => {
          if (settled) return
          settled = true
          window.clearTimeout(timeout)
          callback()
        }
        void webview.once('tauri://created', () => finish(resolve))
        void webview.once<string>('tauri://error', (event) => {
          finish(() => reject(new Error(String(event.payload))))
        })
      })

      webviewsRef.current.set(id, webview)
      visibilityRef.current.set(id, true)
      boundsRef.current = null
      const tab = { id, label, url: initialUrl }
      tabsRef.current = [...tabsRef.current, tab]
      setTabs(tabsRef.current)
      activeIdRef.current = id
      setActiveTabId(id)
      await webview.setZoom(zoom / 100)
      await webview.setFocus()
      await waitForPageReady(label)
      return tab
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      creatingRef.current = false
      setCreating(false)
    }
  }, [devtools, enabled, instanceId, onError, sessionId, singleTab, supported, viewportRef, waitForPageReady, zoom])

  useEffect(() => {
    if (!supported || !enabled || tabs.length > 0 || creating) return
    void createTab(initialUrl)
  }, [createTab, creating, enabled, initialUrl, supported, tabs.length])

  const selectTab = useCallback(async (id: string) => {
    if (id === activeIdRef.current) return
    const previous = webviewsRef.current.get(activeIdRef.current ?? '')
    const next = webviewsRef.current.get(id)
    await previous?.hide().catch(() => {})
    visibilityRef.current.set(activeIdRef.current ?? '', false)
    activeIdRef.current = id
    setActiveTabId(id)
    if (visible && next) {
      await next.show()
      await next.setFocus()
      visibilityRef.current.set(id, true)
    }
  }, [visible])

  const closeTab = useCallback(async (id: string) => {
    const closingIndex = tabs.findIndex((tab) => tab.id === id)
    const webview = webviewsRef.current.get(id)
    await webview?.close().catch(() => {})
    webviewsRef.current.delete(id)
    visibilityRef.current.delete(id)

    const remaining = tabs.filter((tab) => tab.id !== id)
    tabsRef.current = remaining
    setTabs(remaining)
    if (activeIdRef.current === id) {
      const replacement = remaining[Math.min(closingIndex, remaining.length - 1)]
      activeIdRef.current = replacement?.id ?? null
      setActiveTabId(replacement?.id ?? null)
      if (replacement) {
        const next = webviewsRef.current.get(replacement.id)
        if (visible && next) {
          await next.show()
          await next.setFocus()
          visibilityRef.current.set(replacement.id, true)
        }
      } else if (enabled && !singleTab) {
        queueMicrotask(() => void createTab())
      }
    }
  }, [createTab, enabled, singleTab, tabs, visible])

  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? null

  const navigate = useCallback(async (url: string) => {
    if (!activeTab) return
    try {
      await invokeFor('app_browser_webview_navigate', activeTab.label, { url })
      const committedUrl = await waitForNavigation(activeTab.label, url, activeTab.url)
      tabsRef.current = tabsRef.current.map((tab) => tab.id === activeTab.id ? { ...tab, url: committedUrl } : tab)
      setTabs(tabsRef.current)
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    }
  }, [activeTab, invokeFor, onError, waitForNavigation])

  const command = useCallback(async (
    action: 'back' | 'forward' | 'reload' | 'focus' | 'print' | 'devtools',
  ) => {
    if (!activeTab) return
    try {
      await invokeFor('app_browser_webview_command', activeTab.label, { action })
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    }
  }, [activeTab, invokeFor, onError])

  const clearBrowsingData = useCallback(async () => {
    if (!activeTab) return
    await invokeFor('app_browser_webview_command', activeTab.label, {
      action: 'clear_data',
      value: null,
      backwards: null,
    })
  }, [activeTab, invokeFor])

  const find = useCallback(async (query: string, backwards = false) => {
    if (!activeTab || !query) return
    await invokeFor('app_browser_webview_command', activeTab.label, {
      action: 'find',
      value: query,
      backwards,
    })
  }, [activeTab, invokeFor])

  const closeAll = useCallback(async () => {
    for (const webview of webviewsRef.current.values()) {
      await webview.close().catch(() => {})
    }
    webviewsRef.current.clear()
    visibilityRef.current.clear()
    tabsRef.current = []
    activeIdRef.current = null
    setTabs([])
    setActiveTabId(null)
  }, [])

  const applyAgentViewport = useCallback(async (tabId: string) => {
    const viewport = viewportRef.current
    const webview = webviewsRef.current.get(tabId)
    if (!viewport || !webview) throw new Error('Desktop browser is unavailable')
    const rect = viewport.getBoundingClientRect()
    const layout = browserViewportLayout({
      x: rect.left,
      y: rect.top,
      width: rect.width,
      height: rect.height,
    }, viewportOverrideRef.current)
    const { LogicalPosition, LogicalSize } = await import('@tauri-apps/api/dpi')
    await Promise.all([
      webview.setPosition(new LogicalPosition(layout.x, layout.y)),
      webview.setSize(new LogicalSize(layout.width, layout.height)),
      webview.setZoom(viewportOverrideRef.current ? layout.scale : zoom / 100),
    ])
    viewportScaleRef.current = layout.scale
    boundsRef.current = {
      x: layout.x,
      y: layout.y,
      width: layout.width,
      height: layout.height,
    }
  }, [viewportRef, zoom])

  const executeAgentCommand = useCallback(async (
    action: string,
    params: Record<string, unknown>,
  ): Promise<unknown> => {
    const getActive = () => tabsRef.current.find(
      (tab) => tab.id === activeIdRef.current,
    ) ?? null
    const ensureActive = async () => {
      const existing = getActive()
      if (existing) return existing
      for (let attempt = 0; attempt < 40; attempt += 1) {
        const created = await createTab()
        if (created) return created
        await new Promise((resolve) => setTimeout(resolve, 100))
        const mounted = getActive()
        if (mounted) return mounted
      }
      return null
    }

    if (action === 'start') {
      const tab = await ensureActive()
      if (!tab) throw new Error('Could not create a desktop browser tab')
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'instrument',
        params: {},
      })
      return `Desktop browser ready: ${tab.url}`
    }
    if (action === 'stop') {
      await closeAll()
      return 'Desktop browser closed.'
    }
    if (action === 'get_tabs') {
      return tabsRef.current.length
        ? tabsRef.current.map((tab, index) =>
            `[${index}]${tab.id === activeIdRef.current ? '*' : ''} ${tab.url}`,
          ).join('\n')
        : 'No tabs open.'
    }
    if (action === 'new_tab') {
      const url = typeof params.url === 'string' ? params.url : NEW_TAB_URL
      if (singleTab && onRequestNewTab) {
        onRequestNewTab(url)
        return `New workbench browser tab requested: ${url}`
      }
      const tab = await createTab(url)
      if (!tab) throw new Error('Could not create a desktop browser tab')
      return `New tab: ${tab.url}`
    }
    if (action === 'close_tab' || action === 'switch_tab') {
      const index = Number(params.index)
      const tab = tabsRef.current[index]
      if (!tab) throw new Error(`Invalid tab index ${params.index}`)
      if (action === 'close_tab') {
        await closeTab(tab.id)
        return `Closed tab ${index}: ${tab.url}`
      }
      await selectTab(tab.id)
      return `Switched to tab ${index}: ${tab.url}`
    }

    const tab = await ensureActive()
    if (!tab) throw new Error('Desktop browser is unavailable')
    if (action === 'status') {
      const status = await invokeFor<{ url?: string; title?: string; readyState?: string }>(
        'app_browser_webview_agent_action',
        tab.label,
        { action: 'status', params: {} },
      )
      return {
        ...status,
        tabs: tabsRef.current.map((item, index) => ({
          index,
          url: item.url,
          title: item.id === tab.id ? status.title ?? '' : '',
        })),
      }
    }
    if (action === 'navigate') {
      const url = typeof params.url === 'string' ? params.url : ''
      if (!url) throw new Error('navigate requires a URL')
      await invokeFor('app_browser_webview_navigate', tab.label, { url })
      const committedUrl = await waitForNavigation(tab.label, url, tab.url)
      tabsRef.current = tabsRef.current.map((item) => item.id === tab.id
        ? { ...item, url: committedUrl }
        : item)
      setTabs(tabsRef.current)
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'instrument',
        params: {},
      })
      return `Navigated to ${url}`
    }
    if (action === 'back' || action === 'forward' || action === 'reload') {
      await invokeFor('app_browser_webview_command', tab.label, { action })
      await waitForPageReady(tab.label)
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'instrument',
        params: {},
      })
      return `${action} completed`
    }
    if (action === 'wait') {
      const rawSeconds = params.seconds == null ? 2 : Number(params.seconds)
      const seconds = Math.max(0, Math.min(30, Number.isFinite(rawSeconds) ? rawSeconds : 2))
      const selector = typeof params.selector === 'string' ? params.selector : ''
      const expectedState = typeof params.state === 'string' ? params.state : 'attached'
      const expectedText = typeof params.text === 'string' ? params.text : ''
      const urlContains = typeof params.url_contains === 'string' ? params.url_contains : ''
      const loadState = typeof params.load_state === 'string' ? params.load_state : ''
      if (!selector && !expectedText && !urlContains && !loadState) {
        await new Promise((resolve) => setTimeout(resolve, seconds * 1000))
        return `Waited ${seconds.toFixed(1)}s`
      }
      const deadline = Date.now() + seconds * 1000
      do {
        const probe = await invokeFor<BrowserWaitProbe>('app_browser_webview_agent_action', tab.label, {
          action: 'probe',
          params: { selector: selector || undefined },
        })
        if (browserWaitConditionSatisfied(probe, {
          selector,
          state: expectedState,
          text: expectedText,
          urlContains,
          loadState,
        })) {
          return `Wait condition satisfied${selector ? ` for "${selector}"` : ''}`
        }
        await new Promise((resolve) => setTimeout(resolve, 100))
      } while (Date.now() < deadline)
      throw new Error(`Timeout waiting for browser condition${selector ? `: ${selector}` : ''}`)
    }
    if (action === 'resize') {
      const presets: Record<string, [number, number]> = {
        mobile: [375, 812],
        tablet: [768, 1024],
        desktop: [1280, 800],
      }
      const preset = typeof params.preset === 'string' ? presets[params.preset] : undefined
      const width = preset?.[0] ?? Number(params.width)
      const height = preset?.[1] ?? Number(params.height)
      if (!Number.isFinite(width) || !Number.isFinite(height)) {
        throw new Error('resize requires a preset or width and height')
      }
      viewportOverrideRef.current = {
        width: Math.max(200, Math.min(4000, width)),
        height: Math.max(200, Math.min(4000, height)),
      }
      // Apply synchronously for the command response; the animation-frame
      // synchronizer keeps the same override stable as app chrome moves.
      boundsRef.current = null
      await applyAgentViewport(tab.id)
      if (params.color_scheme) {
        await invokeFor('app_browser_webview_agent_action', tab.label, {
          action: 'evaluate',
          params: {
            script: `() => { document.documentElement.style.colorScheme = ${JSON.stringify(params.color_scheme)}; return 'color-scheme ${String(params.color_scheme)}'; }`,
          },
        })
      }
      return `Resized in-app browser to ${Math.round(width)}x${Math.round(height)}`
    }
    if (action === 'reset_viewport') {
      viewportOverrideRef.current = null
      viewportScaleRef.current = 1
      boundsRef.current = null
      await applyAgentViewport(tab.id)
      return 'Reset in-app browser viewport to the panel size'
    }
    if (action === 'zoom') {
      const percent = Math.max(25, Math.min(500, Number(params.percent)))
      if (!Number.isFinite(percent)) throw new Error('zoom requires a percent')
      const webview = webviewsRef.current.get(tab.id)
      if (!webview) throw new Error('Desktop browser is unavailable')
      const scale = viewportOverrideRef.current ? viewportScaleRef.current : 1
      await webview.setZoom((percent / 100) * scale)
      return `Set in-app browser zoom to ${Math.round(percent)}%`
    }
    if (action === 'print') {
      await invokeFor('app_browser_webview_command', tab.label, { action: 'print' })
      return 'Opened the in-app browser print dialog'
    }
    if ([
      'snapshot',
      'query',
      'inspect',
      'html',
      'accessibility',
      'click',
      'click_at',
      'dblclick',
      'hover',
      'focus',
      'fill',
      'type',
      'clear',
      'submit',
      'press',
      'set_checked',
      'select',
      'drag',
      'scroll_into_view',
      'dispatch_event',
      'extract',
      'scroll',
      'screenshot',
      'console',
      'network',
      'dialogs',
      'dialog_behavior',
      'performance',
      'clear_logs',
      'storage',
      'cookies',
      'http',
      'debug_summary',
      'evaluate',
    ].includes(action)) {
      // A click can navigate without going through our navigate handler. Install
      // observability idempotently in the current document before every action.
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'instrument',
        params: {},
      })
      return invokeFor('app_browser_webview_agent_action', tab.label, {
        action,
        params,
      })
    }
    throw new Error(
      `${action} is not supported by the direct desktop browser yet`,
    )
  }, [applyAgentViewport, closeAll, closeTab, createTab, invokeFor, onRequestNewTab, selectTab, singleTab, waitForNavigation, waitForPageReady])

  agentHandlerRef.current = executeAgentCommand

  useEffect(() => {
    if (!supported || !enabled || !bridgeEnabled) return
    let alive = true
    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (!alive) return
      socket = new WebSocket(directBrowserBridgeUrl(sessionId))
      socket.onopen = () => {
        socket?.send(JSON.stringify({ type: 'ready', version: 1 }))
        setAgentConnected(true)
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
        void agentHandlerRef.current(action, params)
          .then((result) => {
            if (socket?.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ id, ok: true, result }))
            }
          })
          .catch((error) => {
            if (socket?.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({
                id,
                ok: false,
                error: error instanceof Error ? error.message : String(error),
              }))
            }
          })
      }
      socket.onclose = () => {
        setAgentConnected(false)
        socket = null
        if (alive) reconnectTimer = setTimeout(connect, 1000)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      alive = false
      setAgentConnected(false)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [bridgeEnabled, enabled, sessionId, supported])

  useEffect(() => {
    const webview = webviewsRef.current.get(activeTabId ?? '')
    const scale = viewportOverrideRef.current ? viewportScaleRef.current : 1
    const effectiveZoom = viewportOverrideRef.current ? scale : zoom / 100
    if (webview) void webview.setZoom(effectiveZoom).catch(() => {})
  }, [activeTabId, zoom])

  useEffect(() => {
    if (!supported || !activeTab || !visible) return
    let disposed = false
    let polling = false
    const pollDialogs = async () => {
      if (disposed || polling || pageDialog) return
      polling = true
      try {
        const dialogs = await invokeFor<BrowserPageDialog[]>(
          'app_browser_webview_agent_action',
          activeTab.label,
          { action: 'dialogs', params: {} },
        )
        const latest = Array.isArray(dialogs) ? dialogs.at(-1) : null
        if (!latest) return
        const key = `${activeTab.label}:${latest.id ?? latest.ts}:${latest.ts}`
        if (key === lastDialogKeyRef.current) return
        lastDialogKeyRef.current = key
        setPageDialog(latest)
      } catch {
        // Navigation briefly invalidates eval callbacks; the next poll retries.
      } finally {
        polling = false
      }
    }
    void pollDialogs()
    const timer = window.setInterval(() => void pollDialogs(), 500)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [activeTab, invokeFor, pageDialog, supported, visible])

  useEffect(() => {
    if (!supported) return
    let disposed = false
    let syncing = false
    let frame = 0

    const loop = async () => {
      if (disposed) return
      const viewport = viewportRef.current
      if (!syncing && viewport) {
        syncing = true
        try {
          const rect = viewport.getBoundingClientRect()
          const cssVisible = getComputedStyle(viewport).visibility !== 'hidden'
          const shouldShow = visible && cssVisible && rect.width >= 2 && rect.height >= 2
          const layout = browserViewportLayout({
            x: rect.left,
            y: rect.top,
            width: rect.width,
            height: rect.height,
          }, viewportOverrideRef.current)
          viewportScaleRef.current = layout.scale
          const bounds = {
            x: layout.x,
            y: layout.y,
            width: layout.width,
            height: layout.height,
          }
          const changed = !sameBounds(boundsRef.current, bounds)

          for (const [id, webview] of webviewsRef.current) {
            const isActive = id === activeIdRef.current
            const show = shouldShow && isActive && !pageDialog
            const currentlyVisible = visibilityRef.current.get(id) === true
            if (show && (changed || !currentlyVisible)) {
              const { LogicalPosition, LogicalSize } = await import('@tauri-apps/api/dpi')
              await Promise.all([
                webview.setPosition(new LogicalPosition(bounds.x, bounds.y)),
                webview.setSize(new LogicalSize(bounds.width, bounds.height)),
                webview.setZoom(viewportOverrideRef.current ? layout.scale : zoom / 100),
              ])
            }
            if (visibilityRef.current.get(id) !== show) {
              await (show ? webview.show() : webview.hide())
              visibilityRef.current.set(id, show)
            }
          }
          if (changed) boundsRef.current = bounds
        } catch {
          // The next animation frame retries bounds/visibility synchronization.
        } finally {
          syncing = false
        }
      }
      frame = requestAnimationFrame(() => void loop())
    }

    frame = requestAnimationFrame(() => void loop())
    return () => {
      disposed = true
      cancelAnimationFrame(frame)
    }
  }, [pageDialog, supported, viewportRef, visible, zoom])

  useEffect(() => {
    if (!supported || !activeTab) return
    const timer = window.setInterval(() => {
      void invokeFor<string>('app_browser_webview_url', activeTab.label)
        .then((url) => {
          setTabs((current) => current.map((tab) => tab.id === activeTab.id && tab.url !== url
            ? { ...tab, url }
            : tab))
        })
        .catch(() => {})
    }, 500)
    return () => window.clearInterval(timer)
  }, [activeTab, invokeFor, supported])

  useEffect(() => () => {
    for (const webview of webviewsRef.current.values()) {
      void webview.close().catch(() => {})
    }
    webviewsRef.current.clear()
  }, [])

  return {
    supported,
    tabs,
    activeTab,
    activeTabId,
    creating,
    agentConnected,
    pageDialog,
    dismissPageDialog: () => setPageDialog(null),
    createTab,
    selectTab,
    closeTab,
    navigate,
    command,
    find,
    clearBrowsingData,
    closeAll,
  }
}

export function browserViewportLayout(
  container: NativeBounds,
  override: BrowserViewportOverride | null,
): BrowserViewportLayout {
  const containerWidth = Math.max(1, container.width)
  const containerHeight = Math.max(1, container.height)
  if (!override) {
    return {
      x: Math.round(container.x),
      y: Math.round(container.y),
      width: Math.max(1, Math.round(containerWidth)),
      height: Math.max(1, Math.round(containerHeight)),
      scale: 1,
    }
  }
  const scale = Math.min(
    1,
    containerWidth / override.width,
    containerHeight / override.height,
  )
  const width = Math.max(1, Math.round(override.width * scale))
  const height = Math.max(1, Math.round(override.height * scale))
  return {
    x: Math.round(container.x + (containerWidth - width) / 2),
    y: Math.round(container.y + (containerHeight - height) / 2),
    width,
    height,
    scale,
  }
}

function directBrowserBridgeUrl(sessionId: string): string {
  return withTokenParam(
    `${apiWsBaseUrl()}/team/${encodeURIComponent(sessionId)}/browser/agent`,
  )
}

function sameBounds(left: NativeBounds | null, right: NativeBounds): boolean {
  return Boolean(
    left
    && left.x === right.x
    && left.y === right.y
    && left.width === right.width
    && left.height === right.height,
  )
}

function normalizeComparableUrl(value: string): string {
  return value.replace(/\/$/, '')
}

export function isBrowserNewTab(url: string): boolean {
  return url === NEW_TAB_URL
    || url.endsWith('/browser-new-tab.html')
    || url === 'about:blank'
}

export function browserWaitConditionSatisfied(
  probe: BrowserWaitProbe,
  expected: {
    selector: string
    state: string
    text: string
    urlContains: string
    loadState: string
  },
): boolean {
  const elementReady = !expected.selector || (
    expected.state === 'detached' ? !probe.attached
      : expected.state === 'hidden' ? !probe.attached || !probe.visible
        : expected.state === 'visible' ? Boolean(probe.visible)
          : Boolean(probe.attached)
  )
  const textReady = !expected.text || String(probe.text ?? '').includes(expected.text)
  const urlReady = !expected.urlContains || String(probe.url ?? '').includes(expected.urlContains)
  const loadReady = !expected.loadState || probe.readyState === expected.loadState
  return elementReady && textReady && urlReady && loadReady
}
