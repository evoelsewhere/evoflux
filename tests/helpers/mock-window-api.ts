import { vi } from 'vitest'

export interface MockWindowAPI {
  chatMock: ReturnType<typeof vi.fn>
  workflowMock: {
    save: ReturnType<typeof vi.fn>
    load: ReturnType<typeof vi.fn>
    list: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
    run: ReturnType<typeof vi.fn>
  }
}

export function setupWindowAPI(): MockWindowAPI {
  const chatMock = vi.fn().mockResolvedValue('Mock LLM response')
  const workflowMock = {
    save: vi.fn().mockResolvedValue({ id: 'wf-1', name: 'Test' }),
    load: vi.fn().mockResolvedValue(null),
    list: vi.fn().mockResolvedValue([]),
    delete: vi.fn().mockResolvedValue(true),
    run: vi.fn().mockResolvedValue({ success: true, results: [] }),
  }

  const win = {
    api: {
      ai: { chat: chatMock },
      workflow: workflowMock,
    },
  }

  // Use Object.assign to set window without defineProperty non-configurable issue
  if (typeof globalThis.window === 'undefined') {
    Object.defineProperty(globalThis, 'window', { value: win, writable: true, configurable: true })
  } else {
    Object.assign(globalThis.window, win)
  }

  return { chatMock, workflowMock }
}

export function teardownWindowAPI(): void {
  if (globalThis.window && 'api' in globalThis.window) {
    // @ts-expect-error — cleanup test environment
    globalThis.window.api = undefined
  }
}
