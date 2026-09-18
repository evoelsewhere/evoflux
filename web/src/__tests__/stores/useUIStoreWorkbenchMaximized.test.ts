/**
 * Maximize is a working posture, not per-tab state.
 *
 * The dock clears the flag whenever it has nothing to show, and at startup
 * the workbench is empty — so persisting "whatever the flag currently is"
 * wrote `false` over the remembered `true` before the first tab existed, and
 * a full-width browser never came back after a restart. Only an explicit
 * toggle is remembered; activation re-applies it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { STORAGE_KEYS } from '@/lib/storage-keys'

const MAXIMIZED_KEY = STORAGE_KEYS.panels.workbenchMaximized

async function freshStore(stored: string | null) {
  if (stored === null) localStorage.removeItem(MAXIMIZED_KEY)
  else localStorage.setItem(MAXIMIZED_KEY, stored)
  vi.resetModules()
  const { useUIStore } = await import('@/stores/useUIStore')
  return useUIStore
}

describe('workbench maximize is remembered across launches', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts docked and remembers being maximized', async () => {
    const store = await freshStore(null)
    store.getState().setWorkbenchSession('session-a')
    store.getState().openWorkbenchTool('browser')
    expect(store.getState().workbenchMaximized).toBe(false)

    store.getState().toggleWorkbenchMaximized()
    expect(store.getState().workbenchMaximized).toBe(true)
    expect(localStorage.getItem(MAXIMIZED_KEY)).toBe('true')
  })

  it('comes back maximized on the next launch, once there is a tab again', async () => {
    const store = await freshStore('true')
    // A launch starts with an empty workbench: nothing to maximize yet.
    expect(store.getState().workbenchMaximized).toBe(false)

    store.getState().setWorkbenchSession('session-a')
    store.getState().openWorkbenchTool('browser')
    expect(store.getState().workbenchMaximized).toBe(true)
  })

  it('does not let an automatic clear erase the remembered posture', async () => {
    const store = await freshStore('true')
    store.getState().setWorkbenchSession('session-a')
    store.getState().openWorkbenchTool('browser')

    store.getState().closeWorkbench()
    expect(store.getState().workbenchMaximized).toBe(false)
    expect(localStorage.getItem(MAXIMIZED_KEY)).toBe('true')

    store.getState().openWorkbenchTool('browser')
    expect(store.getState().workbenchMaximized).toBe(true)
  })

  it('forgets it once the user restores the panel', async () => {
    const store = await freshStore('true')
    store.getState().setWorkbenchSession('session-a')
    store.getState().openWorkbenchTool('browser')

    store.getState().toggleWorkbenchMaximized()
    expect(store.getState().workbenchMaximized).toBe(false)
    expect(localStorage.getItem(MAXIMIZED_KEY)).toBe('false')
  })
})
