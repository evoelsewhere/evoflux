import { beforeEach, describe, expect, it } from 'vitest'

import { useUIStore } from '@/stores/useUIStore'

describe('computer app preview cards', () => {
  beforeEach(() => {
    useUIStore.setState((state) => {
      state.computerPipSessionIds = []
      state.browserPipSessionIds = []
    })
  })

  it('opens one card per session and keeps them independent of browser cards', () => {
    useUIStore.getState().openComputerPip('session-a')
    useUIStore.getState().openComputerPip('session-b')
    useUIStore.getState().openComputerPip('session-a')

    expect(useUIStore.getState().computerPipSessionIds).toEqual(['session-a', 'session-b'])
    expect(useUIStore.getState().browserPipSessionIds).toEqual([])
  })

  it('brings a focused card to the top of the stack', () => {
    useUIStore.getState().openComputerPip('session-a')
    useUIStore.getState().openComputerPip('session-b')

    useUIStore.getState().focusComputerPip('session-a')

    expect(useUIStore.getState().computerPipSessionIds).toEqual(['session-b', 'session-a'])
  })

  it('closes one card or all of them', () => {
    useUIStore.getState().openComputerPip('session-a')
    useUIStore.getState().openComputerPip('session-b')

    useUIStore.getState().closeComputerPip('session-a')
    expect(useUIStore.getState().computerPipSessionIds).toEqual(['session-b'])

    useUIStore.getState().closeComputerPip()
    expect(useUIStore.getState().computerPipSessionIds).toEqual([])
  })
})
