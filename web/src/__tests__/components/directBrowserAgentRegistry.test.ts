import { describe, expect, it, vi } from 'vitest'

import {
  runDirectBrowserSessionCommand,
  type DirectBrowserSurfaceRegistration,
} from '@/components/BrowserViewer/directBrowserAgentRegistry'

function surface(
  instanceId: string,
  order: number,
  url: string,
  active = false,
): DirectBrowserSurfaceRegistration {
  return {
    instanceId,
    order,
    isActive: () => active,
    getTab: () => ({ url, title: instanceId }),
    execute: vi.fn(async (action) => action === 'status'
      ? { url, title: instanceId, readyState: 'complete' }
      : `${instanceId}:${action}`),
    activate: vi.fn(),
    close: vi.fn(),
  }
}

describe('direct browser session registry routing', () => {
  it('lists every workbench browser surface in stable order', async () => {
    const first = surface('one', 1, 'https://one.test')
    const second = surface('two', 2, 'https://two.test', true)

    await expect(runDirectBrowserSessionCommand(
      [second, first],
      'get_tabs',
      {},
    )).resolves.toBe([
      '[0] https://one.test',
      '[1]* https://two.test',
    ].join('\n'))
  })

  it('routes active commands and tab lifecycle actions to the selected surface', async () => {
    const first = surface('one', 1, 'https://one.test')
    const second = surface('two', 2, 'https://two.test', true)

    await expect(runDirectBrowserSessionCommand([first, second], 'snapshot', {}))
      .resolves.toBe('two:snapshot')
    await runDirectBrowserSessionCommand([first, second], 'switch_tab', { index: 0 })
    expect(first.activate).toHaveBeenCalledOnce()
    await runDirectBrowserSessionCommand([first, second], 'close_tab', { index: 1 })
    expect(second.execute).toHaveBeenCalledWith('stop', {})
    expect(second.close).toHaveBeenCalledOnce()
  })

  it('merges session-wide tabs into status', async () => {
    const first = surface('one', 1, 'https://one.test', true)
    const second = surface('two', 2, 'https://two.test')

    const status = await runDirectBrowserSessionCommand([first, second], 'status', {})
    expect(status).toMatchObject({
      url: 'https://one.test',
      tabs: [
        { index: 0, url: 'https://one.test', active: true },
        { index: 1, url: 'https://two.test', active: false },
      ],
    })
  })
})
