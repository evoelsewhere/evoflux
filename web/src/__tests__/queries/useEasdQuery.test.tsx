import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  useAddEasdEvidenceMutation,
  useRetryEasdPlanningMutation,
  useRetryEasdSpecAuthoringMutation,
  useStartEasdRunInChatMutation,
  useStartEasdPlanningMutation,
  useStartEasdReviewMutation,
  useStartEasdSpecAuthoringMutation,
  useStartEasdVerificationMutation,
  useConvergeEasdRunMutation,
  usePublishEasdRunMutation,
} from '@/queries/useEasdQuery'

const api = vi.hoisted(() => ({
  addEvidence: vi.fn(),
  startInChat: vi.fn(),
  startAuthoring: vi.fn(),
  startPlanning: vi.fn(),
  retryAuthoring: vi.fn(),
  retryPlanning: vi.fn(),
  startReview: vi.fn(),
  startVerification: vi.fn(),
  converge: vi.fn(),
  publish: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  acceptEasdRevision: vi.fn(),
  acceptEasdPlanRevision: vi.fn(),
  startEasdRunInChat: api.startInChat,
  startEasdSpecAuthoringInChat: api.startAuthoring,
  startEasdPlanningInChat: api.startPlanning,
  retryEasdSpecAuthoringInChat: api.retryAuthoring,
  retryEasdPlanningInChat: api.retryPlanning,
  startEasdReviewInChat: api.startReview,
  startEasdVerificationInChat: api.startVerification,
  addEasdDeviation: vi.fn(),
  addEasdEvidence: api.addEvidence,
  convergeEasdRun: api.converge,
  createEasdRun: vi.fn(),
  createEasdRevision: vi.fn(),
  executeEasdRecovery: vi.fn(),
  executeEasdRuntimeMigration: vi.fn(),
  generateEasdScopeAndProof: vi.fn(),
  getEasdRun: vi.fn(),
  getEasdRunTrace: vi.fn(),
  getEasdRecovery: vi.fn(),
  getEasdPublication: vi.fn(),
  getEasdRuntimeMigration: vi.fn(),
  getEasdSetup: vi.fn(),
  initializeEasdSetup: vi.fn(),
  listEasdRuns: vi.fn(),
  publishEasdRun: api.publish,
}))

function wrapper(client: QueryClient) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('EASD query invalidation', () => {
  beforeEach(() => {
    api.addEvidence.mockReset().mockResolvedValue({ id: 'evidence-1' })
    api.startInChat.mockReset().mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'active' })
    api.startAuthoring.mockReset().mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'authoring' })
    api.startPlanning.mockReset().mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'planning' })
    api.retryAuthoring.mockReset().mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'authoring' })
    api.retryPlanning.mockReset().mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'planning' })
    api.startReview.mockReset().mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'reviewing' })
    api.startVerification.mockReset().mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'verifying' })
    api.converge.mockReset().mockResolvedValue({ report: {} })
    api.publish.mockReset().mockResolvedValue({ eligible: true, published: true, created: true, path: 'records/run.yaml', record: {} })
  })

  it('refreshes list and detail caches after lifecycle convergence', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useConvergeEasdRunMutation('run-1'), {
      wrapper: wrapper(client),
    })

    await act(() => result.current.mutateAsync())

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['easd', 'runs'] })
  })

  it('stores the manual publication result in the Run publication cache', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const { result } = renderHook(() => usePublishEasdRunMutation('run-1'), {
      wrapper: wrapper(client),
    })

    await act(() => result.current.mutateAsync())

    expect(api.publish).toHaveBeenCalledWith('run-1')
    expect(client.getQueryData(['easd', 'runs', 'run-1', 'publication'])).toMatchObject({
      published: true,
      created: true,
    })
  })

  it('refreshes the same cache family after evidence changes acceptance state', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useAddEasdEvidenceMutation('run-1'), {
      wrapper: wrapper(client),
    })

    await act(() => result.current.mutateAsync({
      spec_hash: 'a'.repeat(64),
      criterion_ids: ['AC-1'],
      producer: 'human',
      kind: 'manual',
      result: 'passed',
      summary: 'Observed in the live UI.',
    }))

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['easd', 'runs'] })
  })

  it('refreshes run caches after atomically starting a run in chat', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useStartEasdRunInChatMutation('run-1'), {
      wrapper: wrapper(client),
    })

    await act(() => result.current.mutateAsync('session-1'))

    expect(api.startInChat).toHaveBeenCalledWith('run-1', 'session-1')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['easd', 'runs'] })
  })

  it('refreshes run caches after starting specification authoring', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useStartEasdSpecAuthoringMutation('run-1'), {
      wrapper: wrapper(client),
    })

    await act(() => result.current.mutateAsync('session-1'))

    expect(api.startAuthoring).toHaveBeenCalledWith('run-1', 'session-1')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['easd', 'runs'] })
  })

  it('refreshes run caches after every post-spec phase transition', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const planning = renderHook(() => useStartEasdPlanningMutation('run-1'), {
      wrapper: wrapper(client),
    })
    const review = renderHook(() => useStartEasdReviewMutation('run-1'), {
      wrapper: wrapper(client),
    })
    const verification = renderHook(() => useStartEasdVerificationMutation('run-1'), {
      wrapper: wrapper(client),
    })

    await act(() => planning.result.current.mutateAsync('session-1'))
    await act(() => review.result.current.mutateAsync('session-1'))
    await act(() => verification.result.current.mutateAsync('session-1'))

    expect(api.startPlanning).toHaveBeenCalledWith('run-1', 'session-1')
    expect(api.startReview).toHaveBeenCalledWith('run-1', 'session-1')
    expect(api.startVerification).toHaveBeenCalledWith('run-1', 'session-1')
    expect(invalidate).toHaveBeenCalledTimes(3)
  })

  it('refreshes run caches after retrying Spec and Plan authoring', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const specification = renderHook(() => useRetryEasdSpecAuthoringMutation('run-1'), {
      wrapper: wrapper(client),
    })
    const plan = renderHook(() => useRetryEasdPlanningMutation('run-1'), {
      wrapper: wrapper(client),
    })

    await act(() => specification.result.current.mutateAsync('session-1'))
    await act(() => plan.result.current.mutateAsync('session-1'))

    expect(api.retryAuthoring).toHaveBeenCalledWith('run-1', 'session-1')
    expect(api.retryPlanning).toHaveBeenCalledWith('run-1', 'session-1')
    expect(invalidate).toHaveBeenCalledTimes(2)
  })
})
