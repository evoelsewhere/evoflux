import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  CircleAlert,
  Download,
  ExternalLink,
  Globe2,
  Loader2,
  LockKeyhole,
  Maximize2,
  Menu,
  Minimize2,
  Monitor,
  Plus,
  Printer,
  RefreshCw,
  Ruler,
  Search,
  Settings2,
  ShieldAlert,
  Trash2,
  Wrench,
  X,
  ZoomIn,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useMotionPreset } from '@/lib/motion'
import { openExternalUrl } from '@/lib/open-external'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import {
  browserConnectionInfo,
  browserZoomOrigin,
  FIT_DESKTOP_WIDTH,
  loadBrowserPreferences,
  loadBrowserZoomForOrigin,
  loadRecentBrowserSites,
  recordRecentBrowserSite,
  saveBrowserPreferences,
  saveBrowserZoomForOrigin,
  subscribeBrowserPreferences,
  type BrowserPreferences,
} from './browserPreferences'
import { BrowserLauncher } from './BrowserLauncher'
import { BrowserStartPage } from './BrowserStartPage'
import { DirectBrowserSettingsView } from './DirectBrowserSettingsView'
import {
  BROWSER_VIEWPORT_PRESETS,
  type BrowserDownload,
  type BrowserPageDialog,
  type BrowserPageError,
  type BrowserPermissionRequest,
  type BrowserSitePermission,
  type BrowserViewportOverride,
  type BrowserViewportPreset,
  isBrowserNewTab,
  useDirectBrowserTabs,
} from './useDirectBrowserTabs'

const ZOOM_LEVELS = [50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200]

/** Browser chrome actions reachable by keyboard, named by the shell too. */
type BrowserShortcut =
  | 'address-bar'
  | 'find'
  | 'new-tab'
  | 'close-tab'
  | 'reload'
  | 'back'
  | 'forward'
  | 'toggle-maximized'

/**
 * The browser fills a workbench surface, which owns its width. The shell used
 * to carry a second, self-resizing mode for a standalone right-hand drawer —
 * its own drag handle, width state and mobile overlay — that nothing has
 * mounted since the workbench took over, so it only made this file look like
 * two components.
 */
interface DirectBrowserShellProps {
  sessionId: string | null
  /** Coding workspace whose launch.json backs the new-tab launcher. */
  workspace?: string | null
  tabId?: string
  initialUrl?: string
  open: boolean
  visible?: boolean
  onClose: () => void
  onNewTab?: (url?: string) => void
  onTitleChange?: (title: string) => void
  className?: string
}

