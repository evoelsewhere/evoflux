import { describe, expect, it, vi } from 'vitest'

import {
  activeDirectBrowserSurface,
  claimantForTab,
  disposeDirectBrowserSession,
  disposeDirectBrowserSessionIfAbandoned,
  disposeDirectBrowserSessionIfUnused,
  getDirectBrowserSession,
  hasLiveBrowserTabs,
  MAX_DETACHED_BROWSER_SESSIONS,
  registerDirectBrowserSurfaceSlot,
  setDirectBrowserActiveTab,
  subscribeDirectBrowserSession,
  unregisterDirectBrowserSurfaceSlot,
  updateDirectBrowserSurfaceSlot,
} from '@/components/BrowserViewer/directBrowserSessionStore'

function seedTabs(sessionId: string, count: number) {
  const session = getDirectBrowserSession(sessionId)
  session.tabs = Array.from({ length: count }, (_unused, index) => ({
    id: `tab-${index + 1}`,
    label: `db-${index + 1}`,
    url: `https://page-${index + 1}.test`,
  }))
  session.activeTabId = session.tabs[0]?.id ?? null
  return session
}

describe('direct browser session store', () => {
  it('keeps one browser per session across surfaces', () => {
    const first = getDirectBrowserSession('session-shared')
    const second = getDirectBrowserSession('session-shared')
    const other = getDirectBrowserSession('session-other')

    expect(second).toBe(first)
    expect(other).not.toBe(first)

    first.tabs = [{ id: 'tab-1', label: 'db-1', url: 'https://one.test' }]
    expect(second.tabs).toHaveLength(1)
    expect(hasLiveBrowserTabs('session-shared')).toBe(true)
    expect(hasLiveBrowserTabs('session-missing')).toBe(false)
  })

  it('notifies every surface when one of them changes the browser', () => {
    const session = getDirectBrowserSession('session-notify')
    const pip = vi.fn()
    const panel = vi.fn()
    const unsubscribePip = subscribeDirectBrowserSession('session-notify', pip)
    const unsubscribePanel = subscribeDirectBrowserSession('session-notify', panel)

    setDirectBrowserActiveTab('session-notify', 'tab-9')

    expect(pip).toHaveBeenCalled()
    expect(panel).toHaveBeenCalled()
    expect(session.activeTabId).toBe('tab-9')

    unsubscribePip()
    unsubscribePanel()
    setDirectBrowserActiveTab('session-notify', 'tab-8')
    expect(pip).toHaveBeenCalledTimes(1)
  })

  it('gives the panel priority over the PiP while both are visible', () => {
    const session = seedTabs('session-arbitration', 2)
    registerDirectBrowserSurfaceSlot('session-arbitration', {
      id: 'pip',
      kind: 'pip',
      visible: true,
      boundTabId: null,
    })
    expect(activeDirectBrowserSurface(session)?.id).toBe('pip')
    expect(claimantForTab(session, 'tab-1')).toBe('pip')

    registerDirectBrowserSurfaceSlot('session-arbitration', {
      id: 'panel:workbench-1',
      kind: 'panel',
      visible: true,
      boundTabId: 'tab-1',
    })
    expect(activeDirectBrowserSurface(session)?.id).toBe('panel:workbench-1')
    // Docking never fights over a WebView: the panel shows its bound page,
    // the PiP only the page the session's selection is on.
    expect(claimantForTab(session, 'tab-1')).toBe('panel:workbench-1')
    expect(claimantForTab(session, 'tab-2')).toBeNull()

    setDirectBrowserActiveTab('session-arbitration', 'tab-2')
    expect(claimantForTab(session, 'tab-2')).toBe('pip')
    expect(claimantForTab(session, 'tab-1')).toBe('panel:workbench-1')
  })

  it('hides a page no surface is showing', () => {
    const session = seedTabs('session-unclaimed', 1)
    registerDirectBrowserSurfaceSlot('session-unclaimed', {
      id: 'panel:workbench-1',
      kind: 'panel',
      visible: false,
      boundTabId: 'tab-1',
    })

    expect(claimantForTab(session, 'tab-1')).toBeNull()
  })

  it('follows the shared selection when a surface becomes visible', () => {
    const session = seedTabs('session-visible', 2)
    session.activeTabId = 'tab-2'
    registerDirectBrowserSurfaceSlot('session-visible', {
      id: 'panel:workbench-1',
      kind: 'panel',
      visible: false,
      boundTabId: 'tab-1',
    })

    updateDirectBrowserSurfaceSlot('session-visible', 'panel:workbench-1', {
      visible: true,
    })
    // The hook pushes its bound page as the shared selection on activation;
    // the store keeps whichever page is selected claimable by its surface.
    expect(claimantForTab(session, 'tab-1')).toBe('panel:workbench-1')
  })

  it('does not dispose a session that still has pages when a surface unmounts', () => {
    const session = seedTabs('session-undock', 1)
    session.webviews.set('tab-1', { close: vi.fn() } as never)

    disposeDirectBrowserSessionIfAbandoned('session-undock')

    expect(hasLiveBrowserTabs('session-undock')).toBe(true)
    expect(session.webviews.size).toBe(1)
  })

  it('disposes a session once its last page is closed', () => {
    const session = getDirectBrowserSession('session-empty')
    session.tabs = []
    const close = vi.fn()
    session.webviews.set('tab-1', { close } as never)

    disposeDirectBrowserSessionIfAbandoned('session-empty')

    expect(close).toHaveBeenCalled()
    expect(session.webviews.size).toBe(0)
  })

  it('ends the browser only on an explicit PiP close with no panel open', () => {
    const session = seedTabs('session-explicit', 1)
    const close = vi.fn()
    session.webviews.set('tab-1', { close } as never)

    registerDirectBrowserSurfaceSlot('session-explicit', {
      id: 'panel:workbench-1',
      kind: 'panel',
      visible: true,
      boundTabId: 'tab-1',
    })
    disposeDirectBrowserSessionIfUnused('session-explicit')
    // The panel is still showing the session; the pages survive.
    expect(close).not.toHaveBeenCalled()
    expect(hasLiveBrowserTabs('session-explicit')).toBe(true)

    unregisterDirectBrowserSurfaceSlot('session-explicit', 'panel:workbench-1')
    disposeDirectBrowserSessionIfUnused('session-explicit')
    expect(close).toHaveBeenCalled()
    expect(hasLiveBrowserTabs('session-explicit')).toBe(false)
  })
})

