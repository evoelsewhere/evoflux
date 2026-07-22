import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAppearance } from './useAppearance'

describe('useAppearance', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('synchronizes appearance changes across hook instances in the same window', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const first = renderHook(() => useAppearance())
    const second = renderHook(() => useAppearance())

    act(() => first.result.current.update({ accent: 'blue' }))

    expect(first.result.current.settings.accent).toBe('blue')
    expect(second.result.current.settings.accent).toBe('blue')
    expect(consoleError).not.toHaveBeenCalled()
  })

  it('keeps synchronous appearance patches without losing earlier values', () => {
    const hook = renderHook(() => useAppearance())

    act(() => {
      hook.result.current.update({ accent: 'purple' })
      hook.result.current.update({ fontScale: 1.1 })
    })

    expect(hook.result.current.settings).toMatchObject({ accent: 'purple', fontScale: 1.1 })
  })
})
