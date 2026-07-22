import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BookOpen } from 'lucide-react'
import { describe, expect, it, vi } from 'vitest'

import { AgentTopbar } from './AgentTopbar'
import { TopbarAction } from './ui/topbar-action'

describe('AgentTopbar', () => {
  it('renders one animated indicator with radio semantics for the active view', async () => {
    const user = userEvent.setup()
    const onViewModeChange = vi.fn()

    render(
      <AgentTopbar
        viewMode="agent"
        onViewModeChange={onViewModeChange}
      />,
    )

    const group = screen.getByRole('radiogroup', { name: 'View mode' })
    expect(group).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Agent' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getAllByTestId('view-mode-indicator')).toHaveLength(1)

    await user.click(screen.getByRole('radio', { name: 'Split' }))
    expect(onViewModeChange).toHaveBeenCalledWith('split')
  })

  it('gives active topbar actions a stable pressed surface', () => {
    render(
      <TopbarAction
        Icon={BookOpen}
        label="Wiki"
        aria-pressed="true"
        onClick={() => undefined}
      />,
    )

    expect(screen.getByRole('button', { name: 'Wiki' })).toHaveClass(
      'aria-pressed:bg-(--color-surface-2)',
    )
  })
})
