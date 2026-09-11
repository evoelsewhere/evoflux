import { useCallback, useEffect, useRef, useState } from 'react'
import type { Webview } from '@tauri-apps/api/webview'

import { getPlatform } from '@/hooks/use-platform'
import {
  nextBrowserSurfaceOrder,
  registerDirectBrowserSurface,
} from './directBrowserAgentRegistry'

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

export interface BrowserPopupRequest {
  id: number
  ts: number
  url: string
}

export interface BrowserPermissionRequest {
  id: number
  ts: number
  kind: 'notifications' | 'media' | 'geolocation' | string
  detail?: Record<string, unknown>
  state: 'pending'
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
  profileMode: 'shared' | 'session' | 'incognito'
  onError: (message: string) => void
  onRequestNewTab?: (url: string) => void
  onActivate?: () => void
  onCloseSurface?: () => void
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

export interface BrowserRuntimeStatus {
  url?: string
  title?: string
  readyState?: string
  documentId?: string | null
  viewport?: { width?: number; height?: number }
}

const NEW_TAB_URL = '/browser-new-tab.html'
/**
 * Ceiling on one attempt to open a page.
 *
 * Creating the WebView is bounded, but the IPC calls after it — zoom,
 * focus, waiting for the document — are not: a WebView that never answers
 * leaves the await pending forever, and the guard that stops two creations
 * racing is held for exactly as long. The panel then reports "still
 * opening" for the rest of the session and never retries.
 */
const CREATE_TIMEOUT_MS = 20_000
/**
 * Ceiling on the health check that runs before a page is opened.
 *
 * Everything this panel does goes through Tauri IPC, and an IPC call that
 * never answers is indistinguishable from a slow one — the panel simply
 * reported "still opening" forever. One cheap call first turns that into
 * a diagnosis.
 */
const IPC_PROBE_TIMEOUT_MS = 4_000
/**
 * Write one line into the desktop app's own log.
 *
 * A browser panel that cannot start used to leave nothing behind but a
 * toast, which is gone by the time anyone asks what happened — and the
 * WebView console is not somewhere a user can be walked to over chat.
 * The log plugin already writes to stdout and the app's log directory,
 * so a failure here is recoverable after the fact.
 */
const LOG_LEVELS = { info: 3, warn: 4, error: 5 } as const

const logToDesktop = async (
  level: keyof typeof LOG_LEVELS,
  message: string,
): Promise<void> => {
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('plugin:log|log', {
    level: LOG_LEVELS[level],
    message: `browser-panel: ${message}`,
  })
}

const withTimeout = async <T,>(
  work: Promise<T>,
  label: string,
  ms: number = CREATE_TIMEOUT_MS,
): Promise<T> => {
  let timer = 0
  try {
    return await Promise.race([
      work,
      new Promise<never>((_resolve, reject) => {
        timer = window.setTimeout(
          () => reject(new Error(`${label} did not respond within ${ms / 1000}s`)),
          ms,
        )
      }),
    ])
  } finally {
    window.clearTimeout(timer)
  }
}

/** Retries before the panel admits defeat and says so. */
const CREATE_MAX_ATTEMPTS = 6
const CREATE_RETRY_BASE_MS = 250
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
  profileMode,
  onError,
  onRequestNewTab,
  onActivate,
  onCloseSurface,
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
  const registryOrderRef = useRef(nextBrowserSurfaceOrder())
  const registryActiveRef = useRef(bridgeEnabled)
  const registryActivateRef = useRef(onActivate)
  const registryCloseRef = useRef(onCloseSurface)
  const counterRef = useRef(0)
  const boundsRef = useRef<NativeBounds | null>(null)
  const viewportOverrideRef = useRef<BrowserViewportOverride | null>(null)
  const viewportScaleRef = useRef(1)
  const lastDialogKeyRef = useRef('')
  const seenPopupKeysRef = useRef(new Set<string>())
  const visibilityRef = useRef(new Map<string, boolean>())
  const creatingRef = useRef(false)
  const visibleRef = useRef(visible)
  // Creating a WebView takes up to five seconds. If the panel unmounts
  // during that wait, cleanup has already emptied the map — and the
  // WebView that lands afterwards is a native window with no owner,
  // floating over the app until the process exits.
  const disposedRef = useRef(false)
  const [tabs, setTabs] = useState<DirectBrowserTab[]>([])
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  // Bumping this is what re-runs the auto-create effect. ``tabs.length``
  // cannot: a failed attempt leaves it at zero, which is why one failure
  // used to mean a permanently blank panel.
  const [createAttempt, setCreateAttempt] = useState(0)
  const retryCreateRef = useRef<() => void>(() => {})
  const lastCreateErrorRef = useRef<string | null>(null)
  const createStageRef = useRef<string>('')
  // Bumped whenever an attempt is abandoned, so a call that was hung on
  // the native shell and finally returns cannot register a second
  // WebView behind the retry that replaced it.
  const createTokenRef = useRef(0)
  const unavailableReasonRef = useRef<() => string>(() => '')
  retryCreateRef.current = () => setCreateAttempt((current) => current + 1)
  unavailableReasonRef.current = () => {
    if (!supported) return 'the in-app browser needs EvoFlux Desktop'
    if (!enabled) return 'the browser panel is turned off in its settings'
    if (creatingRef.current) {
      return createStageRef.current
        ? `still opening the page (waiting on ${createStageRef.current})`
        : 'the page is still opening'
    }
    if (lastCreateErrorRef.current) return lastCreateErrorRef.current
    return 'no page has been opened in it'
  }
  const [agentConnected, setAgentConnected] = useState(false)
  const [pageDialog, setPageDialog] = useState<BrowserPageDialog | null>(null)
  const [pagePermission, setPagePermission] = useState<BrowserPermissionRequest | null>(null)
  const [viewportOverride, setViewportOverride] = useState<BrowserViewportOverride | null>(null)

