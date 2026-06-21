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
  toggleWiki: () => void
  toggleScheduler: () => void
  toggleAgentCapabilities: () => void
  closeWiki: () => void
  closeScheduler: () => void
  closeAgentCapabilities: () => void
}

export const useUIStore = create<UIStore>()(
  immer((set) => ({
    wikiOpen: false,
    schedulerOpen: false,
    agentCapabilitiesOpen: false,
    toggleWiki: () => set((state) => {
      const nextOpen = !state.wikiOpen
      state.wikiOpen = nextOpen
      if (nextOpen) {
        state.schedulerOpen = false
        state.agentCapabilitiesOpen = false
      }
    }),
    toggleScheduler: () => set((state) => {
      const nextOpen = !state.schedulerOpen
      state.schedulerOpen = nextOpen
      if (nextOpen) {
        state.wikiOpen = false
        state.agentCapabilitiesOpen = false
      }
    }),
    toggleAgentCapabilities: () => set((state) => {
      const nextOpen = !state.agentCapabilitiesOpen
      state.agentCapabilitiesOpen = nextOpen
      if (nextOpen) {
        state.wikiOpen = false
        state.schedulerOpen = false
      }
    }),
    closeWiki: () => set((state) => { state.wikiOpen = false }),
    closeScheduler: () => set((state) => { state.schedulerOpen = false }),
    closeAgentCapabilities: () => set((state) => { state.agentCapabilitiesOpen = false }),
  }))
)
