import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const backend = vi.hoisted(() => ({
  getAppBackendStatus: vi.fn(),
}))

vi.mock('@/lib/app-backend', () => ({
  getAppBackendStatus: backend.getAppBackendStatus,
  isTauriContext: () => true,
  retryAppBackend: vi.fn(),
  revealAppBackendLog: vi.fn(),
}))
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}))

import { useAppBackendBootstrap } from '@/hooks/use-app-backend-bootstrap'

describe('useAppBackendBootstrap', () => {
  afterEach(() => vi.clearAllMocks())

  it('keeps the splash mounted when startup reports an error without a backend', async () => {
    backend.getAppBackendStatus.mockResolvedValue({
      base_url: null,
      token: null,
      startup: {
        phase: 'error',
        message: "EvoFlux couldn't start.",
        attempt: 1,
        max_attempts: 3,
        elapsed_ms: 10,
        error: 'attempt 1/3 failed',
        fatal: true,
      },
    })
    const { result } = renderHook(() => useAppBackendBootstrap())
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(result.current.startup.phase).toBe('error')
    expect(result.current.ready).toBe(false)
  })
})
