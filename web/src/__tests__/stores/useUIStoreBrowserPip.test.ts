import { beforeEach, describe, expect, it } from 'vitest'

import { useUIStore } from '@/stores/useUIStore'

describe('browser agent previews', () => {
  beforeEach(() => {
    useUIStore.setState((state) => {
      state.browserPipSessionIds = []
    })
  })

  it('keeps multiple sessions open without duplicating one session', () => {
    useUIStore.getState().openBrowserPip('session-a')
    useUIStore.getState().openBrowserPip('session-b')
    useUIStore.getState().openBrowserPip('session-a')

    expect(useUIStore.getState().browserPipSessionIds).toEqual([
      'session-a',
      'session-b',
    ])
  })

  it('closes only the requested preview', () => {
    useUIStore.getState().openBrowserPip('session-a')
    useUIStore.getState().openBrowserPip('session-b')

    useUIStore.getState().closeBrowserPip('session-a')

    expect(useUIStore.getState().browserPipSessionIds).toEqual(['session-b'])
  })

  it('brings a stacked preview to the front', () => {
    useUIStore.getState().openBrowserPip('session-a')
    useUIStore.getState().openBrowserPip('session-b')

    useUIStore.getState().focusBrowserPip('session-a')

    expect(useUIStore.getState().browserPipSessionIds).toEqual([
      'session-b',
      'session-a',
    ])
  })
})