  activeIdRef.current = activeTabId
  visibleRef.current = visible
  registryActiveRef.current = bridgeEnabled
  registryActivateRef.current = onActivate
  registryCloseRef.current = onCloseSurface

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
    previousDocumentId: string | null,
  ): Promise<string> => {
    const requested = normalizeComparableUrl(requestedUrl)
    const previous = normalizeComparableUrl(previousUrl)
    let current = previousUrl
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        const status = await invokeFor<BrowserRuntimeStatus>(
          'app_browser_webview_agent_action',
          label,
          { action: 'status', params: {} },
        )
        current = status.url ?? current
        if (browserNavigationCommitted(
          status,
          requested,
          previous,
          previousDocumentId,
        )) {
          return current
        }
      } catch {
        // Wry drops evaluation callbacks while the target document is loading.
      }
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    throw new Error(`Browser navigation did not commit: ${requestedUrl}`)
  }, [invokeFor])

  const waitForDocumentNavigation = useCallback(async (
    label: string,
    previousDocumentId: string | null,
  ): Promise<BrowserRuntimeStatus> => {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        const status = await invokeFor<BrowserRuntimeStatus>(
          'app_browser_webview_agent_action',
          label,
          { action: 'status', params: {} },
        )
        const ready = status.readyState === 'interactive' || status.readyState === 'complete'
        if (ready && (!previousDocumentId || status.documentId !== previousDocumentId)) {
          return status
        }
      } catch {
        // The target document is between WebView evaluation contexts.
      }
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    throw new Error('Browser document did not commit after navigation')
  }, [invokeFor])

  const waitForPossibleDocumentNavigation = useCallback(async (
    label: string,
    previousDocumentId: string | null,
    timeoutMs = 900,
  ): Promise<BrowserRuntimeStatus | null> => {
    if (!previousDocumentId) return null
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      try {
        const status = await invokeFor<BrowserRuntimeStatus>(
          'app_browser_webview_agent_action',
          label,
          { action: 'status', params: {} },
        )
        if (status.documentId && status.documentId !== previousDocumentId) {
          if (status.readyState === 'interactive' || status.readyState === 'complete') {
            return status
          }
          return waitForDocumentNavigation(label, previousDocumentId)
        }
      } catch {
        // A navigation can temporarily tear down the old evaluation context.
      }
      await new Promise((resolve) => setTimeout(resolve, 75))
    }
    return null
  }, [invokeFor, waitForDocumentNavigation])

  const createTab = useCallback(async (initialUrl = NEW_TAB_URL) => {
    if (!supported || !enabled || creatingRef.current) return
    if (singleTab && tabsRef.current.length > 0) return tabsRef.current[0]
    const viewport = viewportRef.current
    // A WebView cannot be created without somewhere to put it. Returning
    // here used to be the end of the story: the auto-create effect only
    // re-runs when ``tabs.length`` changes, and it had just failed to
    // change it, so nothing ever tried again. The panel stayed blank with
    // no error, and the agent got "Desktop browser is unavailable" for the
    // rest of the session. Ask to be retried instead.
    const rect = viewport?.getBoundingClientRect()
    if (!rect || rect.width < 2 || rect.height < 2) {
      lastCreateErrorRef.current = viewport
        ? `the panel has no size yet (${Math.round(rect?.width ?? 0)}x${Math.round(rect?.height ?? 0)}) — the workbench may be collapsed or minimised`
        : 'the panel is not mounted yet'
      retryCreateRef.current?.()
      return
    }

    creatingRef.current = true
    setCreating(true)
    createStageRef.current = 'the Tauri API modules'
    const token = createTokenRef.current
    createStageRef.current = 'the desktop shell to answer'
    try {
      await withTimeout(
        logToDesktop('info', 'opening a page'),
        'the desktop shell',
        IPC_PROBE_TIMEOUT_MS,
      )
    } catch {
      lastCreateErrorRef.current =
        'the desktop shell is not answering (Tauri IPC timed out) — '
        + 'nothing in this panel can work until it does; restart EvoFlux Desktop'
      createStageRef.current = ''
      creatingRef.current = false
      setCreating(false)
      retryCreateRef.current?.()
      return
    }
    // `finally` cannot release the guard if an await never settles, and
    // every await below crosses into the native shell. Without this, one
    // unanswered IPC call left the panel reporting "still opening" for the
    // rest of the session, with nothing able to try again.
    const watchdog = window.setTimeout(() => {
      if (!creatingRef.current || createTokenRef.current !== token) return
      lastCreateErrorRef.current = `opening the page timed out (waiting on ${
        createStageRef.current || 'the desktop shell'})`
      void logToDesktop('warn', `${lastCreateErrorRef.current}; retrying`)
        .catch(() => {})
      createTokenRef.current += 1
      createStageRef.current = ''
      creatingRef.current = false
      setCreating(false)
      retryCreateRef.current?.()
    }, CREATE_TIMEOUT_MS)
    try {
      const [{ Webview }, { getCurrentWindow }] = await Promise.all([
        import('@tauri-apps/api/webview'),
        import('@tauri-apps/api/window'),
      ])
      createStageRef.current = 'hiding the previous page'
      const id = `${Date.now().toString(36)}-${counterRef.current++}`
      const safeSession = sessionId.replace(/[^a-zA-Z0-9_-]/g, '').slice(-18)
      const safeInstance = instanceId.replace(/[^a-zA-Z0-9_-]/g, '').slice(-18)
      const label = `browser-${safeSession}-${safeInstance}-${id}`
      const current = webviewsRef.current.get(activeIdRef.current ?? '')
      await current?.hide().catch(() => {})

      createStageRef.current = 'the WebView to be created'
      let webview = new Webview(getCurrentWindow(), label, {
        url: initialUrl,
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.max(1, Math.round(rect.width)),
        height: Math.max(1, Math.round(rect.height)),
        focus: visibleRef.current,
        incognito: profileMode === 'incognito',
        dataDirectory: profileMode === 'session'
          ? `${BROWSER_DATA_DIRECTORY}/${safeSession || 'default'}`
          : BROWSER_DATA_DIRECTORY,
        dataStoreIdentifier: profileMode === 'session'
          ? browserDataStoreIdentifier(sessionId)
          : BROWSER_DATA_STORE_ID,
        devtools,
        zoomHotkeysEnabled: true,
      })
      await new Promise<void>((resolve, reject) => {
        let settled = false
        const timeout = window.setTimeout(() => {
          void Webview.getByLabel(label).then(
            (existing) => {
              if (settled) return
              if (existing) {
                webview = existing
                finish(resolve)
              } else {
                finish(() => reject(new Error('Timed out creating browser WebView')))
              }
            },
            () => finish(() => reject(new Error('Timed out creating browser WebView'))),
          )
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

      if (disposedRef.current || createTokenRef.current !== token) {
        await webview.close().catch(() => {})
        return
      }
      createStageRef.current = 'the WebView to be positioned'
      webviewsRef.current.set(id, webview)
      if (!visibleRef.current) await webview.hide().catch(() => {})
      visibilityRef.current.set(id, visibleRef.current)
      boundsRef.current = null
      lastCreateErrorRef.current = null
      const tab = { id, label, url: initialUrl }
      tabsRef.current = [...tabsRef.current, tab]
      setTabs(tabsRef.current)
      activeIdRef.current = id
      setActiveTabId(id)
      createStageRef.current = 'the page zoom'
      await withTimeout(webview.setZoom(zoom / 100), 'setting the page zoom')
      if (visibleRef.current) await webview.setFocus().catch(() => {})
      createStageRef.current = 'the page to become ready'
      await withTimeout(waitForPageReady(label), 'the new page')
      return tab
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      lastCreateErrorRef.current = `creating the WebView failed (${message})`
      void logToDesktop(
        'error',
        `create failed at stage "${createStageRef.current}": ${message}`,
      ).catch(() => {})
      onError(message)
      // Creation can fail for reasons that pass: the WebView runtime is
      // still starting, the window is mid-resize. One shot and a dead
      // panel is the wrong answer to a transient failure.
      retryCreateRef.current?.()
    } finally {
      window.clearTimeout(watchdog)
      if (createTokenRef.current === token) {
        createStageRef.current = ''
        creatingRef.current = false
        setCreating(false)
      }
    }
  }, [devtools, enabled, instanceId, onError, profileMode, sessionId, singleTab, supported, viewportRef, waitForPageReady, zoom])

  useEffect(() => {
    if (!supported || !enabled || tabs.length > 0 || creating) return
    if (createAttempt > 0 && createAttempt > CREATE_MAX_ATTEMPTS) return
    let timer = 0
    // The first attempt is immediate; retries back off, because the two
    // things worth waiting for — a laid-out viewport and a ready WebView
    // runtime — both resolve in well under a second.
    const delay = createAttempt === 0
      ? 0
      : Math.min(CREATE_RETRY_BASE_MS * 2 ** (createAttempt - 1), 4_000)
    timer = window.setTimeout(() => void createTab(initialUrl), delay)
    return () => window.clearTimeout(timer)
  }, [createAttempt, createTab, creating, enabled, initialUrl, supported, tabs.length])

  useEffect(() => {
    if (createAttempt <= CREATE_MAX_ATTEMPTS || tabsRef.current.length > 0) return
    onError(
      `The browser panel could not start: ${
        lastCreateErrorRef.current ?? 'the desktop shell did not respond'
      }. Close and reopen this tab, or restart EvoFlux Desktop if it keeps failing.`,
    )
  }, [createAttempt, onError])

  // Switching tabs only records which tab is active; the viewport sync
  // does the showing. Doing it here meant marking the incoming WebView
  // visible *before* it had been positioned — and the sync skips
  // positioning a view it already believes is visible at unchanged
  // bounds, so the tab appeared wherever that WebView happened to sit
  // last. Hiding the outgoing one directly is safe and avoids a frame of
  // two visible tabs stacked on each other.
  const selectTab = useCallback(async (id: string) => {
    if (id === activeIdRef.current) return
    const previousId = activeIdRef.current ?? ''
    const previous = webviewsRef.current.get(previousId)
    await previous?.hide().catch(() => {})
    visibilityRef.current.set(previousId, false)
    activeIdRef.current = id
    setActiveTabId(id)
    await webviewsRef.current.get(id)?.setFocus().catch(() => {})
  }, [])

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
        // Same as selectTab: let the viewport sync position it before it
        // is shown, rather than showing it at stale bounds.
        await webviewsRef.current.get(replacement.id)?.setFocus().catch(() => {})
      } else if (enabled && !singleTab) {
        queueMicrotask(() => void createTab())
      }
    }
  }, [createTab, enabled, singleTab, tabs])

  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? null

  const navigate = useCallback(async (url: string) => {
    if (!activeTab) return
    try {
      const before = await invokeFor<BrowserRuntimeStatus>(
        'app_browser_webview_agent_action',
        activeTab.label,
        { action: 'status', params: {} },
      )
      await invokeFor('app_browser_webview_navigate', activeTab.label, { url })
      const committedUrl = await waitForNavigation(
        activeTab.label,
        url,
        activeTab.url,
        before.documentId ?? null,
      )
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
      const status = await invokeFor<BrowserRuntimeStatus>(
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
      const before = await invokeFor<BrowserRuntimeStatus>(
        'app_browser_webview_agent_action',
        tab.label,
        { action: 'status', params: {} },
      )
      await invokeFor('app_browser_webview_navigate', tab.label, { url })
      const committedUrl = await waitForNavigation(
        tab.label,
        url,
        tab.url,
        before.documentId ?? null,
      )
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
      const before = await invokeFor<BrowserRuntimeStatus>(
        'app_browser_webview_agent_action',
        tab.label,
        { action: 'status', params: {} },
      )
      await invokeFor('app_browser_webview_command', tab.label, { action })
      const committed = await waitForDocumentNavigation(
        tab.label,
        before.documentId ?? null,
      )
      if (committed.url) {
        tabsRef.current = tabsRef.current.map((item) => item.id === tab.id
          ? { ...item, url: committed.url ?? item.url }
          : item)
        setTabs(tabsRef.current)
      }
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
      let width = preset?.[0] ?? Number(params.width)
      let height = preset?.[1] ?? Number(params.height)
      if (!Number.isFinite(width) || !Number.isFinite(height)) {
        throw new Error('resize requires a preset or width and height')
      }
      const orientation = params.orientation === 'landscape' ? 'landscape' : 'portrait'
      if (orientation === 'landscape' && height > width) [width, height] = [height, width]
      if (orientation === 'portrait' && width > height) [width, height] = [height, width]
      const presetMobile = params.preset === 'mobile' || params.preset === 'tablet'
      const mobile = typeof params.mobile === 'boolean' ? params.mobile : presetMobile
      const touch = typeof params.touch === 'boolean' ? params.touch : presetMobile
      viewportOverrideRef.current = {
        width: Math.max(200, Math.min(4000, width)),
        height: Math.max(200, Math.min(4000, height)),
      }
      setViewportOverride(viewportOverrideRef.current)
      // Apply synchronously for the command response; the animation-frame
      // synchronizer keeps the same override stable as app chrome moves.
      boundsRef.current = null
      await applyAgentViewport(tab.id)
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'set_emulation',
        params: {
          width,
          height,
          device_scale_factor: Number(params.device_scale_factor) || 1,
          mobile,
          touch,
          orientation,
          color_scheme: params.color_scheme,
          user_agent: params.user_agent,
        },
      })
      return `Resized in-app browser to ${Math.round(width)}x${Math.round(height)}`
    }
    if (action === 'reset_viewport') {
      viewportOverrideRef.current = null
      setViewportOverride(null)
      viewportScaleRef.current = 1
      boundsRef.current = null
      await applyAgentViewport(tab.id)
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'reset_emulation',
        params: {},
      })
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
    if (action === 'clipboard_read') {
      const { readText } = await import('@tauri-apps/plugin-clipboard-manager')
      return readText()
    }
    if (action === 'clipboard_write') {
      const { writeText } = await import('@tauri-apps/plugin-clipboard-manager')
      const text = typeof params.text === 'string' ? params.text : ''
      await writeText(text)
      return `Wrote ${text.length} characters to the clipboard`
    }
    if (action === 'click_at') {
      const coordinateSpace = params.coordinate_space === 'css' ? 'css' : 'screenshot'
      const mappedParams = { ...params }
      delete mappedParams.coordinate_space
      if (coordinateSpace === 'screenshot') {
        const status = await invokeFor<{ viewport?: { width?: number; height?: number } }>(
          'app_browser_webview_agent_action',
          tab.label,
          { action: 'status', params: {} },
        )
        const bounds = boundsRef.current
        const cssWidth = Number(status.viewport?.width)
        const cssHeight = Number(status.viewport?.height)
        if (bounds && cssWidth > 0 && cssHeight > 0) {
          const point = browserScreenshotPoint(
            { x: Number(params.x), y: Number(params.y) },
            bounds,
            { width: cssWidth, height: cssHeight },
          )
          mappedParams.x = point.x
          mappedParams.y = point.y
        }
      }
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'instrument',
        params: {},
      })
      return invokeFor('app_browser_webview_agent_action', tab.label, {
        action,
        params: mappedParams,
      })
    }
    if ([
      'snapshot',
      'find',
      'query',
      'inspect',
      'html',
      'accessibility',
      'click',
      'dblclick',
      'hover',
      'focus',
      'fill',
      'set_files',
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
      'page_assets',
      'download',
      'save_pdf',
      'console',
      'network',
      'dialogs',
      'popups',
      'permission_requests',
      'resolve_permission',
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
      const navigationAware = action === 'click'
        || action === 'dblclick'
        || action === 'submit'
        || (action === 'press' && String(params.key || '').split('+').at(-1) === 'Enter')
      const before = navigationAware
        ? await invokeFor<BrowserRuntimeStatus>(
            'app_browser_webview_agent_action',
            tab.label,
            { action: 'status', params: {} },
          )
        : null
      await invokeFor('app_browser_webview_agent_action', tab.label, {
        action: 'instrument',
        params: {},
      })
      const result = await invokeFor('app_browser_webview_agent_action', tab.label, {
        action,
        params,
      })
      if (before) {
        const committed = await waitForPossibleDocumentNavigation(
          tab.label,
          before.documentId ?? null,
        )
        if (committed?.url) {
          tabsRef.current = tabsRef.current.map((item) => item.id === tab.id
            ? { ...item, url: committed.url ?? item.url }
            : item)
          setTabs(tabsRef.current)
          await invokeFor('app_browser_webview_agent_action', tab.label, {
            action: 'instrument',
            params: {},
          })
        }
      }
      return result
    }
    throw new Error(
      `${action} is not supported by the direct desktop browser yet`,
    )
  }, [applyAgentViewport, closeAll, closeTab, createTab, invokeFor, onRequestNewTab, selectTab, singleTab, waitForDocumentNavigation, waitForNavigation, waitForPossibleDocumentNavigation])

  agentHandlerRef.current = executeAgentCommand

  useEffect(() => {
    if (!supported || !enabled) return
    return registerDirectBrowserSurface(
      sessionId,
      {
        instanceId,
        order: registryOrderRef.current,
        isActive: () => registryActiveRef.current,
        getTab: () => tabsRef.current.find((tab) => tab.id === activeIdRef.current) ?? null,
        unavailableReason: () => unavailableReasonRef.current(),
        execute: (action, params) => agentHandlerRef.current(action, params),
        activate: () => registryActivateRef.current?.(),
        close: () => registryCloseRef.current?.(),
      },
      setAgentConnected,
    )
  }, [enabled, instanceId, sessionId, supported])

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
      if (disposed || polling || pageDialog || pagePermission) return
      polling = true
      try {
        const [dialogs, popups, permissions] = await Promise.all([
          invokeFor<BrowserPageDialog[]>(
            'app_browser_webview_agent_action',
            activeTab.label,
            { action: 'dialogs', params: {} },
          ),
          invokeFor<BrowserPopupRequest[]>(
            'app_browser_webview_agent_action',
            activeTab.label,
            { action: 'popups', params: { clear: true } },
          ),
          invokeFor<BrowserPermissionRequest[]>(
            'app_browser_webview_agent_action',
            activeTab.label,
            { action: 'permission_requests', params: {} },
          ),
        ])
        for (const popup of Array.isArray(popups) ? popups : []) {
          const popupKey = `${activeTab.label}:${popup.id}:${popup.ts}`
          if (seenPopupKeysRef.current.has(popupKey)) continue
          seenPopupKeysRef.current.add(popupKey)
          onRequestNewTab?.(popup.url)
        }
        if (seenPopupKeysRef.current.size > 200) {
          seenPopupKeysRef.current = new Set([...seenPopupKeysRef.current].slice(-100))
        }
        const latest = Array.isArray(dialogs) ? dialogs.at(-1) : null
        if (latest) {
          const key = `${activeTab.label}:${latest.id ?? latest.ts}:${latest.ts}`
          if (key !== lastDialogKeyRef.current) {
            lastDialogKeyRef.current = key
            setPageDialog(latest)
          }
        }
        const permission = Array.isArray(permissions) ? permissions[0] : null
        if (permission) setPagePermission(permission)
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
  }, [activeTab, invokeFor, onRequestNewTab, pageDialog, pagePermission, supported, visible])

  const resolvePagePermission = useCallback(async (allow: boolean) => {
    const tab = tabsRef.current.find((item) => item.id === activeIdRef.current)
    const permission = pagePermission
    if (!tab || !permission) return
    await invokeFor('app_browser_webview_agent_action', tab.label, {
      action: 'resolve_permission',
      params: { id: permission.id, allow },
    })
    setPagePermission(null)
  }, [invokeFor, pagePermission])

  /**
   * Keep the native child WebView on top of its placeholder element.
   *
   * The WebView is an OS-level window, not a DOM node, so nothing lays it
   * out for us: its position, size and visibility have to be pushed over
   * IPC whenever the element it shadows moves.
   *
   * This used to run as an unconditional 60fps ``requestAnimationFrame``
   * loop, forcing a layout read every frame for the whole life of the
   * panel — while the browser was closed, while another workbench tab was
   * in front, one loop per open browser tab. It now syncs when something
   * actually moves: a resize of the placeholder, a scroll or resize of the
   * window, or a React state change that alters what should be shown.
   */
  useEffect(() => {
    if (!supported) return
    const viewport = viewportRef.current
    if (!viewport) return

    let disposed = false
    let syncing = false
    let pendingSync = false
    let frame = 0

    const sync = async () => {
      if (disposed) return
      if (syncing) {
        // Coalesce: one more pass after the in-flight one, never a queue.
        pendingSync = true
        return
      }
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
          const show = shouldShow && isActive && !pageDialog && !pagePermission
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
      } catch (error) {
        // A native WebView left in the wrong place is the most visible way
        // this panel breaks, and the old loop swallowed every failure on
        // the theory that the next frame would fix it. Say so, then retry
        // once on the next frame rather than spinning.
        if (!disposed) {
          console.warn('[browser] viewport sync failed', error)
          pendingSync = true
        }
      } finally {
        syncing = false
        if (pendingSync && !disposed) {
          pendingSync = false
          frame = requestAnimationFrame(() => void sync())
        }
      }
    }

    const schedule = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => void sync())
    }

    schedule()
    const observer = new ResizeObserver(schedule)
    observer.observe(viewport)
    // The placeholder can move without resizing — the window scrolls, a
    // sibling panel collapses — and only its own box is observed, so watch
    // the frame it lives in too.
    window.addEventListener('resize', schedule)
    window.addEventListener('scroll', schedule, true)
    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer.disconnect()
      window.removeEventListener('resize', schedule)
      window.removeEventListener('scroll', schedule, true)
    }
    // Every input the sync reads through a ref has to appear here, or the
    // WebView keeps the position it had when the effect last ran: `tabs`
    // for a newly created view, `activeTabId` for a switch between them,
    // `viewportOverride` for a device-size emulation.
  }, [
    activeTabId,
    pageDialog,
    pagePermission,
    supported,
    tabs,
    viewportOverride,
    viewportRef,
    visible,
    zoom,
  ])

  // Poll the address bar only for a panel someone is looking at. This ran
  // for every open browser tab regardless, so three background tabs cost
  // six IPC round trips a second to keep URLs nobody could see up to date.
  useEffect(() => {
    if (!supported || !activeTab || !visible) return
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
  }, [activeTab, invokeFor, supported, visible])

  useEffect(() => {
    // React invokes an effect, tears it down, and invokes it again on mount
    // in development. Without this reset the teardown latched `disposed`
    // on for the instance's whole life, so every WebView it created was
    // closed on the next line and the panel retried forever — which is
    // exactly what "the browser can't start" looked like.
    disposedRef.current = false
    // The refs hold Maps whose identity never changes, only their
    // contents, so aliasing them here is the same object cleanup would
    // read later — and it keeps the exhaustive-deps rule from mistaking
    // them for DOM nodes captured too early.
    const webviews = webviewsRef.current
    const visibilities = visibilityRef.current
    return () => {
      disposedRef.current = true
      for (const webview of webviews.values()) {
        void webview.close().catch(() => {})
      }
      webviews.clear()
      visibilities.clear()
    }
  }, [])

  return {
    supported,
    tabs,
    activeTab,
    activeTabId,
    creating,
    agentConnected,
    pageDialog,
    pagePermission,
    resolvePagePermission,
    viewportOverride,
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

export function browserScreenshotPoint(
  point: { x: number; y: number },
  imageBounds: Pick<NativeBounds, 'width' | 'height'>,
  cssViewport: { width: number; height: number },
): { x: number; y: number } {
  return {
    x: point.x * cssViewport.width / Math.max(1, imageBounds.width),
    y: point.y * cssViewport.height / Math.max(1, imageBounds.height),
  }
}

export function browserDataStoreIdentifier(sessionId: string): number[] {
  const bytes = new Uint8Array(16)
  const input = new TextEncoder().encode(`evoflux-browser:${sessionId}`)
  for (let index = 0; index < input.length; index += 1) {
    const slot = index % bytes.length
    bytes[slot] = (bytes[slot] * 31 + input[index] + index) & 0xff
  }
  // UUID-compatible variant/version bits keep WKWebsiteDataStore identifiers valid.
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  return [...bytes]
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

export function browserNavigationCommitted(
  status: BrowserRuntimeStatus,
  requestedUrl: string,
  previousUrl: string,
  previousDocumentId: string | null,
): boolean {
  const ready = status.readyState === 'interactive' || status.readyState === 'complete'
  if (!ready) return false
  if (previousDocumentId && status.documentId === previousDocumentId) return false
  const current = normalizeComparableUrl(status.url ?? '')
  return current === requestedUrl
    || (current !== previousUrl && !isBrowserNewTab(status.url ?? ''))
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
