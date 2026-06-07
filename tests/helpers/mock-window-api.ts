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

  Object.defineProperty(globalThis, 'window', {
    value: {
      api: {
        ai: { chat: chatMock },
        workflow: workflowMock,
      },
    },
    writable: true,
  })

  return { chatMock, workflowMock }
}

export function teardownWindowAPI(): void {
  // @ts-expect-error — cleanup test environment
  delete globalThis.window
}
