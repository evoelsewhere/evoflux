import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GoalProgressRow } from '@/components/GoalProgressRow'
import type { GoalResponse } from '@/api/types'

const goal: GoalResponse = {
  session_id: 'session-1',
  objective: 'Ship durable goal mode',
  status: 'active',
  token_budget: 10_000,
  tokens_used: 2_500,
  time_used_seconds: 65,
  pause_reason: null,
  blocker_streak: 1,
  status_details: null,
  version: 3,
  created_at: '2026-07-31T00:00:00Z',
  updated_at: '2026-07-31T00:01:05Z',
  completed_at: null,
}

describe('GoalProgressRow', () => {
  it('shows durable usage and dispatches pause and stop controls', () => {
    const onCommand = vi.fn()
    render(<GoalProgressRow goal={goal} onCommand={onCommand} />)

    expect(screen.getByText('Ship durable goal mode')).toBeInTheDocument()
    expect(screen.getByText('2,500 / 10K tokens')).toBeInTheDocument()
    expect(screen.getByText('1m')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '2500')

    fireEvent.click(screen.getByRole('button', { name: 'Pause goal' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove goal' }))
    expect(onCommand).toHaveBeenNthCalledWith(1, '/goal:pause')
    expect(onCommand).toHaveBeenNthCalledWith(2, '/goal:stop')
  })

  it('offers resume for a paused goal', () => {
    const onCommand = vi.fn()
    render(
      <GoalProgressRow
        goal={{ ...goal, status: 'paused', token_budget: null }}
        onCommand={onCommand}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Resume goal' }))
    expect(onCommand).toHaveBeenCalledWith('/goal:resume')
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})
