import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createComputerAppBridge,
  restoreOpenCards,
  runComputerAppCommand,
} from '@/components/ComputerAppViewer/computerAppBridge'
import { useUIStore } from '@/stores/useUIStore'

const desktop = vi.hoisted(() => ({ stopped: false, invoke: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: desktop.invoke }))

class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = 1
  sent: string[] = []
  closed = false
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: (() => void) | null = null

  url: string

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.closed = true
    this.readyState = 3
    this.onclose?.({ code: 1000 })
  }
}

describe('createComputerAppBridge', () => {
  const realSocket = globalThis.WebSocket

  beforeEach(() => {
    FakeSocket.instances = []
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    desktop.invoke.mockReset()
  })

  afterEach(() => {
    globalThis.WebSocket = realSocket
  })

  const socketFor = (session: string) =>
    FakeSocket.instances.find((socket) => socket.url.includes(`/team/${session}/`))!

  it('only opens and closes the sockets that changed', () => {
    const bridge = createComputerAppBridge()
    bridge.sync(['a', 'b'])
    const a = socketFor('a')
    bridge.sync(['a', 'c'])

    expect(FakeSocket.instances).toHaveLength(3)
    expect(a.closed).toBe(false)
    expect(socketFor('b').closed).toBe(true)
    bridge.dispose()
    expect(a.closed).toBe(true)
  })

  it('takes a displaced session back when the user returns to the window', () => {
    vi.useFakeTimers()
    const bridge = createComputerAppBridge()
    bridge.sync(['a'])
    const first = socketFor('a')
    // Another EvoFlux window took the session.
    first.readyState = 3
    first.onclose?.({ code: 4409 })
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.instances).toHaveLength(1)

    window.dispatchEvent(new Event('focus'))

    expect(FakeSocket.instances).toHaveLength(2)
    bridge.dispose()
    vi.useRealTimers()
  })

  it('keeps a leaving session open until its command is answered', async () => {
    let finish: (value: unknown) => void = () => undefined
    desktop.invoke.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    const bridge = createComputerAppBridge()
    bridge.sync(['a'])
    const a = socketFor('a')
    a.onmessage?.({ data: JSON.stringify({ id: 'r1', action: 'type', params: { text: 'hi' } }) })
    await Promise.resolve()

    bridge.sync([])
    expect(a.closed).toBe(false)

    finish({ typed_chars: 2 })
    await vi.waitFor(() => expect(a.closed).toBe(true))
    expect(a.sent.some((message) => message.includes('"r1"'))).toBe(true)
    bridge.dispose()
  })
})

describe('restoreOpenCards', () => {
  beforeEach(() => {
    sessionStorage.clear()
    desktop.invoke.mockReset()
    useUIStore.setState({ computerPipSessionIds: [] })
  })

  it('reopens after a reload only the cards whose app is still attached', async () => {
    sessionStorage.setItem('oa.computer-app.open-cards', JSON.stringify(['held', 'gone', 'paused']))
    desktop.invoke.mockImplementation(async (_command: string, args: { sessionId: string }) => ({
      attached: args.sessionId === 'held',
      stopped: args.sessionId === 'paused',
    }))

    const stop = restoreOpenCards()

    await vi.waitFor(() =>
      expect([...useUIStore.getState().computerPipSessionIds].sort()).toEqual(['held', 'paused']),
    )
    stop()
  })

  it('saves the open cards as they change', () => {
    const stop = restoreOpenCards()
    useUIStore.getState().openComputerPip('chat-9')

    expect(JSON.parse(sessionStorage.getItem('oa.computer-app.open-cards')!)).toEqual(['chat-9'])
    stop()
    useUIStore.getState().closeComputerPip('chat-9')
    expect(JSON.parse(sessionStorage.getItem('oa.computer-app.open-cards')!)).toEqual(['chat-9'])
  })
})

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
