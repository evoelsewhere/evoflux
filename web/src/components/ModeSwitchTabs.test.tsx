import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ModeSwitchTabs } from './ModeSwitchTabs'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
}))

describe('ModeSwitchTabs', () => {
  it('exposes one stable active indicator and current-page semantics', () => {
    render(<ModeSwitchTabs active="coding" />)

    expect(screen.getByTestId('mode-switch-indicator')).toHaveAttribute('data-active-mode', 'coding')
    expect(screen.getByRole('button', { name: 'Coding' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getAllByRole('button')).toHaveLength(3)
  })

  it('never renders an expanded mode label with ellipsis', () => {
    render(<ModeSwitchTabs active="forge" />)

    for (const label of ['Forge', 'Coding', 'AIM']) {
      expect(screen.getByText(label)).not.toHaveClass('truncate')
      expect(screen.getByText(label)).toHaveClass('whitespace-nowrap')
    }
  })
})
