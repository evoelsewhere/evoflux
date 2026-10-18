import { describe, expect, it, vi } from 'vitest'

import {
  directBrowserSessionSurfaces,
  registerDirectBrowserSurface,
  runDirectBrowserSessionCommand,
  type DirectBrowserSurfaceRegistration,
  type DirectBrowserSurfaceTab,
} from '@/components/BrowserViewer/directBrowserAgentRegistry'

function surface(
  instanceId: string,
  order: number,
  tabs: DirectBrowserSurfaceTab[],
  activeIndex = 0,
): DirectBrowserSurfaceRegistration {
  return {
    instanceId,
    order,
    isActive: () => activeIndex >= 0,
    getTab: () => tabs[activeIndex] ?? null,
    getTabs: () =>
      tabs.map((tab, index) => ({ ...tab, active: index === activeIndex })),
    selectTab: vi.fn(),
    closeTab: vi.fn(),
    unavailableReason: () => '',
    execute: vi.fn(async (action: string) => {
      return action === 'status'
        ? {
            url: tabs[activeIndex]?.url ?? '',
            title: tabs[activeIndex]?.title ?? '',
            readyState: 'complete',
          }
        : `${instanceId}:${action}`
    }),
    activate: vi.fn(),
    close: vi.fn(),
  }
}

describe('direct browser session registry routing', () => {
  it('lists the session tab list the PiP and panel share, in tab order', async () => {
    const one = surface('session', 1, [
      { url: 'https://one.test', title: 'one' },
      { url: 'https://two.test', title: 'two' },
    ])

    await expect(
      runDirectBrowserSessionCommand([one], 'get_tabs', {}),
    ).resolves.toBe(['[0]* https://one.test', '[1] https://two.test'].join('\n'))
  })

  it('routes tab lifecycle actions by index into the shared tab list', async () => {
    const one = surface(
      'session',
      1,
      [{ url: 'https://one.test' }, { url: 'https://two.test' }],
      1,
    )

    await runDirectBrowserSessionCommand([one], 'switch_tab', { index: 0 })
    expect(one.selectTab).toHaveBeenCalledWith(0)
    await runDirectBrowserSessionCommand([one], 'close_tab', { index: 1 })
    expect(one.execute).toHaveBeenCalledWith('stop', {})
    expect(one.closeTab).toHaveBeenCalledWith(1)
  })

  it('routes active commands to the session surface and merges tabs into status', async () => {
    const one = surface(
      'session',
      1,
      [{ url: 'https://one.test' }, { url: 'https://two.test' }],
    )

    await expect(
      runDirectBrowserSessionCommand([one], 'snapshot', {}),
    ).resolves.toBe('session:snapshot')
    const status = await runDirectBrowserSessionCommand([one], 'status', {})
    expect(status).toMatchObject({
      url: 'https://one.test',
      tabs: [
        { index: 0, url: 'https://one.test', active: true },
        { index: 1, url: 'https://two.test', active: false },
      ],
    })
  })

  it('keeps one surface per session while any view of it is registered', () => {
    const first = surface('session', 1, [{ url: 'https://one.test' }])
    const second = surface('session', 2, [{ url: 'https://one.test' }])

    const disposeFirst = registerDirectBrowserSurface('session-1', first, vi.fn())
    expect(directBrowserSessionSurfaces('session-1')).toHaveLength(1)

    // A second view (the panel docking beside the PiP) stands in as the
    // same session surface — the agent never sees each page twice.
    const disposeSecond = registerDirectBrowserSurface(
      'session-1',
      second,
      vi.fn(),
    )
    expect(directBrowserSessionSurfaces('session-1')).toEqual([second])

    disposeFirst()
    expect(directBrowserSessionSurfaces('session-1')).toEqual([second])

    disposeSecond()
    expect(directBrowserSessionSurfaces('session-1')).toEqual([])
  })
})
