import { beforeEach, describe, expect, it } from 'vitest'

import { useUIStore } from '@/stores/useUIStore'

describe('EASD chat handoff state', () => {
  beforeEach(() => {
    useUIStore.setState({ easdChatRequest: null })
  })

  it('keeps a one-shot request until the target chat consumes its exact id', () => {
    useUIStore.getState().requestEasdChat({
      sessionId: 'session-2',
      workspace: '/repo',
      projectId: 'project-1',
      prompt: 'Execute the active EASD run.',
      autoSend: true,
      phase: 'implementation',
    })
    const request = useUIStore.getState().easdChatRequest

    expect(request).toMatchObject({ sessionId: 'session-2', autoSend: true })
    useUIStore.getState().clearEasdChatRequest((request?.id ?? 0) + 1)
    expect(useUIStore.getState().easdChatRequest).toEqual(request)
    useUIStore.getState().clearEasdChatRequest(request?.id)
    expect(useUIStore.getState().easdChatRequest).toBeNull()
  })
})
