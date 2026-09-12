import { afterEach, describe, expect, it, vi } from 'vitest'

import { notifyCodingWorkspacesChanged, removeCodingWorkspace, saveCodingWorkspace } from './workspace'

/**
 * The coding sidebar refetches its Projects + Workspaces snapshot when this
 * event fires. It is the only channel callers without a QueryClient have —
 * a renamed event would silently stop the refresh, which is how a freshly
 * opened repository came to stay missing from the sidebar.
 */
const EVENT = 'coding-workspaces-changed'

function listen() {
  const handler = vi.fn()
  window.addEventListener(EVENT, handler)
  return {
    handler,
    stop: () => window.removeEventListener(EVENT, handler),
  }
}

afterEach(() => {
  localStorage.clear()
})

describe('coding workspace change notifications', () => {
  it('announces a change on the channel the sidebar listens to', () => {
    const { handler, stop } = listen()

    notifyCodingWorkspacesChanged()

    expect(handler).toHaveBeenCalledTimes(1)
    stop()
  })

  it('announces saving a workspace', () => {
    const { handler, stop } = listen()

    saveCodingWorkspace('/repos/demo')

    expect(handler).toHaveBeenCalledTimes(1)
    stop()
  })

  it('announces removing a workspace', () => {
    saveCodingWorkspace('/repos/demo')
    const { handler, stop } = listen()

    removeCodingWorkspace('/repos/demo')

    expect(handler).toHaveBeenCalledTimes(1)
    stop()
  })
})
