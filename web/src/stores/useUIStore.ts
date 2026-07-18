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
  browserOpen: boolean
  terminalOpen: boolean
  settingsOpen: boolean
  settingsPath: string
  settingsSearch: Record<string, string>
  toggleWiki: () => void
  toggleScheduler: () => void
  toggleBrowser: () => void
  toggleTerminal: () => void
  closeWiki: () => void
  closeScheduler: () => void
  closeBrowser: () => void
  closeTerminal: () => void
  openSettings: (path?: string, search?: Record<string, string>) => void
  closeSettings: () => void
  navigateSettings: (path: string, search?: Record<string, string>) => void
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
      }
    }),
    // The terminal is a bottom dock, not a full-screen overlay — it can sit
    // open alongside wiki/scheduler/browser, so toggling it doesn't close them.
    toggleTerminal: () => set((state) => { state.terminalOpen = !state.terminalOpen }),
    closeWiki: () => set((state) => { state.wikiOpen = false }),
    closeScheduler: () => set((state) => { state.schedulerOpen = false }),
    closeBrowser: () => set((state) => { state.browserOpen = false }),
    closeTerminal: () => set((state) => { state.terminalOpen = false }),
    settingsOpen: false,
    settingsPath: '',
    settingsSearch: {},
    openSettings: (path = '', search = {}) => set((state) => { state.settingsOpen = true; state.settingsPath = path; state.settingsSearch = search }),
    closeSettings: () => set((state) => { state.settingsOpen = false }),
    navigateSettings: (path: string, search = {}) => set((state) => { state.settingsPath = path; state.settingsSearch = search }),
  }))
)
