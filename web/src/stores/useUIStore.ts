/**
 * useUIStore — tiny client-state store for UI panels that live above the
 * TeamChatView and were previously owned by ``Sidebar``. Lifting state to a
 * shared store lets shortcuts and command palette items coordinate modal
 * visibility from one path.
 *
 * Mirrors the size and shape of ``useToastStore`` — Zustand + immer, no
 * persistence, no derived selectors.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

interface UIStore {
  wikiOpen: boolean
  schedulerOpen: boolean
  agentCapabilitiesOpen: boolean
  browserOpen: boolean
  settingsOpen: boolean
  settingsPath: string
  settingsSearch: Record<string, string>
  toggleWiki: () => void
  toggleScheduler: () => void
  toggleAgentCapabilities: () => void
  toggleBrowser: () => void
  closeWiki: () => void
  closeScheduler: () => void
  closeAgentCapabilities: () => void
  closeBrowser: () => void
  openSettings: (path?: string, search?: Record<string, string>) => void
  closeSettings: () => void
  navigateSettings: (path: string, search?: Record<string, string>) => void
}

export const useUIStore = create<UIStore>()(
  immer((set) => ({
    wikiOpen: false,
    schedulerOpen: false,
    agentCapabilitiesOpen: false,
    browserOpen: false,
    toggleWiki: () => set((state) => {
      const nextOpen = !state.wikiOpen
      state.wikiOpen = nextOpen
      if (nextOpen) {
        state.schedulerOpen = false
        state.agentCapabilitiesOpen = false
        state.browserOpen = false
      }
    }),
    toggleScheduler: () => set((state) => {
      const nextOpen = !state.schedulerOpen
      state.schedulerOpen = nextOpen
      if (nextOpen) {
        state.wikiOpen = false
        state.agentCapabilitiesOpen = false
        state.browserOpen = false
      }
    }),
    toggleAgentCapabilities: () => set((state) => {
      const nextOpen = !state.agentCapabilitiesOpen
      state.agentCapabilitiesOpen = nextOpen
      if (nextOpen) {
        state.wikiOpen = false
        state.schedulerOpen = false
        state.browserOpen = false
      }
    }),
    toggleBrowser: () => set((state) => {
      const nextOpen = !state.browserOpen
      state.browserOpen = nextOpen
      if (nextOpen) {
        state.wikiOpen = false
        state.schedulerOpen = false
        state.agentCapabilitiesOpen = false
      }
    }),
    closeWiki: () => set((state) => { state.wikiOpen = false }),
    closeScheduler: () => set((state) => { state.schedulerOpen = false }),
    closeAgentCapabilities: () => set((state) => { state.agentCapabilitiesOpen = false }),
    closeBrowser: () => set((state) => { state.browserOpen = false }),
    settingsOpen: false,
    settingsPath: '',
    settingsSearch: {},
    openSettings: (path = '', search = {}) => set((state) => { state.settingsOpen = true; state.settingsPath = path; state.settingsSearch = search }),
    closeSettings: () => set((state) => { state.settingsOpen = false }),
    navigateSettings: (path: string, search = {}) => set((state) => { state.settingsPath = path; state.settingsSearch = search }),
  }))
)