export function DirectBrowserShell({
  sessionId,
  workspace = null,
  tabId = 'browser',
  initialUrl,
  open,
  visible = true,
  onClose,
  onNewTab,
  onTitleChange,
  className,
}: DirectBrowserShellProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const urlInputRef = useRef<HTMLInputElement>(null)
  const onTitleChangeRef = useRef(onTitleChange)
  const urlFocusedRef = useRef(false)
  const [enabled, setEnabled] = useState(() => loadBrowserPreferences().enabled)
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [downloadsOpen, setDownloadsOpen] = useState(false)
  const [siteInfoOpen, setSiteInfoOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [preferences, setPreferences] = useState<BrowserPreferences>(loadBrowserPreferences)
  const [zoom, setZoom] = useState(() => loadBrowserPreferences().defaultZoom)
  const [recentSites, setRecentSites] = useState(loadRecentBrowserSites)
  // Starts true: the first tab opens on the new-tab page anyway, and
  // assuming that keeps the native view hidden from the first frame instead
  // of flashing the static page before the launcher takes over.
  const [onNewTabPage, setOnNewTabPage] = useState(true)
  const preset = useMotionPreset()
  const pushToast = useToastStore((state) => state.push)
  const maximized = useUIStore((state) => state.workbenchMaximized)
  const toggleMaximized = useUIStore((state) => state.toggleWorkbenchMaximized)

  useEffect(() => subscribeBrowserPreferences((next) => {
    setPreferences(next)
    setEnabled(next.enabled)
  }), [])

  const reportError = useCallback((message: string) => {
    pushToast({
      tone: 'error',
      title: 'Browser action failed',
      description: message,
    })
  }, [pushToast])

  // The launcher is React content in the viewport the native WebView covers,
  // so it can only be seen while that view is hidden — the same trick the
  // settings view uses. Without a workspace there is nothing to launch, so
  // the same slot holds a start page instead of an empty view.
  const atNewTabPage = onNewTabPage && enabled && !settingsOpen
  const showLauncher = Boolean(workspace) && atNewTabPage
  const showStartPage = !workspace && atNewTabPage
  // Set from the hook's own error state below; declared here because the
  // native view has to be hidden for our error card to be visible at all.
  const [pageErrorVisible, setPageErrorVisible] = useState(false)

  const browser = useDirectBrowserTabs({
    sessionId: sessionId ?? 'detached',
    instanceId: tabId,
    viewportRef,
    enabled: Boolean(open && sessionId && enabled),
    visible: Boolean(
      open && visible && !settingsOpen && !showLauncher && !showStartPage && !pageErrorVisible,
    ),
    bridgeEnabled: visible,
    initialUrl,
    singleTab: true,
    zoom,
    fitWidth: preferences.fitDesktopWidth ? FIT_DESKTOP_WIDTH : null,
    devtools: preferences.developerTools,
    profileMode: preferences.profileMode,
    onError: reportError,
    onRequestNewTab: (url) => onNewTab?.(url),
    onActivate: async () => {
      useUIStore.getState().selectWorkbenchTab(tabId)
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
      })
    },
    onCloseSurface: onClose,
  })

  const currentUrl = browser.activeTab?.url ?? ''
  const hasPage = Boolean(browser.activeTab)

  // Adjusted during render rather than in an effect: the launcher and the
  // native view's visibility must flip in the same commit, or one frame
  // shows both (or neither).
  const nextOnNewTabPage = !browser.activeTab || isBrowserNewTab(currentUrl)
  if (nextOnNewTabPage !== onNewTabPage) setOnNewTabPage(nextOnNewTabPage)

  const nextPageErrorVisible = Boolean(browser.pageError)
  if (nextPageErrorVisible !== pageErrorVisible) setPageErrorVisible(nextPageErrorVisible)

  const activeDownloads = browser.downloads.filter(
    (download) => download.state === 'started' || download.state === 'in_progress',
  ).length

  const connection = browserConnectionInfo(currentUrl)

  const openInPage = useCallback((url: string) => {
    // No WebView to navigate (creation failed, say) — hand the URL to a fresh
    // workbench tab rather than dropping the click.
    if (browser.activeTab) void browser.navigate(url)
    else onNewTab?.(url)
  }, [browser, onNewTab])

  useEffect(() => {
    onTitleChangeRef.current = onTitleChange
  }, [onTitleChange])

  useEffect(() => {
    const input = urlInputRef.current
    if (input && !urlFocusedRef.current) {
      input.value = isBrowserNewTab(currentUrl) ? '' : currentUrl
    }
  }, [currentUrl])

  useEffect(() => {
    onTitleChangeRef.current?.(tabTitle(currentUrl))
  }, [currentUrl])

  // Follow the site: its remembered zoom, or the default for one we have
  // never been asked to change.
  useEffect(() => {
    const origin = browserZoomOrigin(currentUrl)
    setZoom(loadBrowserZoomForOrigin(origin) ?? preferences.defaultZoom)
  }, [currentUrl, preferences.defaultZoom])

  useEffect(() => {
    const next = recordRecentBrowserSite(currentUrl)
    if (next) setRecentSites(next)
  }, [currentUrl])

  /**
   * One implementation for both ways a shortcut can arrive: from this
   * document, when the app's own UI has focus, and from the shell, when the
   * page has it and the native view handed the key back.
   */
  const runShortcut = useCallback(async (shortcut: BrowserShortcut) => {
    switch (shortcut) {
      case 'address-bar': {
        // Focus lives in the child WebView, which is an OS window of its own:
        // the app has to take it back before any DOM focus call means anything.
        const { getCurrentWindow } = await import('@tauri-apps/api/window')
        await getCurrentWindow().setFocus().catch(() => {})
        urlInputRef.current?.focus()
        urlInputRef.current?.select()
        break
      }
      case 'find':
        if (hasPage) setFindOpen(true)
        break
      case 'new-tab':
        onNewTab?.()
        break
      case 'close-tab':
        onClose()
        break
      case 'reload':
      case 'back':
      case 'forward':
        if (hasPage) void browser.command(shortcut)
        break
      case 'toggle-maximized':
        toggleMaximized()
        break
    }
  }, [browser, hasPage, onClose, onNewTab, toggleMaximized])

  // Shortcuts the shell intercepted before the page could swallow them.
  useEffect(() => {
    if (!open || !visible || !browser.supported) return
    const label = browser.activeTab?.label
    if (!label) return
    let disposed = false
    let unlisten: (() => void) | undefined
    void (async () => {
      const { listen } = await import('@tauri-apps/api/event')
      const stop = await listen<{ label: string; shortcut: BrowserShortcut }>(
        'browser-shortcut',
        (event) => {
          if (event.payload.label !== label) return
          void runShortcut(event.payload.shortcut)
        },
      )
      if (disposed) stop()
      else unlisten = stop
    })()
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [browser.activeTab?.label, browser.supported, open, runShortcut, visible])

  useEffect(() => {
    if (!open || !visible) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        void runShortcut('find')
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'l') {
        event.preventDefault()
        void runShortcut('address-bar')
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 't') {
        event.preventDefault()
        void runShortcut('new-tab')
      } else if (
        (event.metaKey || event.ctrlKey)
        && event.shiftKey
        && event.key.toLowerCase() === 'enter'
      ) {
        event.preventDefault()
        void runShortcut('toggle-maximized')
      } else if (event.key === 'Escape') {
        if (findOpen) setFindOpen(false)
        else if (menuOpen) setMenuOpen(false)
        else if (settingsOpen) setSettingsOpen(false)
        // Leaving full width is what Escape means in every other full-screen
        // surface; closing the tab from here would be a surprising way to lose
        // a page you were reading.
        else if (maximized) toggleMaximized()
        else onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [
    findOpen,
    maximized,
    menuOpen,
    onClose,
    open,
    runShortcut,
    settingsOpen,
    toggleMaximized,
    visible,
  ])

  const updatePreferences = useCallback((next: BrowserPreferences) => {
    setPreferences(next)
    saveBrowserPreferences(next)
  }, [])

  const handleNavigate = useCallback((event?: React.FormEvent) => {
    event?.preventDefault()
    const input = urlInputRef.current
    const value = input?.value.trim() ?? ''
    if (!value || !hasPage) return
    const target = normalizeBrowserTarget(value)
    if (input) input.value = target
    urlFocusedRef.current = false
    void browser.navigate(target)
  }, [browser, hasPage])

  /** Settings edits the starting point for sites we have no record of. */
  const handleDefaultZoomChange = useCallback((value: number) => {
    updatePreferences({
      ...preferences,
      defaultZoom: Math.max(50, Math.min(200, value)),
    })
  }, [preferences, updatePreferences])

  // Zoom applies to the site in front of you and is remembered for it. The
  // preference stays what a site with no opinion of its own starts at.
  const handleZoomChange = useCallback((value: number) => {
    const next = Math.max(50, Math.min(200, value))
    setZoom(next)
    const origin = browserZoomOrigin(currentUrl)
    if (origin) {
      saveBrowserZoomForOrigin(origin, next === preferences.defaultZoom ? null : next)
    }
  }, [currentUrl, preferences.defaultZoom])

  const handleClearData = useCallback(async () => {
    try {
      await browser.clearBrowsingData()
      pushToast({ tone: 'success', title: 'Browsing data cleared' })
    } catch (error) {
      reportError(error instanceof Error ? error.message : String(error))
    }
  }, [browser, pushToast, reportError])

  if (!open || !sessionId) return null

  return (
    <AnimatePresence>
      <>
        <motion.section
          aria-label="Built-in browser"
          className={cn(
            'relative flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden',
            'border-l border-(--color-border-strong) bg-(--bg-page)',
            className,
          )}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={preset.transition}
        >
          <div className="relative flex h-11 shrink-0 items-center gap-1.5 border-b border-(--color-border) bg-(--bg-page) px-2">
            {browser.loading && (
              // On the toolbar's own edge, not the viewport's: the native view
              // is an OS window stacked above this document, so anything drawn
              // over the page area is drawn underneath it.
              <div
                role="progressbar"
                aria-label="Loading page"
                className="pointer-events-none absolute inset-x-0 -bottom-px z-(--z-panel) h-0.5 overflow-hidden bg-(--color-accent)/15"
              >
                {/* Indeterminate: a native WebView reports that it is busy,
                    never how far along it is. */}
                <div className="h-full w-1/3 animate-[browser-progress_1.1s_ease-in-out_infinite] rounded-full bg-(--color-accent)" />
              </div>
            )}
            <ToolbarButton label="Back" disabled={!hasPage} onClick={() => void browser.command('back')}>
              <ArrowLeft />
            </ToolbarButton>
            <ToolbarButton label="Forward" disabled={!hasPage} onClick={() => void browser.command('forward')}>
              <ArrowRight />
            </ToolbarButton>
            <ToolbarButton label="Reload" disabled={!hasPage} onClick={() => void browser.command('reload')}>
              <RefreshCw />
            </ToolbarButton>

            {findOpen ? (
              <form
                className="flex min-w-0 flex-1 items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-key) px-1"
                onSubmit={(event) => {
                  event.preventDefault()
                  void browser.find(findQuery)
                }}
              >
                <Search size={13} className="ml-2 shrink-0 text-(--color-text-subtle)" aria-hidden />
                <input
                  autoFocus
                  value={findQuery}
                  onChange={(event) => setFindQuery(event.target.value)}
                  placeholder="Find in page"
                  className="h-7 min-w-0 flex-1 bg-transparent px-1 text-xs text-(--color-text) outline-none"
                  aria-label="Find in page"
                />
                <ToolbarButton label="Previous match" onClick={() => void browser.find(findQuery, true)}>
                  <ArrowUp />
                </ToolbarButton>
                <ToolbarButton label="Next match" onClick={() => void browser.find(findQuery)}>
                  <ArrowDown />
                </ToolbarButton>
                <ToolbarButton label="Close find" onClick={() => setFindOpen(false)}>
                  <X />
                </ToolbarButton>
              </form>
            ) : (
              <form onSubmit={handleNavigate} className="relative min-w-0 flex-1">
                <button
                  type="button"
                  disabled={!hasPage}
                  onClick={() => {
                    setMenuOpen(false)
                    setDownloadsOpen(false)
                    setSiteInfoOpen((current) => !current)
                  }}
                  aria-label="Site information"
                  title={connection.summary}
                  className="absolute left-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-full text-(--color-text-subtle) transition-colors hover:bg-(--bg-page) hover:text-(--color-text) disabled:pointer-events-none"
                >
                  {connection.encrypted ? <LockKeyhole size={12} /> : <Globe2 size={13} />}
                </button>
                <input
                  ref={urlInputRef}
                  data-browser-omnibox
                  defaultValue=""
                  onFocus={(event) => {
                    urlFocusedRef.current = true
                    event.currentTarget.select()
                  }}
                  onBlur={() => {
                    urlFocusedRef.current = false
                    if (urlInputRef.current) {
                      urlInputRef.current.value = isBrowserNewTab(currentUrl) ? '' : currentUrl
                    }
                  }}
                  placeholder="Search or enter a URL"
                  disabled={!hasPage}
                  className="h-8 w-full rounded-full border border-(--color-border) bg-(--bg-key) pl-8 pr-10 text-xs text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-subtle) hover:border-(--color-border-strong) focus:border-(--color-accent) focus:bg-(--bg-page) focus:ring-2 focus:ring-(--color-accent)/15 disabled:opacity-50"
                  spellCheck={false}
                  aria-label="Address and search bar"
                />
                <button
                  type="submit"
                  disabled={!hasPage}
                  className="absolute right-1 top-1/2 flex h-6 w-7 -translate-y-1/2 items-center justify-center rounded-full text-(--color-text-muted) hover:bg-(--bg-page) hover:text-(--color-text) disabled:hidden"
                  aria-label="Go"
                  title="Go"
                >
                  <ArrowRight size={13} />
                </button>
              </form>
            )}

            {browser.downloads.length > 0 && (
              <div className="relative shrink-0">
                <ToolbarButton
                  label="Downloads"
                  onClick={() => {
                    setMenuOpen(false)
                    setDownloadsOpen((current) => !current)
                  }}
                >
                  <Download />
                </ToolbarButton>
                {activeDownloads > 0 && (
                  <span
                    aria-hidden
                    className="pointer-events-none absolute right-1 top-1 size-1.5 rounded-full bg-(--color-accent)"
                  />
                )}
              </div>
            )}

            {browser.viewportOverride && (
              <button
                type="button"
                onClick={() => void browser.setViewportPreset(null)}
                title="Back to the panel size"
                className="flex h-7 shrink-0 items-center gap-1 rounded-full border border-(--color-accent)/40 bg-(--color-accent)/12 px-2 font-mono text-[10px] tabular-nums text-(--color-accent) transition-colors hover:bg-(--color-accent)/20"
              >
                {browser.viewportOverride.width}×{browser.viewportOverride.height}
                <X size={11} aria-hidden />
                <span className="sr-only">Back to the panel size</span>
              </button>
            )}

            <ToolbarButton
              label={maximized ? 'Restore panel width' : 'Fill the window'}
              onClick={toggleMaximized}
            >
              {maximized ? <Minimize2 /> : <Maximize2 />}
            </ToolbarButton>

            <button
              type="button"
              onClick={() => setMenuOpen((current) => !current)}
              className={cn(
                'flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                menuOpen && 'bg-(--bg-key) text-(--color-text)',
              )}
              aria-label="Browser menu"
              aria-expanded={menuOpen}
              title="Browser menu"
            >
              <Menu size={16} />
            </button>
          </div>

          <div className="relative flex min-h-0 flex-1 overflow-hidden">
            <div
              ref={viewportRef}
              className={cn(
                'relative min-h-0 min-w-0 flex-1 overflow-hidden transition-colors',
                browser.viewportOverride
                  ? 'bg-[#202124] bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.13)_0.75px,transparent_0.75px)] bg-size-[12px_12px]'
                  : 'bg-white',
              )}
            >
              {browser.viewportOverride && (
                <>
                  <div className="pointer-events-none absolute inset-3 rounded-lg border border-white/12 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.35)]" />
                  {/* Non-interactive on purpose: a tall device fills the panel
                      and the native view covers this spot. The toolbar chip is
                      the one that can always be clicked. */}
                  <div className="pointer-events-none absolute bottom-2 left-1/2 z-(--z-panel) -translate-x-1/2 rounded-full border border-white/15 bg-black/65 px-2.5 py-1 font-mono text-[10px] tabular-nums text-white/80 shadow-lg backdrop-blur-md">
                    {browser.viewportOverride.width} × {browser.viewportOverride.height}
                  </div>
                </>
              )}
              {settingsOpen ? (
                <DirectBrowserSettingsView
                  active={enabled}
                  supported={browser.supported}
                  preferences={preferences}
                  onBack={() => setSettingsOpen(false)}
                  onToggleBrowser={(next) => {
                    setEnabled(next)
                    updatePreferences({ ...preferences, enabled: next })
                    if (!next) void browser.closeAll()
                  }}
                  onPreferencesChange={updatePreferences}
                  onZoomChange={handleDefaultZoomChange}
                  onPrint={() => void browser.command('print')}
                  onClearData={() => void handleClearData()}
                  onOpenDevTools={() => void browser.command('devtools')}
                />
              ) : !browser.supported ? (
                <div className="absolute inset-0 flex items-center justify-center bg-(--bg-page) px-6 text-center">
                  <div className="max-w-sm">
                    <Globe2 size={30} className="mx-auto mb-3 text-(--color-text-muted)" />
                    <p className="text-sm font-medium text-(--color-text)">Desktop browser required</p>
                    <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">
                      Direct browser rendering is available in the EvoFlux desktop app.
                    </p>
                  </div>
                </div>
              ) : browser.creating ? (
                <div className="absolute inset-0 flex items-center justify-center bg-(--bg-page)">
                  <Loader2 size={26} className="animate-spin text-(--color-accent)" />
                </div>
              ) : browser.pageError ? (
                <BrowserPageErrorView
                  error={browser.pageError}
                  onRetry={() => browser.pageError && void browser.navigate(browser.pageError.url)}
                  onOpenExternal={() => browser.pageError?.url
                    && void openExternalUrl(browser.pageError.url)}
                />
              ) : showLauncher && workspace ? (
                <BrowserLauncher
                  workspace={workspace}
                  paused={!visible}
                  onOpen={openInPage}
                />
              ) : showStartPage ? (
                <BrowserStartPage
                  recentSites={recentSites}
                  onOpen={(target) => openInPage(normalizeBrowserTarget(target))}
                />
              ) : null}
              {browser.pageDialog && !settingsOpen && (
                <BrowserPageDialogPrompt
                  dialog={browser.pageDialog}
                  onContinue={browser.dismissPageDialog}
                />
              )}
              {browser.pagePermission && !settingsOpen && (
                <BrowserPermissionPrompt
                  permission={browser.pagePermission}
                  onDecision={browser.resolvePagePermission}
                />
              )}
            </div>

            <AnimatePresence initial={false}>
              {siteInfoOpen && (
                <BrowserSiteInfoPanel
                  connection={connection}
                  url={currentUrl}
                  zoom={zoom}
                  defaultZoom={preferences.defaultZoom}
                  readPermissions={browser.readSitePermissions}
                  onClose={() => setSiteInfoOpen(false)}
                  onClearData={() => void handleClearData()}
                  onResetZoom={() => handleZoomChange(preferences.defaultZoom)}
                />
              )}
            </AnimatePresence>

            <AnimatePresence initial={false}>
              {downloadsOpen && (
                <BrowserDownloadsPanel
                  downloads={browser.downloads}
                  onClose={() => setDownloadsOpen(false)}
                  onClear={() => {
                    browser.clearDownloads()
                    setDownloadsOpen(false)
                  }}
                />
              )}
            </AnimatePresence>

            <AnimatePresence initial={false}>
              {menuOpen && (
                <DirectBrowserMenuPanel
                  active={hasPage}
                  currentUrl={currentUrl}
                  zoom={zoom}
                  fitDesktopWidth={preferences.fitDesktopWidth}
                  devToolsEnabled={preferences.developerTools}
                  viewportOverride={browser.viewportOverride}
                  onViewportPreset={(preset) => void browser.setViewportPreset(preset)}
                  onToggleFitDesktopWidth={() => updatePreferences({
                    ...preferences,
                    fitDesktopWidth: !preferences.fitDesktopWidth,
                  })}
                  onClose={() => setMenuOpen(false)}
                  onNewTab={() => onNewTab?.()}
                  onFind={() => setFindOpen(true)}
                  onOpenExternal={() => currentUrl && void openExternalUrl(currentUrl)}
                  onZoomChange={handleZoomChange}
                  onPrint={() => void browser.command('print')}
                  onClearData={() => void handleClearData()}
                  onOpenDevTools={() => void browser.command('devtools')}
                  onSettings={() => setSettingsOpen(true)}
                  onCloseTab={onClose}
                />
              )}
            </AnimatePresence>
          </div>
        </motion.section>
      </>
    </AnimatePresence>
  )
}

/**
 * What this site is, over what kind of connection, and what it has been
 * allowed to do — the questions the padlock implies it can answer.
 */
function BrowserSiteInfoPanel({
  connection,
  url,
  zoom,
  defaultZoom,
  readPermissions,
  onClose,
  onClearData,
  onResetZoom,
}: {
  connection: ReturnType<typeof browserConnectionInfo>
  url: string
  zoom: number
  defaultZoom: number
  readPermissions: () => Promise<BrowserSitePermission[]>
  onClose: () => void
  onClearData: () => void
  onResetZoom: () => void
}) {
  const [permissions, setPermissions] = useState<BrowserSitePermission[] | null>(null)

  useEffect(() => {
    let cancelled = false
    void readPermissions().then((result) => {
      if (!cancelled) setPermissions(result)
    })
    return () => {
      cancelled = true
    }
  }, [readPermissions, url])

  return (
    <motion.aside
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 12 }}
      className="relative z-(--z-panel) flex h-full w-[min(18rem,75%)] shrink-0 flex-col border-l border-(--color-border) bg-(--bg-card) shadow-lg"
      role="dialog"
      aria-label="Site information"
    >
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-(--color-border) px-3">
        <span className="text-xs font-semibold text-(--color-text)">Site information</span>
        <Button type="button" variant="ghost" size="icon-xs" onClick={onClose} aria-label="Close site information">
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <div>
          <p className="break-all text-xs font-medium text-(--color-text)">
            {connection.host || url || 'No page loaded'}
          </p>
          <p className="mt-1 flex items-center gap-1.5 text-[11px] text-(--color-text-muted)">
            {connection.encrypted
              ? <LockKeyhole size={11} aria-hidden />
              : <ShieldAlert size={11} aria-hidden />}
            {connection.summary}
          </p>
        </div>

        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
            Permissions
          </p>
          {permissions === null ? (
            <p className="mt-1 text-[11px] text-(--color-text-subtle)">Checking…</p>
          ) : permissions.length === 0 ? (
            <p className="mt-1 text-[11px] text-(--color-text-subtle)">
              Nothing granted or blocked.
            </p>
          ) : (
            <ul className="mt-1 space-y-1">
              {permissions.map((permission) => (
                <li
                  key={permission.name}
                  className="flex items-center justify-between gap-2 text-[11px] text-(--color-text)"
                >
                  <span className="capitalize">{permission.name.replace(/-/g, ' ')}</span>
                  <span
                    className={cn(
                      'rounded-full border px-1.5 py-0.5 text-[10px]',
                      permission.state === 'granted'
                        ? 'border-(--color-accent)/40 bg-(--color-accent)/12 text-(--color-accent)'
                        : 'border-(--color-border) text-(--color-text-muted)',
                    )}
                  >
                    {permission.state}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {zoom !== defaultZoom && (
          <div className="flex items-center justify-between gap-2 rounded-md border border-(--color-border) px-2 py-1.5">
            <span className="text-[11px] text-(--color-text)">Zoom {zoom}%</span>
            <button
              type="button"
              onClick={onResetZoom}
              className="rounded px-1.5 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              Reset
            </button>
          </div>
        )}

        <p className="text-[11px] leading-4 text-(--color-text-subtle)">
          Permissions and storage are cleared for every site at once — the
          engine keeps no per-site record this panel can edit.
        </p>
        <Button type="button" size="sm" variant="outline" onClick={onClearData} className="w-full">
          <Trash2 />
          Clear browsing data
        </Button>
      </div>
    </motion.aside>
  )
}

/** Downloads the page started, newest first. */
function BrowserDownloadsPanel({
  downloads,
  onClose,
  onClear,
}: {
  downloads: BrowserDownload[]
  onClose: () => void
  onClear: () => void
}) {
  const reveal = async (path: string) => {
    if (!path) return
    const { revealItemInDir } = await import('@tauri-apps/plugin-opener')
    await revealItemInDir(path).catch(() => {})
  }
  return (
    // A sibling of the viewport, not an overlay on it: the native view is an
    // OS window above this document, so a popover over the page is invisible.
    // Shrinking the viewport moves the native view out of the way instead.
    <motion.aside
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 12 }}
      className="relative z-(--z-panel) flex h-full w-[min(18rem,75%)] shrink-0 flex-col border-l border-(--color-border) bg-(--bg-card) shadow-lg"
      role="dialog"
      aria-label="Downloads"
    >
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-(--color-border) px-3">
        <span className="text-xs font-semibold text-(--color-text)">Downloads</span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onClear}
            className="rounded px-1.5 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            Clear
          </button>
          <Button type="button" variant="ghost" size="icon-xs" onClick={onClose} aria-label="Close downloads">
            <X />
          </Button>
        </div>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto p-1">
        {downloads.map((download) => (
          <li key={download.id}>
            <button
              type="button"
              onClick={() => void reveal(download.path)}
              disabled={!download.path}
              title={download.path || download.url}
              className="flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-(--bg-key) disabled:pointer-events-none"
            >
              <span className="w-full truncate text-xs text-(--color-text)">
                {downloadName(download)}
              </span>
              <span className="text-[10px] text-(--color-text-subtle)">
                {downloadStatus(download)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </motion.aside>
  )
}

function downloadName(download: BrowserDownload): string {
  const source = download.path || download.url
  const name = source.split(/[\\/]/).pop()
  return name || source
}

function downloadStatus(download: BrowserDownload): string {
  if (download.state === 'completed') return `Saved · ${formatBytes(download.totalBytes)}`
  if (download.state === 'interrupted') return 'Stopped'
  if (download.totalBytes > 0) {
    const percent = Math.min(99, Math.round((download.receivedBytes / download.totalBytes) * 100))
    return `${percent}% of ${formatBytes(download.totalBytes)}`
  }
  return `Downloading · ${formatBytes(download.receivedBytes)}`
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  const value = bytes / 1024 ** exponent
  return `${value >= 10 || exponent === 0 ? Math.round(value) : value.toFixed(1)} ${units[exponent]}`
}

/**
 * Our own page for a load that failed.
 *
 * The engine has one too, but it is a page inside the native view: the
 * address bar has already been replaced by an internal scheme, and nothing
 * there knows how to retry what the user actually asked for.
 */
function BrowserPageErrorView({
  error,
  onRetry,
  onOpenExternal,
}: {
  error: BrowserPageError
  onRetry: () => void
  onOpenExternal: () => void
}) {
  let host = error.url
  try {
    host = new URL(error.url).host || error.url
  } catch {
    // Keep the raw text: an unparseable address is the likeliest reason to
    // be looking at this page.
  }
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-(--bg-page) px-6 text-center">
      <div className="max-w-sm">
        <CircleAlert size={30} className="mx-auto mb-3 text-(--color-text-muted)" aria-hidden />
        <p className="text-sm font-medium text-(--color-text)">
          Could not open {host || 'this page'}
        </p>
        {error.detail && (
          <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">{error.detail}</p>
        )}
        {error.url && (
          <p className="mt-2 break-all font-mono text-[11px] leading-4 text-(--color-text-subtle)">
            {error.url}
          </p>
        )}
        <div className="mt-4 flex justify-center gap-2">
          <Button type="button" size="sm" onClick={onRetry} disabled={!error.url}>
            <RefreshCw />
            Try again
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onOpenExternal}
            disabled={!/^https?:/i.test(error.url)}
          >
            <ExternalLink />
            Open externally
          </Button>
        </div>
      </div>
    </div>
  )
}

function BrowserPermissionPrompt({
  permission,
  onDecision,
}: {
  permission: BrowserPermissionRequest
  onDecision: (allow: boolean) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const titleId = useId()
  const descriptionId = useId()
  const decide = async (allow: boolean) => {
    setBusy(true)
    setError(null)
    try {
      await onDecision(allow)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setBusy(false)
    }
  }
  const detail = permission.detail && Object.keys(permission.detail).length
    ? JSON.stringify(permission.detail)
    : null
  return (
    <div
      className="absolute inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-4 backdrop-blur-sm"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      data-modal-focus="true"
    >
      <div className="w-full max-w-sm overflow-hidden rounded-xl border border-(--color-primary)/35 bg-(--bg-page) shadow-xl">
        <div className="flex items-center gap-2 border-b border-(--color-border) bg-(--color-primary)/5 px-4 py-2.5">
          <CircleAlert size={15} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
          <span id={titleId} className="text-xs font-semibold text-(--color-text)">
            Browser permission request
          </span>
        </div>
        <div className="space-y-3 px-4 py-3">
          <p id={descriptionId} className="text-sm leading-5 text-(--color-text)">
            This page wants access to <strong>{permission.kind}</strong>.
          </p>
          {detail && (
            <code className="block max-h-24 overflow-auto rounded-md bg-(--bg-key) p-2 text-[11px] text-(--color-text-muted)">
              {detail}
            </code>
          )}
          {error && <p className="text-xs text-(--color-error)">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void decide(false)}>
              Deny
            </Button>
            <Button type="button" size="sm" disabled={busy} onClick={() => void decide(true)} autoFocus>
              Allow
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function BrowserPageDialogPrompt({
  dialog,
  onContinue,
}: {
  dialog: BrowserPageDialog
  onContinue: () => void
}) {
  const safelyDismissed = dialog.response === 'dismissed'
  const titleId = useId()
  const messageId = useId()
  return (
    <div
      className="absolute inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-4 backdrop-blur-sm"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={messageId}
      data-modal-focus="true"
    >
      <div className="w-full max-w-sm overflow-hidden rounded-xl border border-(--color-primary)/35 bg-(--bg-page) shadow-xl">
        <div className="flex items-center gap-2 border-b border-(--color-border) bg-(--color-primary)/5 px-4 py-2.5">
          <CircleAlert size={15} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
          <span id={titleId} className="text-xs font-semibold text-(--color-text)">
            Browser {dialog.type}
          </span>
        </div>
        <div className="space-y-3 px-4 py-3">
          <p id={messageId} className="whitespace-pre-wrap break-words text-sm leading-5 text-(--color-text)">
            {dialog.message || '(This page opened an empty dialog.)'}
          </p>
          {safelyDismissed && (
            <p className="text-xs leading-5 text-(--color-text-muted)">
              EvoFlux safely dismissed this blocking dialog so the browser and agent can continue.
            </p>
          )}
          <div className="flex justify-end">
            <Button type="button" size="sm" onClick={onContinue} autoFocus>
              Continue
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function DirectBrowserMenuPanel({
  active,
  currentUrl,
  zoom,
  fitDesktopWidth,
  devToolsEnabled,
  viewportOverride,
  onViewportPreset,
  onToggleFitDesktopWidth,
  onClose,
  onNewTab,
  onFind,
  onOpenExternal,
  onZoomChange,
  onPrint,
  onClearData,
  onOpenDevTools,
  onSettings,
  onCloseTab,
}: {
  active: boolean
  currentUrl: string
  zoom: number
  fitDesktopWidth: boolean
  devToolsEnabled: boolean
  viewportOverride: BrowserViewportOverride | null
  onViewportPreset: (preset: BrowserViewportPreset | null) => void
  onToggleFitDesktopWidth: () => void
  onClose: () => void
  onNewTab: () => void
  onFind: () => void
  onOpenExternal: () => void
  onZoomChange: (value: number) => void
  onPrint: () => void
  onClearData: () => void
  onOpenDevTools: () => void
  onSettings: () => void
  onCloseTab: () => void
}) {
  const runAndClose = (action: () => void) => {
    onClose()
    action()
  }
  const zoomIndex = Math.max(0, ZOOM_LEVELS.indexOf(zoom))
  const zoomOut = ZOOM_LEVELS[Math.max(0, zoomIndex - 1)] ?? zoom
  const zoomIn = ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, zoomIndex + 1)] ?? zoom

  return (
    <motion.aside
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 12 }}
      className="relative z-(--z-panel) flex h-full w-[min(16rem,70%)] shrink-0 flex-col border-l border-(--color-border) bg-(--bg-card) shadow-lg"
      aria-label="Browser menu panel"
    >
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-(--color-border) px-3">
        <span className="text-xs font-semibold text-(--color-text)">Browser menu</span>
        <Button type="button" variant="ghost" size="icon-xs" onClick={onClose} aria-label="Close browser menu">
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        <BrowserMenuAction onClick={() => runAndClose(onNewTab)}>
          <Plus />
          New tab
        </BrowserMenuAction>
        <BrowserMenuAction disabled={!active} onClick={() => runAndClose(onFind)}>
          <Search />
          Find in page
          <span className="ml-auto text-[10px] text-(--color-text-subtle)">⌘F</span>
        </BrowserMenuAction>
        <BrowserMenuAction disabled={!active} onClick={() => runAndClose(onPrint)}>
          <Printer />
          Print
        </BrowserMenuAction>
        <BrowserMenuAction disabled={!/^https?:/i.test(currentUrl)} onClick={() => runAndClose(onOpenExternal)}>
          <ExternalLink />
          Open in default browser
        </BrowserMenuAction>
        <div className="my-1 h-px bg-(--color-border)" />
        <div className="px-2 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
          Device
        </div>
        <div className="flex items-center gap-1 px-1.5 pb-1">
          {(['mobile', 'tablet', 'desktop'] as const).map((preset) => {
            const size = BROWSER_VIEWPORT_PRESETS[preset]
            const selected = viewportOverride?.width === size.width
              && viewportOverride?.height === size.height
            return (
              <button
                key={preset}
                type="button"
                disabled={!active}
                aria-pressed={selected}
                title={`${size.width} × ${size.height}`}
                onClick={() => onViewportPreset(selected ? null : preset)}
                className={cn(
                  'flex-1 rounded-md border px-1.5 py-1 text-xs capitalize transition-colors disabled:pointer-events-none disabled:opacity-40',
                  selected
                    ? 'border-(--color-accent)/45 bg-(--color-accent)/12 text-(--color-accent)'
                    : 'border-(--color-border) text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                )}
              >
                {preset}
              </button>
            )
          })}
        </div>
        <BrowserMenuAction
          disabled={!active || !viewportOverride}
          onClick={() => onViewportPreset(null)}
        >
          <Ruler />
          Fit to panel
        </BrowserMenuAction>
        <div className="my-1 h-px bg-(--color-border)" />
        <div className="flex h-9 items-center gap-2 rounded-md px-2 text-sm text-(--color-text)">
          <ZoomIn className="size-4 shrink-0" />
          <span>Zoom</span>
          <div className="ml-auto flex items-center gap-0.5 rounded-md border border-(--color-border) bg-(--bg-key) p-0.5">
            <Button type="button" variant="ghost" size="icon-xs" disabled={zoom <= ZOOM_LEVELS[0]} onClick={() => onZoomChange(zoomOut)} aria-label="Zoom out">−</Button>
            <span className="w-11 text-center text-xs tabular-nums">{zoom}%</span>
            <Button type="button" variant="ghost" size="icon-xs" disabled={zoom >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]} onClick={() => onZoomChange(zoomIn)} aria-label="Zoom in">+</Button>
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={fitDesktopWidth}
          onClick={onToggleFitDesktopWidth}
          className="flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-(--color-text) transition-colors hover:bg-(--bg-key) [&_svg]:size-4 [&_svg]:shrink-0"
        >
          <Monitor />
          <span>
            Desktop layout
            <span className="block text-[10px] leading-4 text-(--color-text-subtle)">
              Render pages at {FIT_DESKTOP_WIDTH}px and scale to fit
            </span>
          </span>
          <span
            className={cn(
              'ml-auto rounded-full border px-1.5 py-0.5 text-[10px] font-medium',
              fitDesktopWidth
                ? 'border-(--color-accent)/40 bg-(--color-accent)/12 text-(--color-accent)'
                : 'border-(--color-border) text-(--color-text-subtle)',
            )}
          >
            {fitDesktopWidth ? 'On' : 'Off'}
          </span>
        </button>
        <BrowserMenuAction disabled={!active} onClick={() => runAndClose(onClearData)}>
          <Trash2 />
          Clear browsing data
        </BrowserMenuAction>
        {devToolsEnabled && (
          <BrowserMenuAction disabled={!active} onClick={() => runAndClose(onOpenDevTools)}>
            <Wrench />
            Developer tools
          </BrowserMenuAction>
        )}
        <div className="my-1 h-px bg-(--color-border)" />
        <BrowserMenuAction onClick={() => runAndClose(onSettings)}>
          <Settings2 />
          Browser settings
        </BrowserMenuAction>
        <BrowserMenuAction disabled={!active} onClick={() => runAndClose(onCloseTab)}>
          <X />
          Close tab
        </BrowserMenuAction>
      </div>
    </motion.aside>
  )
}

function BrowserMenuAction({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-(--color-text) transition-colors hover:bg-(--bg-key) disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-4 [&_svg]:shrink-0"
    >
      {children}
    </button>
  )
}

function ToolbarButton({
  label,
  children,
  onClick,
  disabled,
}: {
  label: string
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-35"
      aria-label={label}
      title={label}
    >
      {children}
    </button>
  )
}

function normalizeBrowserTarget(value: string): string {
  if (/^[a-z][a-z\d+.-]*:/i.test(value)) return value
  if (value.includes('.') && !/\s/.test(value)) return `https://${value}`
  return `https://www.google.com/search?q=${encodeURIComponent(value)}`
}

function tabTitle(url: string): string {
  if (isBrowserNewTab(url)) return 'New tab'
  try {
    return new URL(url).hostname || new URL(url).protocol.replace(':', '')
  } catch {
    return url || 'New tab'
  }
}
