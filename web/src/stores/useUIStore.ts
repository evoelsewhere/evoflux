/**
 * useUIStore — tiny client-state store for UI panels that live above the
 * TeamChatView and were previously owned by ``Sidebar``. Lifting state to a
 * shared store lets shortcuts and command palette items coordinate modal
 * visibility from one path.
 *
 * Also owns the desktop sidebar collapse state — one field shared by all
 * three mode sidebars (forge / coding / aim) and toggled from AppShell
 * (button + Ctrl+B). This is the store's only persisted field.
 *
 * Mirrors the size and shape of ``useToastStore`` — Zustand + immer, no
 * derived selectors.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { STORAGE_KEYS } from '@/lib/storage-keys'

const SIDEBAR_COLLAPSED_KEY = STORAGE_KEYS.sidebar.collapsed

export const SIDEBAR_WIDTH = {
  default: 280,
  min: 248,
  max: 420,
} as const

function clampSidebarWidth(width: number): number {
  return Math.min(Math.max(width, SIDEBAR_WIDTH.min), SIDEBAR_WIDTH.max)
}

function loadSidebarWidth(): number {
  try {
    const candidates = [
      STORAGE_KEYS.sidebar.width,
      STORAGE_KEYS.sidebar.codingWidth,
      STORAGE_KEYS.sidebar.aimWidth,
    ]
    for (const key of candidates) {
      const stored = localStorage.getItem(key)
      const parsed = stored === null ? Number.NaN : Number(stored)
      if (!Number.isFinite(parsed)) continue
      const width = clampSidebarWidth(parsed)
      localStorage.setItem(STORAGE_KEYS.sidebar.width, String(width))
      return width
    }
    localStorage.setItem(
      STORAGE_KEYS.sidebar.width,
      String(SIDEBAR_WIDTH.default),
    )
  } catch {
    // Storage can be unavailable during SSR or in privacy-restricted contexts.
  }
  return SIDEBAR_WIDTH.default
}

function persistSidebarWidth(width: number): void {
  try {
    localStorage.setItem(STORAGE_KEYS.sidebar.width, String(width))
  } catch {
    // ignore storage failures
  }
}

function loadSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function persistSidebarCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed))
  } catch {
    // ignore storage failures
  }
}

interface UIStore {
  wikiOpen: boolean
  schedulerOpen: boolean
  browserOpen: boolean
  terminalOpen: boolean
  sidebarCollapsed: boolean
  sidebarWidth: number
  settingsOpen: boolean
  settingsPath: string
  settingsSearch: Record<string, string>
  /**
   * One-shot request to open the side chat panel for a specific session —
   * set by the sidebar session-row icon; consumed and cleared by
   * TeamChatView once that session is active.
   */
  sideChatRequest: string | null
  toggleWiki: () => void
  toggleScheduler: () => void
  toggleBrowser: () => void
  toggleTerminal: () => void
  closeWiki: () => void
  closeScheduler: () => void
  closeBrowser: () => void
  closeTerminal: () => void
  toggleSidebarCollapsed: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setSidebarWidth: (width: number) => void
  resetSidebarWidth: () => void
  openSettings: (path?: string, search?: Record<string, string>) => void
  closeSettings: () => void
  navigateSettings: (path: string, search?: Record<string, string>) => void
  requestSideChat: (sessionId: string) => void
  clearSideChatRequest: () => void
}

export const useUIStore = create<UIStore>()(
  immer((set) => ({
    wikiOpen: false,
    schedulerOpen: false,
    browserOpen: false,
    terminalOpen: false,
    toggleWiki: () => set((state) => {
      const nextOpen = !state.wikiOpen
      state.wikiOpen = nextOpen
      if (nextOpen) {
        state.schedulerOpen = false
        state.browserOpen = false
      }
    }),
    toggleScheduler: () => set((state) => {
      const nextOpen = !state.schedulerOpen
      state.schedulerOpen = nextOpen
      if (nextOpen) {
        state.wikiOpen = false
        state.browserOpen = false
      }
    }),
    toggleBrowser: () => set((state) => {
      const nextOpen = !state.browserOpen
      state.browserOpen = nextOpen
      if (nextOpen) {
        state.wikiOpen = false
        state.schedulerOpen = false
        state.terminalOpen = false
      }
    }),
    // The terminal is a right-side aside (mounted in ChatTrailingPanels),
    // not a full-screen overlay — it can sit open alongside
    // wiki/scheduler/browser, so toggling it doesn't close them.
    toggleTerminal: () => set((state) => {
      const nextOpen = !state.terminalOpen
      state.terminalOpen = nextOpen
      if (nextOpen) state.browserOpen = false
    }),
    closeWiki: () => set((state) => { state.wikiOpen = false }),
    closeScheduler: () => set((state) => { state.schedulerOpen = false }),
    closeBrowser: () => set((state) => { state.browserOpen = false }),
    closeTerminal: () => set((state) => { state.terminalOpen = false }),
    sidebarCollapsed: loadSidebarCollapsed(),
    sidebarWidth: loadSidebarWidth(),
    toggleSidebarCollapsed: () => set((state) => {
      state.sidebarCollapsed = !state.sidebarCollapsed
      persistSidebarCollapsed(state.sidebarCollapsed)
    }),
    setSidebarCollapsed: (collapsed) => set((state) => {
      state.sidebarCollapsed = collapsed
      persistSidebarCollapsed(collapsed)
    }),
    setSidebarWidth: (width) => set((state) => {
      const nextWidth = clampSidebarWidth(width)
      state.sidebarWidth = nextWidth
      persistSidebarWidth(nextWidth)
    }),
    resetSidebarWidth: () => set((state) => {
      state.sidebarWidth = SIDEBAR_WIDTH.default
      persistSidebarWidth(SIDEBAR_WIDTH.default)
    }),
    settingsOpen: false,
    settingsPath: '',
    settingsSearch: {},
    openSettings: (path = '', search = {}) => set((state) => { state.settingsOpen = true; state.settingsPath = path; state.settingsSearch = search }),
    closeSettings: () => set((state) => { state.settingsOpen = false }),
    navigateSettings: (path: string, search = {}) => set((state) => { state.settingsPath = path; state.settingsSearch = search }),
    sideChatRequest: null,
    requestSideChat: (sessionId) => set((state) => { state.sideChatRequest = sessionId }),
    clearSideChatRequest: () => set((state) => { state.sideChatRequest = null }),
  }))
)
