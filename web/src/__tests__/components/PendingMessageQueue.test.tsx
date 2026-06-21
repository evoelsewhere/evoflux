import { afterEach, describe, expect, it, mock } from 'bun:test'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PendingMessageQueue } from '@/components/PendingMessageQueue'
import { useTeamStore } from '@/stores/useTeamStore'

const INITIAL_TEAM_STATE = {
  _pendingMessages: [],
  sessionId: 'session-1',
}

afterEach(() => {
  cleanup()
  useTeamStore.setState(INITIAL_TEAM_STATE)
})

describe('PendingMessageQueue', () => {
  it('renders queued messages for the active session only', () => {
    useTeamStore.setState({
      sessionId: 'session-1',
      _pendingMessages: [
        { id: 'pending-1', sessionId: 'session-1', content: 'Queued for active session' },
        { id: 'pending-2', sessionId: 'session-2', content: 'Other session' },
      ],
    })

    render(<PendingMessageQueue />)

    expect(screen.getByText('Queued for active session')).toBeTruthy()
    expect(screen.queryByText('Other session')).toBeNull()
  })

  it('allows queued messages to span full width on mobile and caps width from md up', () => {
    useTeamStore.setState({
      sessionId: 'session-1',
      _pendingMessages: [
        { id: 'pending-1', sessionId: 'session-1', content: 'Queued message' },
      ],
    })

    const { container } = render(<PendingMessageQueue />)

    const wrapper = container.querySelector("div[class*='max-w-full'][class*='md:max-w-[78%]']")
    expect(wrapper).toBeTruthy()
  })

  it('keeps queued edit action visible and large enough for touch before desktop hover reveal', () => {
    useTeamStore.setState({
      sessionId: 'session-1',
      _pendingMessages: [
        { id: 'pending-1', sessionId: 'session-1', content: 'Queued message' },
      ],
    })

    render(<PendingMessageQueue />)

    const editButton = screen.getByLabelText('Edit queued message')
    expect(editButton.className).toContain('opacity-100')
    expect(editButton.className).toContain('h-8')
    expect(editButton.className).toContain('w-8')
    expect(editButton.className).toContain('md:opacity-70')
    expect(editButton.className).toContain('md:group-hover:opacity-100')
  })

  it('keeps expand action large enough for touch before desktop compact sizing', () => {
    useTeamStore.setState({
      sessionId: 'session-1',
      _pendingMessages: [
        {
          id: 'pending-1',
          sessionId: 'session-1',
          content: Array.from({ length: 11 }, (_, i) => `Line ${i + 1}`).join('\n'),
        },
      ],
    })

    render(<PendingMessageQueue />)

    const expandButton = screen.getByTitle('Expand')
    expect(expandButton.className).toContain('h-8')
    expect(expandButton.className).toContain('w-8')
    expect(expandButton.className).toContain('md:h-5')
    expect(expandButton.className).toContain('md:w-5')
  })

  it('restores queued text into the composer before removing the pending message', async () => {
    const user = userEvent.setup()
    const restoreListener = mock(() => {})
    window.addEventListener('queue:restore-draft', restoreListener)
    useTeamStore.setState({
      sessionId: 'session-1',
      _pendingMessages: [
        { id: 'pending-1', sessionId: 'session-1', content: 'Please edit me' },
      ],
    })

    render(<PendingMessageQueue />)

    await user.click(screen.getByLabelText('Edit queued message'))

    expect(restoreListener).toHaveBeenCalledTimes(1)
    expect(useTeamStore.getState()._pendingMessages).toEqual([])
    window.removeEventListener('queue:restore-draft', restoreListener)
  })
})
