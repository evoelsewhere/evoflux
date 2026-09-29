import { afterEach, describe, expect, it, vi } from 'vitest'

import { notifyCodingWorkspacesChanged } from './workspace'

/**
 * The coding sidebar refetches its projects snapshot when this event fires.
 * It is the only channel callers without a QueryClient have — a renamed
 * event would silently stop the refresh.
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
})
