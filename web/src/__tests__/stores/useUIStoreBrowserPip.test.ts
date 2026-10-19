import { beforeEach, describe, expect, it } from 'vitest'

import { getDirectBrowserSession } from '@/components/BrowserViewer/directBrowserSessionStore'
import { useUIStore } from '@/stores/useUIStore'

describe('browser agent previews', () => {
  beforeEach(() => {
    useUIStore.setState((state) => {
      state.browserPipSessionIds = []
      state.workbenchTabs = []
      state.activeWorkbenchTabId = null
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

  it('undocks to the preview when the panel closes and pages are still live', () => {
    const session = getDirectBrowserSession('session-undock')
    session.tabs = [{ id: 'tab-1', label: 'db-1', url: 'https://example.test' }]
    useUIStore.setState((state) => {
      state.workbenchSessionId = 'session-undock'
      state.workbenchTabs = [
        { id: 'browser-1', tool: 'browser', sessionId: 'session-undock' },
      ]
      state.activeWorkbenchTabId = 'browser-1'
    })

    useUIStore.getState().closeWorkbenchTab('browser-1')

    expect(useUIStore.getState().browserPipSessionIds).toEqual(['session-undock'])
  })

  it('stays docked while the session still has a browser panel open', () => {
    const session = getDirectBrowserSession('session-docked')
    session.tabs = [{ id: 'tab-1', label: 'db-1', url: 'https://example.test' }]
    useUIStore.setState((state) => {
      state.workbenchSessionId = 'session-docked'
      state.workbenchTabs = [
        { id: 'browser-1', tool: 'browser', sessionId: 'session-docked' },
        { id: 'browser-2', tool: 'browser', sessionId: 'session-docked' },
      ]
      state.activeWorkbenchTabId = 'browser-1'
    })

    useUIStore.getState().closeWorkbenchTab('browser-1')

    expect(useUIStore.getState().browserPipSessionIds).toEqual([])
  })

  it('does not undock a session with no live pages left', () => {
    getDirectBrowserSession('session-closed').tabs = []
    useUIStore.setState((state) => {
      state.workbenchSessionId = 'session-closed'
      state.workbenchTabs = [
        { id: 'browser-1', tool: 'browser', sessionId: 'session-closed' },
      ]
      state.activeWorkbenchTabId = 'browser-1'
    })

    useUIStore.getState().closeWorkbenchTab('browser-1')

    expect(useUIStore.getState().browserPipSessionIds).toEqual([])
  })

  it('undocks every session that keeps live pages when the browser closes', () => {
    const session = getDirectBrowserSession('session-tool')
    session.tabs = [{ id: 'tab-1', label: 'db-1', url: 'https://example.test' }]
    useUIStore.setState((state) => {
      state.workbenchSessionId = 'session-tool'
      state.workbenchTabs = [
        { id: 'browser-1', tool: 'browser', sessionId: 'session-tool' },
      ]
      state.activeWorkbenchTabId = 'browser-1'
    })

    useUIStore.getState().closeWorkbenchTool('browser')

    expect(useUIStore.getState().browserPipSessionIds).toEqual(['session-tool'])
    expect(useUIStore.getState().workbenchTabs).toEqual([])
  })
})
