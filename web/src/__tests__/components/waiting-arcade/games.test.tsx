import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MinesweeperGame } from '@/components/waiting-arcade/games/MinesweeperGame'
import { SnakeGame } from '@/components/waiting-arcade/games/SnakeGame'
import { TicTacToeGame } from '@/components/waiting-arcade/games/TicTacToeGame'
import { Game2048 } from '@/components/waiting-arcade/games/Game2048'
import { MemoryGame } from '@/components/waiting-arcade/games/MemoryGame'
import { BreakoutGame } from '@/components/waiting-arcade/games/BreakoutGame'

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
    expect(screen.getByTestId('2048-cell-12')).toHaveAttribute('data-motion-direction', 'down')
    expect(screen.getByTestId('2048-cell-12').className).toContain('waiting-2048-slide')
    expect(screen.getByTestId('2048-cell-12').getAttribute('style')).toContain('--waiting-offset-y: calc(-300% + -1.125rem)')
    expect(screen.getByText('Move 1, score 0')).toBeInTheDocument()
  })
})

describe('Memory Pairs game view', () => {
  it('uses one Tab stop and Enter to reveal a card', () => {
    render(<MemoryGame active />)
    const first = screen.getAllByRole('button', { name: 'Hidden card' })[0]
    expect(first).toHaveAttribute('tabindex', '0')
    first.focus()
    fireEvent.keyDown(first, { key: 'Enter' })
    expect(screen.getByRole('button', { name: /Revealed card/ })).toBeInTheDocument()
  })

  it('moves focus with arrows and clears a mismatch after a short reveal', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0)
    vi.useFakeTimers()
    render(<MemoryGame active />)
    const cells = screen.getAllByRole('button', { name: 'Hidden card' })
    cells[0].focus()
    fireEvent.keyDown(cells[0], { key: 'ArrowRight' })
    expect(cells[1]).toHaveFocus()
    fireEvent.click(cells[0])
    fireEvent.click(cells[1])
    act(() => vi.advanceTimersByTime(700))
    expect(screen.getAllByRole('button', { name: 'Hidden card' })).toHaveLength(16)
  })
})

describe('Mini Breakout game view', () => {
  it('moves the paddle with keyboard controls and pauses/resumes with Space', () => {
    vi.useFakeTimers()
    render(<BreakoutGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Breakout' }))
    const board = screen.getByRole('group', { name: 'Mini Breakout board' })
    const paddle = screen.getByTestId('breakout-paddle')
    const initialLeft = paddle.style.left
    fireEvent.keyDown(board, { key: 'ArrowLeft' })
    expect(paddle.style.left).not.toBe(initialLeft)
    fireEvent.keyDown(board, { key: ' ' })
    expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    expect(screen.getByRole('button', { name: 'Pause Breakout' })).toBeInTheDocument()
  })

  it('stops its animation loop while inactive', () => {
    vi.useFakeTimers()
    const view = render(<BreakoutGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Breakout' }))
    const ball = screen.getByTestId('breakout-ball')
    act(() => vi.advanceTimersByTime(64))
    const moved = ball.style.top
    view.rerender(<BreakoutGame active={false} />)
    act(() => vi.advanceTimersByTime(320))
    expect(screen.getByTestId('breakout-ball').style.top).toBe(moved)
  })

  it('slows the ball tick when reduced motion is preferred', () => {
    vi.useFakeTimers()
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
    render(<BreakoutGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Breakout' }))
    const ball = screen.getByTestId('breakout-ball')
    act(() => vi.advanceTimersByTime(32))
    expect(ball.style.top).toBe('83%')
    act(() => vi.advanceTimersByTime(32))
    expect(ball.style.top).not.toBe('83%')
  })

  it('stops its animation loop while the document is hidden', () => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    render(<BreakoutGame active />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Breakout' }))
    const ball = screen.getByTestId('breakout-ball')
    act(() => vi.advanceTimersByTime(64))
    const current = ball.style.top
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    act(() => vi.advanceTimersByTime(320))
    expect(ball.style.top).toBe(current)
  })
})
