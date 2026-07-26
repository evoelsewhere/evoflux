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

export type WorkbenchTool =
  | 'review'
  | 'terminal'
  | 'browser'
  | 'files'
  | 'side-chat'
  | 'wiki'
  | 'scheduler'
  | 'pull-requests'

export interface WorkbenchTab {
  id: WorkbenchTool
  tool: WorkbenchTool
}

export type PullRequestsScope = 'all' | 'session'

interface WorkbenchState {
  workbenchTabs: WorkbenchTab[]
  activeWorkbenchTool: WorkbenchTool | null
  workbenchOpen: boolean
  workbenchMaximized: boolean
  pullRequestsScope: PullRequestsScope
}

function toggleTool(state: WorkbenchState, tool: WorkbenchTool): void {
  const index = state.workbenchTabs.findIndex((tab) => tab.tool === tool)
  if (index === -1) {
    state.workbenchTabs.push({ id: tool, tool })
    state.activeWorkbenchTool = tool
    state.workbenchOpen = true
    return
  }
  if (state.activeWorkbenchTool === tool && state.workbenchOpen) {
    state.workbenchOpen = false
    state.workbenchMaximized = false
    return
  }
  state.activeWorkbenchTool = tool
  state.workbenchOpen = true
}

function closeTool(state: WorkbenchState, tool: WorkbenchTool): void {
  const index = state.workbenchTabs.findIndex((tab) => tab.tool === tool)
  if (index === -1) return
  state.workbenchTabs.splice(index, 1)
  if (state.activeWorkbenchTool === tool) {
    state.activeWorkbenchTool =
      state.workbenchTabs[Math.min(index, state.workbenchTabs.length - 1)]?.tool
      ?? state.workbenchTabs.at(-1)?.tool
      ?? null
  }
  if (state.workbenchTabs.length === 0) state.workbenchMaximized = false
}

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
  workbenchTabs: WorkbenchTab[]
  activeWorkbenchTool: WorkbenchTool | null
  workbenchOpen: boolean
  workbenchMaximized: boolean
  pullRequestsScope: PullRequestsScope
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
  openWorkbenchTool: (tool: WorkbenchTool) => void
  toggleWorkbenchTool: (tool: WorkbenchTool) => void
  selectWorkbenchTool: (tool: WorkbenchTool) => void
  closeWorkbenchTool: (tool: WorkbenchTool) => void
  closeActiveWorkbenchTool: () => void
  toggleWorkbench: () => void
  closeWorkbench: () => void
  showWorkbenchLauncher: () => void
  toggleWorkbenchMaximized: () => void
  toggleWiki: () => void
  toggleScheduler: () => void
  togglePullRequests: () => void
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
    workbenchTabs: [],
    activeWorkbenchTool: null,
    workbenchOpen: false,
    workbenchMaximized: false,
    pullRequestsScope: 'session',
    openWorkbenchTool: (tool) => set((state) => {
      if (tool === 'pull-requests') state.pullRequestsScope = 'session'
      if (!state.workbenchTabs.some((tab) => tab.tool === tool)) {
        state.workbenchTabs.push({ id: tool, tool })
      }
      state.activeWorkbenchTool = tool
      state.workbenchOpen = true
    }),
    toggleWorkbenchTool: (tool) => set((state) => {
      if (tool === 'pull-requests') state.pullRequestsScope = 'session'
      toggleTool(state, tool)
    }),
    selectWorkbenchTool: (tool) => set((state) => {
      if (state.workbenchTabs.some((tab) => tab.tool === tool)) {
        if (tool === 'pull-requests') state.pullRequestsScope = 'session'
        state.activeWorkbenchTool = tool
        state.workbenchOpen = true
      }
    }),
    closeWorkbenchTool: (tool) => set((state) => {
      closeTool(state, tool)
    }),
    closeActiveWorkbenchTool: () => set((state) => {
      const tool = state.activeWorkbenchTool
      if (!tool) return
      const index = state.workbenchTabs.findIndex((tab) => tab.tool === tool)
      if (index !== -1) state.workbenchTabs.splice(index, 1)
      state.activeWorkbenchTool =
        state.workbenchTabs[Math.min(index, state.workbenchTabs.length - 1)]?.tool
        ?? state.workbenchTabs.at(-1)?.tool
        ?? null
      if (state.workbenchTabs.length === 0) state.workbenchMaximized = false
    }),
    toggleWorkbench: () => set((state) => {
      state.workbenchOpen = !state.workbenchOpen
      if (
        state.workbenchOpen
        && state.activeWorkbenchTool === 'pull-requests'
      ) {
        state.pullRequestsScope = 'session'
      }
      if (!state.workbenchOpen) state.workbenchMaximized = false
    }),
    closeWorkbench: () => set((state) => {
      state.workbenchOpen = false
      state.workbenchMaximized = false
    }),
    showWorkbenchLauncher: () => set((state) => {
      state.workbenchOpen = true
      state.activeWorkbenchTool = null
      state.workbenchMaximized = false
    }),
    toggleWorkbenchMaximized: () => set((state) => {
      if (state.activeWorkbenchTool) {
        state.workbenchMaximized = !state.workbenchMaximized
      }
    }),
    // Compatibility entry points used by desktop commands, sidebar actions,
    // and streamed tool calls. They now all target the shared workbench.
    toggleWiki: () => set((state) => { toggleTool(state, 'wiki') }),
    toggleScheduler: () => set((state) => { toggleTool(state, 'scheduler') }),
    togglePullRequests: () => set((state) => {
      const switchScopeOnly =
        state.pullRequestsScope === 'session'
        && state.activeWorkbenchTool === 'pull-requests'
        && state.workbenchOpen
      state.pullRequestsScope = 'all'
      if (switchScopeOnly) return
      toggleTool(state, 'pull-requests')
    }),
    toggleBrowser: () => set((state) => { toggleTool(state, 'browser') }),
    toggleTerminal: () => set((state) => { toggleTool(state, 'terminal') }),
    closeWiki: () => set((state) => { closeTool(state, 'wiki') }),
    closeScheduler: () => set((state) => { closeTool(state, 'scheduler') }),
    closeBrowser: () => set((state) => { closeTool(state, 'browser') }),
    closeTerminal: () => set((state) => { closeTool(state, 'terminal') }),
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
