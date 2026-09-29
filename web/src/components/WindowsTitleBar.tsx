/**
 * WindowsTitleBar — the whole title-bar strip on Windows, where the native
 * one (and its menu strip) is off.
 *
 * Left: the app menu (File/Edit/View/Go/Developer/Help, a native popup so
 * clipboard items act on the focused field), the sidebar toggle and history
 * controls. Right: the caption buttons. Everything else drags the window and
 * double-click maximizes (useTauriDrag). The strip sits in the
 * `--app-titlebar-height` band that `.mobile-viewport` shells leave free.
 */
import { invoke } from '@tauri-apps/api/core'
import { LogicalPosition } from '@tauri-apps/api/dpi'
import { Menu, MenuItem, PredefinedMenuItem, Submenu } from '@tauri-apps/api/menu'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { ChevronLeft, ChevronRight, Menu as MenuIcon, PanelLeft } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { usePlatform } from '@/hooks/use-platform'
import { useDesktopSettings } from '@/hooks/useDesktopSettings'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useWindowHistory } from '@/hooks/use-window-history'
import { requestShellSidebarToggle } from '@/lib/shell-events'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/useUIStore'

const CONTROL_CLASS =
  'flex h-7 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--color-text)/6 hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40 disabled:pointer-events-none disabled:opacity-35'

const CAPTION_CLASS =
  'flex h-full w-[46px] items-center justify-center text-(--color-text-2) transition-colors focus-visible:outline-none focus-visible:bg-(--color-text)/8'

interface MenuActions {
  back: () => void
  forward: () => void
}

/** Ids are the native menu's (desktop main.rs); Rust runs them. */
function nativeAction(id: string) {
  return () => void invoke('app_menu_action', { id })
}

async function buildAppMenu(actions: MenuActions, trayIcon: boolean): Promise<Menu> {
  // Item ids carry a prefix so the app-wide native menu handler never runs
  // them a second time; each item's own action does the work.
  const item = (text: string, id: string, action: () => void, accelerator?: string) =>
    MenuItem.new({ id: `titlebar:${id}`, text, action, accelerator })
  const run = (text: string, id: string, accelerator?: string) =>
    item(text, id, nativeAction(id), accelerator)
  const separator = () => PredefinedMenuItem.new({ item: 'Separator' })
  const ui = useUIStore.getState()

  return Menu.new({
    items: [
      await Submenu.new({
        text: 'File',
        items: [
          await run('New Window', 'new_window'),
          await separator(),
          await run('Settings', 'settings', 'Ctrl+,'),
          await separator(),
          // Without the tray icon, closing the last window quits (desktop_settings.rs).
          await PredefinedMenuItem.new({
            item: 'CloseWindow',
            text: trayIcon ? 'Hide to Tray' : 'Close Window',
          }),
          await run('Quit EvoFlux', 'quit'),
        ],
      }),
      await Submenu.new({
        text: 'Edit',
        items: [
          await run('Undo', 'edit_undo', 'Ctrl+Z'),
          await run('Redo', 'edit_redo', 'Ctrl+Y'),
          await separator(),
          await PredefinedMenuItem.new({ item: 'Cut', text: 'Cut' }),
          await PredefinedMenuItem.new({ item: 'Copy', text: 'Copy' }),
          await PredefinedMenuItem.new({ item: 'Paste', text: 'Paste' }),
          await PredefinedMenuItem.new({ item: 'SelectAll', text: 'Select All' }),
        ],
      }),
      await Submenu.new({
        text: 'View',
        items: [
          await run('Command Palette…', 'command_palette', 'Ctrl+P'),
          await item('Toggle Sidebar', 'toggle_sidebar', requestShellSidebarToggle, 'Ctrl+B'),
          await run('Wiki', 'wiki'),
          await run('Scheduler', 'scheduler', 'Ctrl+S'),
          await separator(),
          await run('Zoom In', 'zoom_in', 'Ctrl+='),
          await run('Zoom Out', 'zoom_out', 'Ctrl+-'),
          await run('Actual Size', 'zoom_reset', 'Ctrl+0'),
        ],
      }),
      await Submenu.new({
        text: 'Go',
        items: [
          await item('Back', 'back', actions.back, 'Alt+Left'),
          await item('Forward', 'forward', actions.forward, 'Alt+Right'),
          await separator(),
          await run('Work', 'chat'),
          await run('Coding', 'coding'),
          await separator(),
          await run('Providers', 'providers'),
          await run('Notifications', 'notifications'),
          await run('Telemetry', 'telemetry'),
        ],
      }),
      await Submenu.new({
        text: 'Developer',
        items: [
          await run('Reload', 'reload', 'Ctrl+R'),
          await run('Force Reload', 'force_reload'),
          await separator(),
          await run('Open Config Folder', 'open_config_dir'),
          await run('Show Backend Log', 'reveal_backend_log'),
        ],
      }),
      await Submenu.new({
        text: 'Help',
        items: [
          await item('Guidelines', 'guidelines', () => ui.openGuidelines()),
          await run('Check for Updates…', 'check_updates'),
          await separator(),
          await item('About EvoFlux', 'about', () => ui.openSettings('')),
        ],
      }),
    ],
  })
}

