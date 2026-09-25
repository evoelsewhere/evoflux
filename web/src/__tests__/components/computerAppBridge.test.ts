import { beforeEach, describe, expect, it, vi } from 'vitest'

import { runComputerAppCommand } from '@/components/ComputerAppViewer/computerAppBridge'
import { useUIStore } from '@/stores/useUIStore'

const desktop = vi.hoisted(() => ({ stopped: false, invoke: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: desktop.invoke }))

describe('runComputerAppCommand', () => {
  beforeEach(() => {
    desktop.invoke.mockReset()
    desktop.invoke.mockImplementation(async (_command: string, args: { action: string }) => {
      if (args.action === 'attach') throw new Error('The user stopped Computer App Control in this chat.')
      if (args.action === 'status') return { attached: false, stopped: desktop.stopped }
      return {}
    })
    useUIStore.setState({ computerPipSessionIds: [] })
  })

  it('shows the stopped card when an attach is refused after Stop', async () => {
    desktop.stopped = true

    const reply = await runComputerAppCommand('chat-1', 'attach', { window_id: 7 })

    expect(reply.ok).toBe(false)
    expect(useUIStore.getState().computerPipSessionIds).toContain('chat-1')
  })

  it('leaves the card closed when an attach fails for another reason', async () => {
    desktop.stopped = false

    await runComputerAppCommand('chat-1', 'attach', { window_id: 7 })

    expect(useUIStore.getState().computerPipSessionIds).not.toContain('chat-1')
  })
})