describe('detached browser sessions', () => {
  function detach(sessionId: string, at: number) {
    vi.setSystemTime(at)
    const session = seedTabs(sessionId, 1)
    const close = vi.fn()
    session.webviews.set('tab-1', { close } as never)
    registerDirectBrowserSurfaceSlot(sessionId, {
      id: 'panel:w',
      kind: 'panel',
      visible: true,
      boundTabId: 'tab-1',
    })
    unregisterDirectBrowserSurfaceSlot(sessionId, 'panel:w')
    return { session, close }
  }

  it('closes the longest-detached sessions beyond the cap, keeping the newest', () => {
    vi.useFakeTimers()
    const ids = Array.from(
      { length: MAX_DETACHED_BROWSER_SESSIONS + 1 },
      (_unused, index) => `detached-${index}`,
    )
    try {
      const detached = ids.map((id, index) => detach(id, 1_000 * (index + 1)))
      const [oldest, ...kept] = detached

      expect(oldest.close).toHaveBeenCalled()
      expect(hasLiveBrowserTabs(ids[0])).toBe(false)
      for (const entry of kept) {
        expect(entry.close).not.toHaveBeenCalled()
        expect(entry.session.webviews.size).toBe(1)
      }
    } finally {
      for (const id of ids) disposeDirectBrowserSession(id)
      vi.useRealTimers()
    }
  })

  it('does not close a session that is shown again', () => {
    vi.useFakeTimers()
    try {
      const shown = detach('shown-1', 100)
      registerDirectBrowserSurfaceSlot('shown-1', {
        id: 'pip',
        kind: 'pip',
        visible: true,
        boundTabId: 'tab-1',
      })
      for (let i = 0; i < MAX_DETACHED_BROWSER_SESSIONS + 2; i += 1) {
        detach(`shown-other-${i}`, 200 + i)
      }

      expect(shown.close).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('closes a session browser outright when its chat is deleted', () => {
    const session = seedTabs('deleted-chat', 1)
    const close = vi.fn()
    session.webviews.set('tab-1', { close } as never)

    disposeDirectBrowserSession('deleted-chat')

    expect(close).toHaveBeenCalled()
    expect(hasLiveBrowserTabs('deleted-chat')).toBe(false)
  })
})
