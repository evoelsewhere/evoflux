/**
 * Workbench tabs belong to a session.
 *
 * They used to be one global list, which broke two ways at once. A
 * terminal tab opened in one session stayed on screen in the next and
 * reconnected under the new session id carrying the old tab's terminal
 * id — the backend answers that by spawning a second, unrelated shell.
 * The workaround was to close the terminal, browser and side chat on
 * every switch, which is why none of them survived leaving a session.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import {
  sessionHasWorkbenchTool,
  sessionWorkbenchTabs,
  shouldMountWorkbenchTab,
  useUIStore,
} from '@/stores/useUIStore'
import type { WorkbenchTab, WorkbenchTool } from '@/stores/useUIStore'

const store = () => useUIStore.getState()
const visible = () => sessionWorkbenchTabs(useUIStore.getState())

describe('workbench tabs are scoped to their session', () => {
  beforeEach(() => {
    useUIStore.setState((state) => {
      state.workbenchTabs = []
      state.activeWorkbenchTabId = null
      state.activeWorkbenchTool = null
      state.workbenchSessionId = null
      state._activeTabBySession = {}
      state.workbenchOpen = false
      state.workbenchMaximized = false
    })
  })

  it('hides another session tabs and brings them back', () => {
    store().setWorkbenchSession('session-a')
    store().openWorkbenchTool('terminal')
    expect(visible().map((tab) => tab.tool)).toEqual(['terminal'])

    store().setWorkbenchSession('session-b')
    expect(visible()).toEqual([])
    expect(sessionHasWorkbenchTool(useUIStore.getState(), 'terminal')).toBe(false)

    store().setWorkbenchSession('session-a')
    expect(visible().map((tab) => tab.tool)).toEqual(['terminal'])
  })

  it('keeps each session tab, so neither is destroyed by a switch', () => {
    store().setWorkbenchSession('session-a')
    store().openWorkbenchTool('terminal')
    store().setWorkbenchSession('session-b')
    store().openWorkbenchTool('terminal')

    // Both still exist; only one is on screen.
    expect(store().workbenchTabs).toHaveLength(2)
    expect(visible()).toHaveLength(1)
    const ids = store().workbenchTabs.map((tab) => tab.id)
    expect(new Set(ids).size).toBe(2)
  })

  it('opens a fresh tab rather than adopting another session one', () => {
    store().setWorkbenchSession('session-a')
    store().openWorkbenchTool('browser')
    const first = visible()[0]?.id

    store().setWorkbenchSession('session-b')
    store().openWorkbenchTool('browser')
    const second = visible()[0]?.id

    expect(first).toBeDefined()
    expect(second).toBeDefined()
    expect(second).not.toBe(first)
  })

  it('remembers which tab a session was looking at', () => {
    store().setWorkbenchSession('session-a')
    store().openWorkbenchTool('terminal')
    store().openWorkbenchTool('browser')
    const browserTab = store().activeWorkbenchTabId

    store().setWorkbenchSession('session-b')
    store().setWorkbenchSession('session-a')
    expect(store().activeWorkbenchTabId).toBe(browserTab)
  })

  it('leaves session-independent tools in place across a switch', () => {
    store().setWorkbenchSession('session-a')
    store().openWorkbenchTool('plugins')
    store().setWorkbenchSession('session-b')

    // Plugin Center means the same thing in every session.
    expect(sessionHasWorkbenchTool(useUIStore.getState(), 'plugins')).toBe(true)
    expect(store().workbenchTabs).toHaveLength(1)
  })

  it('closing a tool only closes this session copy', () => {
    store().setWorkbenchSession('session-a')
    store().openWorkbenchTool('terminal')
    store().setWorkbenchSession('session-b')
    store().openWorkbenchTool('terminal')

    store().closeWorkbenchTool('terminal')
    expect(visible()).toEqual([])

    store().setWorkbenchSession('session-a')
    expect(visible().map((tab) => tab.tool)).toEqual(['terminal'])
  })

  it('never activates a tab belonging to another session', () => {
    store().setWorkbenchSession('session-a')
    store().openWorkbenchTool('terminal')
    const foreign = store().activeWorkbenchTabId

    store().setWorkbenchSession('session-b')
    expect(store().activeWorkbenchTabId).not.toBe(foreign)
    expect(store().activeWorkbenchTabId).toBeNull()
  })

  describe('restoring from the server', () => {
    it('adopts the server list for this session', () => {
      store().setWorkbenchSession('session-a')
      store().restoreWorkbenchTabs('terminal', [{ id: 'tid-1' }, { id: 'tid-2' }])
      expect(visible().map((tab) => tab.id)).toEqual(['tid-1', 'tid-2'])
    })

    it('drops a tab the server no longer reports', () => {
      store().setWorkbenchSession('session-a')
      store().restoreWorkbenchTabs('terminal', [{ id: 'tid-1' }, { id: 'tid-2' }])
      store().restoreWorkbenchTabs('terminal', [{ id: 'tid-1' }])
      expect(visible().map((tab) => tab.id)).toEqual(['tid-1'])
    })

    it('does not disturb another session terminals', () => {
      store().setWorkbenchSession('session-a')
      store().restoreWorkbenchTabs('terminal', [{ id: 'a-1' }])
      store().setWorkbenchSession('session-b')
      store().restoreWorkbenchTabs('terminal', [{ id: 'b-1' }])

      expect(visible().map((tab) => tab.id)).toEqual(['b-1'])
      store().setWorkbenchSession('session-a')
      expect(visible().map((tab) => tab.id)).toEqual(['a-1'])
    })
  })
})

/**
 * Which foreign tabs stay mounted.
 *
 * Keeping every session's tab mounted preserved their live state but
 * released nothing: visiting five sessions with a terminal each left five
 * xterm instances and five open sockets alive at once, measured in the
 * browser. Only the browser tab genuinely cannot be rebuilt — its page
 * lives in a native WebView with no replay — while a terminal's PTY
 * outlives the socket and `terminal_ws` replays its scrollback on
 * reconnect, which the browser test confirmed end to end.
 */
describe('mounting foreign tabs', () => {
  const tab = (tool: WorkbenchTool, sessionId: string | null): WorkbenchTab =>
    ({ id: `${tool}-${sessionId}`, tool, sessionId })

  it('keeps a browser from another session mounted', () => {
    expect(shouldMountWorkbenchTab(tab('browser', 'other'), 'current')).toBe(true)
  })

  it('lets another session terminal go', () => {
    expect(shouldMountWorkbenchTab(tab('terminal', 'other'), 'current')).toBe(false)
  })

  it('mounts this session own tabs whatever the tool', () => {
    for (const tool of ['terminal', 'browser', 'side-chat', 'files'] as const) {
      expect(shouldMountWorkbenchTab(tab(tool, 'current'), 'current')).toBe(true)
    }
  })

  it('mounts session-independent tabs', () => {
    expect(shouldMountWorkbenchTab(tab('plugins', null), 'current')).toBe(true)
  })
})
