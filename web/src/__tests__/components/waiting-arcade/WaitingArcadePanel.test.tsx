import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { WaitingArcadePanel } from '@/components/waiting-arcade/WaitingArcadePanel'

function ArcadeHarness() {
  const [open, setOpen] = useState(false)
  return <WaitingArcadePanel open={open} active onOpenChange={setOpen} launcherVisible />
}

describe('Waiting Arcade picker', () => {
  it('shows six distinct pixel game marks without the broken arrow glyph', () => {
    render(<ArcadeHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'More composer actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Play while waiting' }))
    expect(screen.getByRole('dialog', { name: 'Waiting Arcade' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Play while waiting' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()
    const games = ['Snake', 'Minesweeper Mini', 'Tic-tac-toe', '2048', 'Memory Pairs', 'Mini Breakout']
    games.forEach((name) => expect(screen.getByRole('button', { name })).toBeInTheDocument())
    const icons = screen.getAllByRole('button', { name: /^(Snake|Minesweeper Mini|Tic-tac-toe|2048|Memory Pairs|Mini Breakout)$/ }).map((button) => button.querySelector('svg path')?.getAttribute('d'))
    expect(new Set(icons).size).toBe(games.length)
    expect(screen.queryByText('↗')).not.toBeInTheDocument()
  })
})
