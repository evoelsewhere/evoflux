/**
 * useUIStore — tiny client-state store for UI panels that live above the
 * TeamChatView and were previously owned by ``Sidebar``. Lifting state to a
 * shared store lets shortcuts and command palette items coordinate modal
 * visibility from one path.
 *
 * Also owns the desktop sidebar collapse state — one field shared by both
 * mode sidebars (work / coding) and toggled from AppShell (button + Ctrl+B).
 * This is the store's only persisted field.
 *
 * Mirrors the size and shape of ``useToastStore`` — Zustand + immer, no
 * derived selectors.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { STORAGE_KEYS } from '@/lib/storage-keys'

const SIDEBAR_COLLAPSED_KEY = STORAGE_KEYS.sidebar.collapsed

export type WorkbenchTool =
  | 'overview'
  | 'terminal'
  | 'processes'
  | 'browser'
  | 'files'
  | 'graph'
  | 'side-chat'
  | 'wiki'
  | 'scheduler'
  | 'plugins'
  | 'source-control'
  | 'pull-requests'
  | 'problems'
  | 'easd'

export interface WorkbenchTab {
  id: string
  tool: WorkbenchTool
  title?: string
  initialUrl?: string
}

export interface WorkbenchTabOptions {
  id?: string
  initialUrl?: string
  title?: string
}

export type PullRequestsScope = 'all' | 'session'
export type GitWorkspaceView = 'changes' | 'reviews'

export interface WorkspaceFileRequest {
  id: number
  sessionId: string
  path: string
}

export interface EasdChatRequest {
  id: number
  sessionId: string
  workspace: string
  projectId: string | null
  prompt: string | null
  autoSend: boolean
  phase: 'authoring' | 'planning' | 'implementation' | 'review' | 'verification'
}

interface WorkbenchState {
  workbenchTabs: WorkbenchTab[]
  activeWorkbenchTabId: string | null
  activeWorkbenchTool: WorkbenchTool | null
  workbenchOpen: boolean
  workbenchMaximized: boolean
  pullRequestsScope: PullRequestsScope
  gitWorkspaceView: GitWorkspaceView
}

const MULTI_INSTANCE_TOOLS = new Set<WorkbenchTool>(['terminal', 'browser'])
let workbenchTabSequence = 0
let workspaceFileRequestSequence = 0
let easdChatRequestSequence = 0

function newWorkbenchTab(
  tool: WorkbenchTool,
  options: WorkbenchTabOptions = {},
): WorkbenchTab {
  workbenchTabSequence += 1
  return {
    id: options.id
      ?? `${tool}-${Date.now().toString(36)}-${workbenchTabSequence.toString(36)}`,
    tool,
    initialUrl: options.initialUrl,
    title: options.title,
  }
}

function activateTab(state: WorkbenchState, tab: WorkbenchTab | undefined): void {
  state.activeWorkbenchTabId = tab?.id ?? null
  state.activeWorkbenchTool = tab?.tool ?? null
}

function lastTabForTool(
  tabs: readonly WorkbenchTab[],
  tool: WorkbenchTool,
): WorkbenchTab | undefined {
  for (let index = tabs.length - 1; index >= 0; index -= 1) {
    if (tabs[index]?.tool === tool) return tabs[index]
  }
  return undefined
}

function addOrActivateTool(
  state: WorkbenchState,
  tool: WorkbenchTool,
  options: WorkbenchTabOptions = {},
  forceNew = false,
): WorkbenchTab {
  const existing = forceNew && MULTI_INSTANCE_TOOLS.has(tool)
    ? undefined
    : lastTabForTool(state.workbenchTabs, tool)
  const tab = existing ?? newWorkbenchTab(tool, options)
  if (!existing) state.workbenchTabs.push(tab)
  activateTab(state, tab)
  state.workbenchOpen = true
  return tab
}

function toggleTool(state: WorkbenchState, tool: WorkbenchTool): void {
  const tab = lastTabForTool(state.workbenchTabs, tool)
  if (!tab) {
    addOrActivateTool(state, tool)
    return
  }
  if (state.activeWorkbenchTabId === tab.id && state.workbenchOpen) {
    state.workbenchOpen = false
    state.workbenchMaximized = false
    return
  }
  activateTab(state, tab)
  state.workbenchOpen = true
}

function closeTab(state: WorkbenchState, tabId: string): void {
  const index = state.workbenchTabs.findIndex((tab) => tab.id === tabId)
  if (index === -1) return
  const wasActive = state.activeWorkbenchTabId === tabId
  state.workbenchTabs.splice(index, 1)
  if (wasActive) {
    activateTab(
      state,
      state.workbenchTabs[Math.min(index, state.workbenchTabs.length - 1)]
        ?? state.workbenchTabs.at(-1),
    )
  }
  if (state.workbenchTabs.length === 0) state.workbenchMaximized = false
}

function closeTool(state: WorkbenchState, tool: WorkbenchTool): void {
  const activeIndex = state.workbenchTabs.findIndex(
    (tab) => tab.id === state.activeWorkbenchTabId,
  )
  const closingActive = state.activeWorkbenchTool === tool
  state.workbenchTabs = state.workbenchTabs.filter((tab) => tab.tool !== tool)
  if (closingActive) {
    activateTab(
      state,
      state.workbenchTabs[Math.min(activeIndex, state.workbenchTabs.length - 1)]
        ?? state.workbenchTabs.at(-1),
    )
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
  activeWorkbenchTabId: string | null
  activeWorkbenchTool: WorkbenchTool | null
  workbenchOpen: boolean
  workbenchMaximized: boolean
  pullRequestsScope: PullRequestsScope
  gitWorkspaceView: GitWorkspaceView
  sidebarCollapsed: boolean
  /** Transient responsive mode; unlike collapse/width this is not persisted. */
  sidebarOverlay: boolean
  sidebarResizing: boolean
  sidebarWidth: number
  settingsOpen: boolean
  settingsPath: string
  settingsSearch: Record<string, string>
  /** Searchable in-app Guidelines modal (sidebar Help). */
  guidelinesOpen: boolean
  guidelinesTopicId: string | null
  /**
   * One-shot request to open the side chat panel for a specific session —
   * set by the sidebar session-row icon; consumed and cleared by
   * TeamChatView once that session is active.
   */
  sideChatRequest: string | null
  /** One-shot request from a transcript artifact link to preview a workspace file. */
  workspaceFileRequest: WorkspaceFileRequest | null
  /** One-shot handoff from an EASD run to its linked Coding chat. */
  easdChatRequest: EasdChatRequest | null
  createWorkbenchTab: (tool: WorkbenchTool, options?: WorkbenchTabOptions) => void
  restoreWorkbenchTabs: (
    tool: WorkbenchTool,
    tabs: WorkbenchTabOptions[],
  ) => void
  openWorkbenchTool: (tool: WorkbenchTool, options?: WorkbenchTabOptions) => void
  toggleWorkbenchTool: (tool: WorkbenchTool) => void
  selectWorkbenchTab: (tabId: string) => void
  selectWorkbenchTool: (tool: WorkbenchTool) => void
  closeWorkbenchTab: (tabId: string) => void
  closeWorkbenchTool: (tool: WorkbenchTool) => void
  updateWorkbenchTab: (tabId: string, patch: Pick<WorkbenchTabOptions, 'title'>) => void
  closeActiveWorkbenchTool: () => void
  toggleWorkbench: () => void
  closeWorkbench: () => void
  showWorkbenchLauncher: () => void
  toggleWorkbenchMaximized: () => void
  toggleWiki: () => void
  toggleScheduler: () => void
  togglePullRequests: () => void
  openGitChanges: () => void
  setGitWorkspaceView: (view: GitWorkspaceView) => void
  toggleBrowser: () => void
  toggleTerminal: () => void
  closeWiki: () => void
  closeScheduler: () => void
  closeBrowser: () => void
  closeTerminal: () => void
  toggleSidebarCollapsed: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setSidebarOverlay: (overlay: boolean) => void
  setSidebarResizing: (resizing: boolean) => void
  setSidebarWidth: (width: number) => void
  resetSidebarWidth: () => void
  openSettings: (path?: string, search?: Record<string, string>) => void
  closeSettings: () => void
  navigateSettings: (path: string, search?: Record<string, string>) => void
  openGuidelines: (topicId?: string | null) => void
  closeGuidelines: () => void
  requestSideChat: (sessionId: string) => void
  clearSideChatRequest: () => void
  requestWorkspaceFile: (sessionId: string, path: string) => void
  clearWorkspaceFileRequest: (requestId?: number) => void
  requestEasdChat: (request: Omit<EasdChatRequest, 'id'>) => void
  clearEasdChatRequest: (requestId?: number) => void
}

