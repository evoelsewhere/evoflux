import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MinesweeperGame } from '@/components/waiting-arcade/games/MinesweeperGame'
import { SnakeGame } from '@/components/waiting-arcade/games/SnakeGame'
import { TicTacToeGame } from '@/components/waiting-arcade/games/TicTacToeGame'
import { Game2048 } from '@/components/waiting-arcade/games/Game2048'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Snake game view', () => {
  it('starts only after the user asks and advances while active', () => {
    vi.useFakeTimers()
    render(<SnakeGame active />)

    expect(screen.getByRole('button', { name: 'Start Snake' })).toBeInTheDocument()
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', '5')
    fireEvent.click(screen.getByRole('button', { name: 'Start Snake' }))

    act(() => vi.advanceTimersByTime(320))

    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', '6')
  })

  it('accepts direction keys only when its board is focused', () => {
    vi.useFakeTimers()
    render(<SnakeGame active />)
    const board = screen.getByRole('group', { name: 'Snake board' })
    const head = screen.getByTestId('snake-head')

    fireEvent.keyDown(document.body, { key: 'ArrowDown' })
    expect(head).toHaveAttribute('data-y', '5')

    board.focus()
    fireEvent.keyDown(board, { key: 'ArrowDown' })
    fireEvent.click(screen.getByRole('button', { name: 'Start Snake' }))
    act(() => vi.advanceTimersByTime(320))
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-y', '6')
  })

  it('pauses and resumes from Space when the board is focused', () => {
    vi.useFakeTimers()
    render(<SnakeGame active />)
    const board = screen.getByRole('group', { name: 'Snake board' })
    fireEvent.click(screen.getByRole('button', { name: 'Start Snake' }))
    board.focus()

    fireEvent.keyDown(board, { key: ' ' })
    expect(screen.getByRole('button', { name: 'Start Snake' })).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1000))
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', '5')

    fireEvent.keyDown(board, { key: ' ' })
    expect(screen.getByRole('button', { name: 'Pause Snake' })).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(320))
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', '6')
  })

  it('slows its tick to 480 ms when reduced motion is requested', () => {
    vi.useFakeTimers()
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
    render(<SnakeGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Snake' }))

    act(() => vi.advanceTimersByTime(320))
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', '5')
    act(() => vi.advanceTimersByTime(160))
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', '6')
  })

  it('shows a clear loss state and lets the user restart', () => {
    vi.useFakeTimers()
    render(<SnakeGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Snake' }))
    act(() => vi.advanceTimersByTime(7 * 320))
    expect(screen.getByText('Snake over — restart to play again')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Restart Snake' }))
    expect(screen.getByRole('button', { name: 'Start Snake' })).toBeInTheDocument()
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', '5')
  })
})

describe('Minesweeper game view', () => {
  it('reveals a cell and lets the user flag cells without a timer', () => {
    render(<MinesweeperGame active />)
    expect(screen.getByRole('button', { name: 'Start Minesweeper' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Start Minesweeper' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reveal mode' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cell 4, 4 hidden' }))

    expect(screen.getByRole('button', { name: /Cell 4, 4 revealed/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Flag mode' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cell 1, 1 hidden' }))
    expect(screen.getByRole('button', { name: 'Cell 1, 1 flagged' })).toBeInTheDocument()
  })

  it('uses one Tab stop and arrow keys to navigate its cells', () => {
    render(<MinesweeperGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Minesweeper' }))
    const firstCell = screen.getByRole('button', { name: 'Cell 1, 1 hidden' })
    const secondCell = screen.getByRole('button', { name: 'Cell 1, 2 hidden' })

    expect(firstCell).toHaveAttribute('tabindex', '0')
    expect(secondCell).toHaveAttribute('tabindex', '-1')
    firstCell.focus()
    fireEvent.keyDown(firstCell, { key: 'ArrowRight' })
    expect(secondCell).toHaveFocus()
    fireEvent.keyDown(secondCell, { key: 'ArrowLeft' })
    expect(firstCell).toHaveFocus()
    fireEvent.click(firstCell)
    expect(screen.getByRole('button', { name: /Cell 1, 1 revealed/ })).toBeInTheDocument()
  })
})

describe('Tic-tac-toe game view', () => {
  it('plays against an immediate local opponent without reporting agent progress', () => {
    render(<TicTacToeGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Tic-tac-toe' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cell 1' }))

    expect(screen.getByRole('button', { name: 'Cell 1: X' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cell 5: O' })).toBeInTheDocument()
    expect(screen.queryByText(/agent progress/i)).not.toBeInTheDocument()
  })

  it('uses one Tab stop and arrow keys to navigate its cells', () => {
    render(<TicTacToeGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Tic-tac-toe' }))
    const firstCell = screen.getByRole('button', { name: 'Cell 1' })
    const secondCell = screen.getByRole('button', { name: 'Cell 2' })

    expect(firstCell).toHaveAttribute('tabindex', '0')
    expect(secondCell).toHaveAttribute('tabindex', '-1')
    firstCell.focus()
    fireEvent.keyDown(firstCell, { key: 'ArrowRight' })
    expect(secondCell).toHaveFocus()
    fireEvent.click(secondCell)
    expect(screen.getByRole('button', { name: 'Cell 2: X' })).toBeInTheDocument()
  })
})

describe('2048 game view', () => {
  it('starts on an explicit board focus and moves tiles with arrow keys only there', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0)
    render(<Game2048 active />)
    const board = screen.getByRole('group', { name: '2048 board' })

    expect(screen.getByText('Move with the arrow keys after focusing the board')).toBeInTheDocument()
    expect(screen.getByText('Score: 0')).toBeInTheDocument()
    fireEvent.keyDown(document.body, { key: 'ArrowDown' })
    expect(screen.getByTestId('2048-cell-0')).toHaveTextContent('2')

    board.focus()
    fireEvent.keyDown(board, { key: 'ArrowDown' })
    expect(screen.getByTestId('2048-cell-12')).toHaveTextContent('2')
    expect(screen.getByTestId('2048-cell-13')).toHaveTextContent('2')
    expect(screen.getByText('Move 1, score 0')).toBeInTheDocument()
  })
})
