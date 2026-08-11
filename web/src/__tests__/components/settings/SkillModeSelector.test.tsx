import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SkillModeSelector } from '@/components/settings/SkillModeSelector'

describe('SkillModeSelector', () => {
  it('toggles individual modes without collapsing partial combinations', () => {
    const onChange = vi.fn()
    render(
      <SkillModeSelector
        value={['work', 'aim']}
        onChange={onChange}
      />,
    )

    expect(screen.getByRole('button', { name: 'Work' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Coding' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'AIM' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'Coding' }))
    expect(onChange).toHaveBeenCalledWith(['work', 'coding', 'aim'])
  })

  it('keeps at least one mode selected', () => {
    const onChange = vi.fn()
    render(
      <SkillModeSelector
        value={['aim']}
        onChange={onChange}
      />,
    )

    const aim = screen.getByRole('button', { name: 'AIM' })
    expect(aim).toBeDisabled()
    fireEvent.click(aim)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('offers an all-modes shortcut', () => {
    const onChange = vi.fn()
    render(
      <SkillModeSelector
        value={['coding']}
        onChange={onChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'All modes' }))
    expect(onChange).toHaveBeenCalledWith(['work', 'coding', 'aim'])
  })
})
