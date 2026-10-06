import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WaitingArcadeHost } from '@/components/waiting-arcade/WaitingArcadeHost'

async function openSnake() {
  fireEvent.click(screen.getByRole('button', { name: 'Play while waiting' }))
  fireEvent.click(screen.getByRole('button', { name: 'Snake' }))
  await act(async () => vi.dynamicImportSettled())
  fireEvent.click(screen.getByRole('button', { name: 'Start Snake' }))
}

afterEach(() => {
  vi.useRealTimers()
  delete (document as unknown as { visibilityState?: DocumentVisibilityState }).visibilityState
})

describe('WaitingArcadeHost lifecycle', () => {
  it('shows the launcher after 1.5 seconds of active work', () => {
    vi.useFakeTimers()
    render(<WaitingArcadeHost isWorking sessionId="s1" mode="work" hasUserActionGate={false} />)
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()

    act(() => vi.advanceTimersByTime(1499))
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByRole('button', { name: 'Play while waiting' })).toBeInTheDocument()
  })

  it('cancels the delayed launcher when work stops or a gate is pending', () => {
    vi.useFakeTimers()
    const { rerender } = render(<WaitingArcadeHost isWorking sessionId="s1" mode="work" hasUserActionGate={false} />)
    act(() => vi.advanceTimersByTime(900))
    rerender(<WaitingArcadeHost isWorking={false} sessionId="s1" mode="work" hasUserActionGate={false} />)
    act(() => vi.advanceTimersByTime(1000))
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()

    rerender(<WaitingArcadeHost isWorking sessionId="s1" mode="work" hasUserActionGate />)
    act(() => vi.advanceTimersByTime(1500))
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()
  })

  it('pauses and closes for a user gate, then requires a manual reopen', async () => {
    vi.useFakeTimers()
    const { rerender } = render(<WaitingArcadeHost isWorking sessionId="s1" mode="work" hasUserActionGate={false} />)
    act(() => vi.advanceTimersByTime(1500))
    await openSnake()
    act(() => vi.advanceTimersByTime(240))
    const head = screen.getByTestId('snake-head')
    const x = head.getAttribute('data-x')

    rerender(<WaitingArcadeHost isWorking sessionId="s1" mode="work" hasUserActionGate />)
    expect(screen.queryByRole('group', { name: 'Snake board' })).not.toBeInTheDocument()
    act(() => vi.advanceTimersByTime(500))
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()

    rerender(<WaitingArcadeHost isWorking sessionId="s1" mode="work" hasUserActionGate={false} />)
    act(() => vi.advanceTimersByTime(1500))
    expect(screen.getByRole('button', { name: 'Play while waiting' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start Snake' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Play while waiting' }))
    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', x)
  })

  it('clears the selected game when the session changes', async () => {
    vi.useFakeTimers()
    const { rerender } = render(<WaitingArcadeHost isWorking sessionId="s1" mode="coding" hasUserActionGate={false} />)
    act(() => vi.advanceTimersByTime(1500))
    fireEvent.click(screen.getByRole('button', { name: 'Play while waiting' }))
    fireEvent.click(screen.getByRole('button', { name: 'Snake' }))
    await act(async () => vi.dynamicImportSettled())
    expect(screen.getByRole('button', { name: 'Start Snake' })).toBeInTheDocument()

    rerender(<WaitingArcadeHost isWorking sessionId="s2" mode="coding" hasUserActionGate={false} />)
    act(() => vi.advanceTimersByTime(1499))
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    fireEvent.click(screen.getByRole('button', { name: 'Play while waiting' }))
    expect(screen.getByRole('button', { name: 'Snake' })).toBeInTheDocument()
  })

  it('stops game ticks while the document is hidden', async () => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    render(<WaitingArcadeHost isWorking sessionId="s1" mode="work" hasUserActionGate={false} />)
    act(() => vi.advanceTimersByTime(1500))
    await openSnake()
    act(() => vi.advanceTimersByTime(240))
    const x = screen.getByTestId('snake-head').getAttribute('data-x')

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    act(() => vi.advanceTimersByTime(1000))

    expect(screen.getByTestId('snake-head')).toHaveAttribute('data-x', x)
  })
})
