import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AskUserQuestionModal } from '@/components/AskUserQuestionModal'
import { useTeamStore } from '@/stores/useTeamStore'

const api = vi.hoisted(() => ({
  replyAskUserQuestion: vi.fn(),
}))

vi.mock('@/api/client', () => api)
vi.mock('@/queries', () => ({
  useRegistryQuery: () => ({ data: { models: [] } }),
}))

beforeEach(() => {
  api.replyAskUserQuestion.mockReset().mockResolvedValue(undefined)
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

afterEach(() => {
  useTeamStore.setState({ sessionId: null, askUserQuestion: null })
})

function showQuestion(strict: boolean) {
  useTeamStore.setState({
    sessionId: 'session-1',
    askUserQuestion: {
      requestId: 'request-1',
      sessionId: 'session-1',
      questions: [{
        question: 'Choose a workspace',
        options: ['Current workspace', 'Choose another'],
        strict,
      }],
    },
  })
  render(<AskUserQuestionModal />)
}

describe('AskUserQuestionModal', () => {
  it('submits a free-text answer when options are suggestions', async () => {
    showQuestion(false)

    fireEvent.change(screen.getByRole('textbox', { name: 'Choose a workspace' }), {
      target: { value: '/work/custom-repo' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))

    await waitFor(() => {
      expect(api.replyAskUserQuestion).toHaveBeenCalledWith(
        'session-1',
        'request-1',
        ['/work/custom-repo'],
      )
    })
    expect(useTeamStore.getState().askUserQuestion).toBeNull()
  })

  it('does not offer a free-text field for a strict workflow gate', () => {
    showQuestion(true)

    expect(screen.queryByRole('textbox', { name: 'Choose a workspace' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Current workspace' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose another' })).toBeInTheDocument()
  })
})