/** Windows 11 caption glyphs: 10px hairline strokes. */
function CaptionGlyph({ kind }: { kind: 'minimize' | 'maximize' | 'restore' | 'close' }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1" aria-hidden="true">
      {kind === 'minimize' && <path d="M0 5.5h10" />}
      {kind === 'maximize' && <rect x="0.5" y="0.5" width="9" height="9" rx="1" />}
      {kind === 'restore' && (
        <>
          <rect x="0.5" y="2.5" width="7" height="7" rx="1" />
          <path d="M2.5 2.5V1.5a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-1" />
        </>
      )}
      {kind === 'close' && <path d="M0.5 0.5l9 9M9.5 0.5l-9 9" />}
    </svg>
  )
}

export function WindowsTitleBar() {
  const { isWindowsTitleBar } = usePlatform()
  const dragHandlers = useTauriDrag()
  const { canGoBack, canGoForward, back, forward, hasAppSidebar, sidebarCollapsed } =
    useWindowHistory()
  const [maximized, setMaximized] = useState(false)
  const trayIcon = useDesktopSettings().data?.tray_icon ?? true
  const menuRef = useRef<{ trayIcon: boolean; menu: Promise<Menu> } | null>(null)
  const actionsRef = useRef<MenuActions>({ back, forward })
  useEffect(() => {
    actionsRef.current = { back, forward }
  })

  useEffect(() => {
    if (!isWindowsTitleBar) return
    document.documentElement.setAttribute('data-windows-titlebar', '')
    return () => document.documentElement.removeAttribute('data-windows-titlebar')
  }, [isWindowsTitleBar])

  useEffect(() => {
    if (!isWindowsTitleBar) return
    const appWindow = getCurrentWindow()
    let unlisten: (() => void) | undefined
    let cancelled = false
    const sync = () => void appWindow.isMaximized().then((value) => {
      if (!cancelled) setMaximized(value)
    })
    sync()
    void appWindow.onResized(sync).then((stop) => {
      if (cancelled) stop()
      else unlisten = stop
    })
    return () => {
      cancelled = true
      unlisten?.()
    }
  }, [isWindowsTitleBar])

  if (!isWindowsTitleBar) return null

  const openMenu = async (button: HTMLButtonElement) => {
    // Built once per tray setting; history items read the latest callbacks
    // through the ref.
    if (menuRef.current?.trayIcon !== trayIcon) {
      menuRef.current = {
        trayIcon,
        menu: buildAppMenu(
          {
            back: () => actionsRef.current.back(),
            forward: () => actionsRef.current.forward(),
          },
          trayIcon,
        ),
      }
    }
    const menu = await menuRef.current.menu
    const rect = button.getBoundingClientRect()
    await menu.popup(new LogicalPosition(rect.left, rect.bottom + 4))
  }

  const appWindow = getCurrentWindow()

  return (
    <div
      {...dragHandlers}
      // Above modal scrims (not the lightbox): like a native frame, the
      // window can still be dragged, minimized or closed while a dialog is up.
      className="fixed inset-x-0 top-0 z-(--z-toast) flex h-(--app-titlebar-height) select-none items-center"
      aria-label="Window title bar"
    >
      <div className="flex h-full items-center gap-0.5 pl-2">
        <button
          type="button"
          onClick={(event) => void openMenu(event.currentTarget)}
          aria-label="Application menu"
          aria-haspopup="menu"
          title="Menu"
          className={CONTROL_CLASS}
        >
          <MenuIcon size={16} strokeWidth={1.7} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={requestShellSidebarToggle}
          disabled={!hasAppSidebar}
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!sidebarCollapsed}
          title={`${sidebarCollapsed ? 'Expand' : 'Collapse'} sidebar (Ctrl+B)`}
          className={CONTROL_CLASS}
        >
          <PanelLeft size={16} strokeWidth={1.7} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={back}
          disabled={!canGoBack}
          aria-label="Back"
          title="Back"
          className={CONTROL_CLASS}
        >
          <ChevronLeft size={16} strokeWidth={1.8} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={forward}
          disabled={!canGoForward}
          aria-label="Forward"
          title="Forward"
          className={CONTROL_CLASS}
        >
          <ChevronRight size={16} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>

      <div className="h-full flex-1" />

      <div className="flex h-full items-stretch">
        <button
          type="button"
          onClick={() => void appWindow.minimize()}
          aria-label="Minimize"
          title="Minimize"
          className={cn(CAPTION_CLASS, 'hover:bg-(--color-text)/6')}
        >
          <CaptionGlyph kind="minimize" />
        </button>
        <button
          type="button"
          onClick={() => void appWindow.toggleMaximize()}
          aria-label={maximized ? 'Restore' : 'Maximize'}
          title={maximized ? 'Restore Down' : 'Maximize'}
          className={cn(CAPTION_CLASS, 'hover:bg-(--color-text)/6')}
        >
          <CaptionGlyph kind={maximized ? 'restore' : 'maximize'} />
        </button>
        <button
          type="button"
          onClick={() => void appWindow.close()}
          aria-label="Close"
          title="Close"
          className={cn(CAPTION_CLASS, 'hover:bg-[#c42b1c] hover:text-white')}
        >
          <CaptionGlyph kind="close" />
        </button>
      </div>
    </div>
  )
}
