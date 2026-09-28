import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ComputerAppPipHost } from '@/components/ComputerAppViewer/ComputerAppPipHost'

const desktop = vi.hoisted(() => ({
  frames: [] as Array<Record<string, unknown>>,
  invoke: vi.fn(),
  listen: vi.fn(),
}))

vi.mock('@tauri-apps/api/core', () => ({ invoke: desktop.invoke }))
vi.mock('@tauri-apps/api/event', () => ({ listen: desktop.listen }))

class DeferredImage {
  static instances: DeferredImage[] = []

  decoding: 'async' | 'auto' | 'sync' = 'auto'
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  src = ''
  private finish: (() => void) | null = null
  private readonly ready = new Promise<void>((resolve) => {
    this.finish = resolve
  })

  constructor() {
    DeferredImage.instances.push(this)
  }

  decode() {
    return this.ready
  }

  resolve() {
    this.finish?.()
    this.onload?.()
  }
}

describe('ComputerAppPipHost', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    DeferredImage.instances = []
    desktop.frames = [
      { attached: true, width: 800, height: 600, media_type: 'image/jpeg', data: 'FIRST' },
      { attached: true, width: 800, height: 600, media_type: 'image/jpeg', data: 'SECOND' },
    ]
    desktop.invoke.mockReset()
    desktop.invoke.mockImplementation(async (command: string) => {
      if (command === 'app_computer_frame') {
        return desktop.frames.shift() ?? {
          attached: true,
          width: 800,
          height: 600,
          media_type: 'image/jpeg',
          data: 'SECOND',
        }
      }
      return {}
    })
    desktop.listen.mockReset()
    desktop.listen.mockResolvedValue(() => undefined)
    vi.stubGlobal('Image', DeferredImage)
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      disconnect() {}
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('keeps the last decoded frame visible until the next frame is ready', async () => {
    render(<ComputerAppPipHost sessionId="chat-1" stackDepth={0} stackOrder={0} />)
    await act(async () => { await Promise.resolve() })

    expect(DeferredImage.instances).toHaveLength(1)
    await act(async () => { vi.advanceTimersByTime(600); await Promise.resolve() })
    expect(DeferredImage.instances).toHaveLength(2)
    expect(document.querySelector('img')).toBeNull()

    // Even though a newer frame was requested before the first one decoded,
    // the first completed frame becomes visible instead of being cancelled.
    await act(async () => { DeferredImage.instances[0].resolve(); await Promise.resolve() })
    expect(document.querySelector('img')?.getAttribute('src')).toContain('FIRST')

    await act(async () => { DeferredImage.instances[1].resolve(); await Promise.resolve() })
    expect(document.querySelector('img')?.getAttribute('src')).toContain('SECOND')
  })
})
