import { beforeEach, describe, expect, it, vi } from 'vitest'

const CANONICAL_WIDTH_KEY = 'oa.sidebar.width'
const CODING_WIDTH_KEY = 'oa.codingSidebar.width'
const AIM_WIDTH_KEY = 'oa.aimSidebar.width'

async function loadFreshStore() {
  vi.resetModules()
  const { useUIStore } = await import('./useUIStore')
  return useUIStore as typeof useUIStore & {
    getState: () => ReturnType<typeof useUIStore.getState> & {
      sidebarWidth: number
      setSidebarWidth: (width: number) => void
      resetSidebarWidth: () => void
    }
  }
}

describe('shared sidebar width', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('prefers the existing Forge width and clamps it to the shared contract', async () => {
    localStorage.setItem(CANONICAL_WIDTH_KEY, '480')
    localStorage.setItem(CODING_WIDTH_KEY, '310')
    localStorage.setItem(AIM_WIDTH_KEY, '390')

    const store = await loadFreshStore()

    expect(store.getState().sidebarWidth).toBe(420)
    expect(localStorage.getItem(CANONICAL_WIDTH_KEY)).toBe('420')
  })

  it('migrates Coding before AIM when no valid Forge width exists', async () => {
    localStorage.setItem(CANONICAL_WIDTH_KEY, 'not-a-number')
    localStorage.setItem(CODING_WIDTH_KEY, '210')
    localStorage.setItem(AIM_WIDTH_KEY, '390')

    const store = await loadFreshStore()

    expect(store.getState().sidebarWidth).toBe(248)
    expect(localStorage.getItem(CANONICAL_WIDTH_KEY)).toBe('248')
  })

  it('falls back to AIM and then the 280px default', async () => {
    localStorage.setItem(AIM_WIDTH_KEY, '390')
    let store = await loadFreshStore()
    expect(store.getState().sidebarWidth).toBe(390)

    localStorage.clear()
    store = await loadFreshStore()
    expect(store.getState().sidebarWidth).toBe(280)
    expect(localStorage.getItem(CANONICAL_WIDTH_KEY)).toBe('280')
  })

  it('persists one clamped width for every sidebar remount', async () => {
    const store = await loadFreshStore()

    store.getState().setSidebarWidth(336)
    expect(store.getState().sidebarWidth).toBe(336)
    expect(localStorage.getItem(CANONICAL_WIDTH_KEY)).toBe('336')

    store.getState().setSidebarWidth(120)
    expect(store.getState().sidebarWidth).toBe(248)

    const remountedStore = await loadFreshStore()
    expect(remountedStore.getState().sidebarWidth).toBe(248)

    remountedStore.getState().resetSidebarWidth()
    expect(remountedStore.getState().sidebarWidth).toBe(280)
  })

  it('makes Browser and Terminal mutually exclusive with the newest panel winning', async () => {
    const store = await loadFreshStore()

    store.getState().toggleTerminal()
    expect(store.getState().terminalOpen).toBe(true)
    expect(store.getState().browserOpen).toBe(false)

    store.getState().toggleBrowser()
    expect(store.getState().browserOpen).toBe(true)
    expect(store.getState().terminalOpen).toBe(false)

    store.getState().toggleTerminal()
    expect(store.getState().terminalOpen).toBe(true)
    expect(store.getState().browserOpen).toBe(false)
  })
})
