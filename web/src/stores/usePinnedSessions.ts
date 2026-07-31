/**
 * usePinnedSessions — client-side set of session ids the user pinned in a
 * mode sidebar. Persisted to localStorage as a JSON array, most-recently-
 * pinned first (that order drives the work sidebar's "Pinned" section).
 *
 * Mirrors the load/persist idiom of ``useUIStore`` (sidebarCollapsed):
 * module-level loaders, writes inside the actions, storage failures
 * swallowed. Zustand + immer, no derived selectors.
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { STORAGE_KEYS } from '@/lib/storage-keys'

function loadPinnedIds(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.pinnedSessions)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((id): id is string => typeof id === 'string')
  } catch {
    return []
  }
}

function persistPinnedIds(ids: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEYS.pinnedSessions, JSON.stringify(ids))
  } catch {
    // ignore storage failures
  }
}

interface PinnedSessionsStore {
  /** Most-recently-pinned first. */
  pinnedIds: string[]
  togglePin: (id: string) => void
  isPinned: (id: string) => boolean
}

export const usePinnedSessions = create<PinnedSessionsStore>()(
  immer((set, get) => ({
    pinnedIds: loadPinnedIds(),
    togglePin: (id) => set((state) => {
      const index = state.pinnedIds.indexOf(id)
      if (index >= 0) state.pinnedIds.splice(index, 1)
      else state.pinnedIds.unshift(id)
      persistPinnedIds(state.pinnedIds)
    }),
    isPinned: (id) => get().pinnedIds.includes(id),
  }))
)
