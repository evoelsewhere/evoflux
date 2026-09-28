import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useToastStore } from '@/stores/useToastStore'

beforeEach(() => {
  vi.useFakeTimers()
  useToastStore.setState({ toasts: [] })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useToastStore', () => {
  it('collapses a repeated identical toast into one and extends its life', () => {
    const { push } = useToastStore.getState()
    const failure = { tone: 'error' as const, title: 'Could not save WebBridge', description: 'Method Not Allowed' }

    push(failure, 1000)
    vi.advanceTimersByTime(800)
    push(failure, 1000)
    push(failure, 1000)

    expect(useToastStore.getState().toasts).toHaveLength(1)
    vi.advanceTimersByTime(800)
    expect(useToastStore.getState().toasts).toHaveLength(1)
    vi.advanceTimersByTime(300)
    expect(useToastStore.getState().toasts).toHaveLength(0)
  })

  it('keeps toasts that differ in description', () => {
    const { push } = useToastStore.getState()
    push({ tone: 'error', title: 'Could not save', description: 'A' })
    push({ tone: 'error', title: 'Could not save', description: 'B' })

    expect(useToastStore.getState().toasts).toHaveLength(2)
  })
})
