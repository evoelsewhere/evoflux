import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ExternalLink,
  Globe2,
  Loader2,
  LockKeyhole,
  Menu,
  Plus,
  Printer,
  RefreshCw,
  Search,
  Settings2,
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
import {
  loadBrowserPreferences,
  saveBrowserPreferences,
  type BrowserPreferences,
} from './browserPreferences'
import { DirectBrowserSettingsView } from './DirectBrowserSettingsView'
import {
  isBrowserNewTab,
  useDirectBrowserTabs,
} from './useDirectBrowserTabs'

const MIN_WIDTH = 420
const MAX_WIDTH = 1400
const DEFAULT_WIDTH = 720
const ZOOM_LEVELS = [50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200]

interface DirectBrowserShellProps {
  sessionId: string | null
  tabId?: string
  initialUrl?: string
  open: boolean
  visible?: boolean
  onClose: () => void
  onNewTab?: (url?: string) => void
  onTitleChange?: (title: string) => void
  className?: string
  embedded?: boolean
}

export function DirectBrowserShell({
  sessionId,
  tabId = 'browser',
  initialUrl,
  open,
  visible = true,
  onClose,
  onNewTab,
  onTitleChange,
  className,
  embedded = false,
}: DirectBrowserShellProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const urlInputRef = useRef<HTMLInputElement>(null)
  const onTitleChangeRef = useRef(onTitleChange)
  const urlFocusedRef = useRef(false)
  const resizingRef = useRef(false)
  const [enabled, setEnabled] = useState(true)
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [preferences, setPreferences] = useState<BrowserPreferences>(loadBrowserPreferences)
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const preset = useMotionPreset()
  const pushToast = useToastStore((state) => state.push)

  const reportError = useCallback((message: string) => {
    pushToast({
      tone: 'error',
      title: 'Browser action failed',
      description: message,
    })
  }, [pushToast])

  const browser = useDirectBrowserTabs({
    sessionId: sessionId ?? 'detached',
    instanceId: tabId,
    viewportRef,
    enabled: Boolean(open && sessionId && enabled),
    visible: Boolean(open && visible && !settingsOpen),
    bridgeEnabled: visible,
    initialUrl,
    singleTab: true,
    zoom: preferences.defaultZoom,
    devtools: preferences.developerTools,
    onError: reportError,
    onRequestNewTab: (url) => onNewTab?.(url),
  })

  const currentUrl = browser.activeTab?.url ?? ''
  const hasPage = Boolean(browser.activeTab)

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

  useEffect(() => {
    if (!open || !visible) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        if (hasPage) setFindOpen(true)
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'l') {
        event.preventDefault()
        urlInputRef.current?.focus()
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 't') {
        event.preventDefault()
        onNewTab?.()
      } else if (event.key === 'Escape') {
        if (findOpen) setFindOpen(false)
        else if (menuOpen) setMenuOpen(false)
        else if (settingsOpen) setSettingsOpen(false)
        else onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [browser, findOpen, hasPage, menuOpen, onClose, onNewTab, open, settingsOpen, visible])

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

  const handleZoomChange = useCallback((value: number) => {
    updatePreferences({
      ...preferences,
      defaultZoom: Math.max(50, Math.min(200, value)),
    })
  }, [preferences, updatePreferences])

  const handleClearData = useCallback(async () => {
    try {
      await browser.clearBrowsingData()
      pushToast({ tone: 'success', title: 'Browsing data cleared' })
    } catch (error) {
      reportError(error instanceof Error ? error.message : String(error))
    }
  }, [browser, pushToast, reportError])

  const handleResizeStart = useCallback((event: React.MouseEvent) => {
    event.preventDefault()
    resizingRef.current = true
    const startX = event.clientX
    const startWidth = width
    const handleMove = (moveEvent: MouseEvent) => {
      if (!resizingRef.current) return
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + startX - moveEvent.clientX)))
    }
    const handleUp = () => {
      resizingRef.current = false
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [width])

  if (!open || !sessionId) return null

  return (
    <AnimatePresence>
      <>
        {!embedded && (
          <motion.button
            type="button"
            aria-label="Close browser"
            className="fixed inset-0 z-(--z-overlay) bg-(--color-overlay) backdrop-blur-sm sm:hidden"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={preset.transition}
          />
        )}
        <motion.section
          aria-label="Built-in browser"
          className={cn(
            'flex min-w-0 flex-col overflow-hidden border-l border-(--color-border-strong) bg-(--bg-page)',
            embedded
              ? 'relative h-full min-h-0 w-full'
              : 'fixed inset-x-0 bottom-0 top-[env(safe-area-inset-top,0px)] z-(--z-modal) sm:relative sm:inset-auto sm:h-full sm:min-h-0 sm:shrink-0 sm:w-[var(--browser-viewer-width)]',
            className,
          )}
          style={embedded ? undefined : { '--browser-viewer-width': `${width}px` } as React.CSSProperties}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={preset.transition}
        >
          {!embedded && (
            <div
              className="group/handle absolute bottom-0 left-0 top-0 z-(--z-panel) hidden w-2 cursor-col-resize sm:block"
              onMouseDown={handleResizeStart}
              onDoubleClick={() => setWidth(DEFAULT_WIDTH)}
              title="Resize browser"
            >
              <div className="absolute bottom-0 left-0 top-0 w-px bg-(--color-border-strong) group-hover/handle:bg-(--color-accent)" />
            </div>
          )}

          <div className="flex h-11 shrink-0 items-center gap-1.5 border-b border-(--color-border) bg-(--bg-page) px-2">
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
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-subtle)">
                  {currentUrl.startsWith('https://') ? <LockKeyhole size={12} /> : <Globe2 size={13} />}
                </span>
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
            <div ref={viewportRef} className="relative min-h-0 min-w-0 flex-1 overflow-hidden bg-white">
              {settingsOpen ? (
                <DirectBrowserSettingsView
                  active={hasPage}
                  supported={browser.supported}
                  preferences={preferences}
                  onBack={() => setSettingsOpen(false)}
                  onToggleBrowser={(next) => {
                    setEnabled(next)
                    if (!next) void browser.closeAll()
                  }}
                  onPreferencesChange={updatePreferences}
                  onZoomChange={handleZoomChange}
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
              ) : null}
            </div>

            <AnimatePresence initial={false}>
              {menuOpen && (
                <DirectBrowserMenuPanel
                  active={hasPage}
                  currentUrl={currentUrl}
                  zoom={preferences.defaultZoom}
                  devToolsEnabled={preferences.developerTools}
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

function DirectBrowserMenuPanel({
  active,
  currentUrl,
  zoom,
  devToolsEnabled,
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
  devToolsEnabled: boolean
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
        <div className="flex h-9 items-center gap-2 rounded-md px-2 text-sm text-(--color-text)">
          <ZoomIn className="size-4 shrink-0" />
          <span>Zoom</span>
          <div className="ml-auto flex items-center gap-0.5 rounded-md border border-(--color-border) bg-(--bg-key) p-0.5">
            <Button type="button" variant="ghost" size="icon-xs" disabled={zoom <= ZOOM_LEVELS[0]} onClick={() => onZoomChange(zoomOut)} aria-label="Zoom out">−</Button>
            <span className="w-11 text-center text-xs tabular-nums">{zoom}%</span>
            <Button type="button" variant="ghost" size="icon-xs" disabled={zoom >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]} onClick={() => onZoomChange(zoomIn)} aria-label="Zoom in">+</Button>
          </div>
        </div>
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