export const useUIStore = create<UIStore>()(
  immer((set) => ({
    workbenchTabs: [],
    activeWorkbenchTabId: null,
    activeWorkbenchTool: null,
    workbenchOpen: false,
    workbenchMaximized: false,
    pullRequestsScope: 'session',
    gitWorkspaceView: 'changes',
    createWorkbenchTab: (tool, options = {}) => set((state) => {
      if (tool === 'pull-requests') {
        state.pullRequestsScope = 'session'
        state.gitWorkspaceView = 'reviews'
      } else if (tool === 'source-control') {
        state.gitWorkspaceView = 'changes'
      }
      addOrActivateTool(state, tool, options, true)
    }),
    restoreWorkbenchTabs: (tool, tabs) => set((state) => {
      for (const options of tabs) {
        if (!options.id) continue
        const exists = state.workbenchTabs.some((tab) => tab.id === options.id)
        if (!exists) state.workbenchTabs.push(newWorkbenchTab(tool, options))
      }
    }),
    openWorkbenchTool: (tool, options = {}) => set((state) => {
      if (tool === 'pull-requests') {
        state.pullRequestsScope = 'session'
        state.gitWorkspaceView = 'reviews'
      } else if (tool === 'source-control') {
        state.gitWorkspaceView = 'changes'
      }
      addOrActivateTool(state, tool, options)
    }),
    toggleWorkbenchTool: (tool) => set((state) => {
      if (tool === 'pull-requests') {
        state.pullRequestsScope = 'session'
        state.gitWorkspaceView = 'reviews'
      } else if (tool === 'source-control') {
        state.gitWorkspaceView = 'changes'
      }
      toggleTool(state, tool)
    }),
    selectWorkbenchTab: (tabId) => set((state) => {
      const tab = state.workbenchTabs.find((item) => item.id === tabId)
      if (!tab) return
      activateTab(state, tab)
      state.workbenchOpen = true
    }),
    selectWorkbenchTool: (tool) => set((state) => {
      const tab = lastTabForTool(state.workbenchTabs, tool)
      if (!tab) return
      activateTab(state, tab)
      state.workbenchOpen = true
    }),
    closeWorkbenchTab: (tabId) => set((state) => {
      closeTab(state, tabId)
    }),
    closeWorkbenchTool: (tool) => set((state) => {
      closeTool(state, tool)
    }),
    updateWorkbenchTab: (tabId, patch) => set((state) => {
      const tab = state.workbenchTabs.find((item) => item.id === tabId)
      if (tab) Object.assign(tab, patch)
    }),
    closeActiveWorkbenchTool: () => set((state) => {
      if (state.activeWorkbenchTabId) {
        closeTab(state, state.activeWorkbenchTabId)
      }
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
      activateTab(state, undefined)
      state.workbenchMaximized = false
    }),
    toggleWorkbenchMaximized: () => set((state) => {
      if (state.activeWorkbenchTabId) {
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
      state.gitWorkspaceView = 'reviews'
      if (switchScopeOnly) return
      toggleTool(state, 'pull-requests')
    }),
    openGitChanges: () => set((state) => {
      state.pullRequestsScope = 'session'
      state.gitWorkspaceView = 'changes'
      addOrActivateTool(state, 'source-control')
    }),
    setGitWorkspaceView: (view) => set((state) => {
      state.gitWorkspaceView = view
    }),
    toggleBrowser: () => set((state) => { toggleTool(state, 'browser') }),
    toggleTerminal: () => set((state) => { toggleTool(state, 'terminal') }),
    closeWiki: () => set((state) => { closeTool(state, 'wiki') }),
    closeScheduler: () => set((state) => { closeTool(state, 'scheduler') }),
    closeBrowser: () => set((state) => { closeTool(state, 'browser') }),
    closeTerminal: () => set((state) => { closeTool(state, 'terminal') }),
    sidebarCollapsed: loadSidebarCollapsed(),
    sidebarOverlay: false,
    sidebarResizing: false,
    sidebarWidth: loadSidebarWidth(),
    toggleSidebarCollapsed: () => set((state) => {
      state.sidebarCollapsed = !state.sidebarCollapsed
      persistSidebarCollapsed(state.sidebarCollapsed)
    }),
    setSidebarCollapsed: (collapsed) => set((state) => {
      state.sidebarCollapsed = collapsed
      persistSidebarCollapsed(collapsed)
    }),
    setSidebarOverlay: (overlay) => set((state) => {
      state.sidebarOverlay = overlay
    }),
    setSidebarResizing: (resizing) => set((state) => {
      state.sidebarResizing = resizing
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
    guidelinesOpen: false,
    guidelinesTopicId: null,
    openGuidelines: (topicId = null) => set((state) => {
      state.guidelinesOpen = true
      state.guidelinesTopicId = topicId ?? null
    }),
    closeGuidelines: () => set((state) => {
      state.guidelinesOpen = false
      state.guidelinesTopicId = null
    }),
    sideChatRequest: null,
    requestSideChat: (sessionId) => set((state) => { state.sideChatRequest = sessionId }),
    clearSideChatRequest: () => set((state) => { state.sideChatRequest = null }),
    workspaceFileRequest: null,
    requestWorkspaceFile: (sessionId, path) => set((state) => {
      workspaceFileRequestSequence += 1
      state.workspaceFileRequest = {
        id: workspaceFileRequestSequence,
        sessionId,
        path,
      }
      addOrActivateTool(state, 'files')
    }),
    clearWorkspaceFileRequest: (requestId) => set((state) => {
      if (requestId !== undefined && state.workspaceFileRequest?.id !== requestId) return
      state.workspaceFileRequest = null
    }),
    easdChatRequest: null,
    requestEasdChat: (request) => set((state) => {
      easdChatRequestSequence += 1
      state.easdChatRequest = { id: easdChatRequestSequence, ...request }
    }),
    clearEasdChatRequest: (requestId) => set((state) => {
      if (requestId !== undefined && state.easdChatRequest?.id !== requestId) return
      state.easdChatRequest = null
    }),
  }))
)
