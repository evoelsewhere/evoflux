import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  AUTOMATIC_SPLIT_TRANSITION_MS,
  AutomaticSplitTransition,
} from '@/components/TeamChatView/AutomaticSplitTransition'
import { shouldStartAutomaticSplit } from '@/components/TeamChatView/auto-layout'

describe('automatic Split layout', () => {
  it('starts when active agents cross from two to three', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 2,
      activeCount: 3,
      viewMode: 'agent',
      isMobile: false,
    })).toBe(true)
  })

  it('does not repeatedly override a manual Agent selection', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 3,
      activeCount: 3,
      viewMode: 'agent',
      isMobile: false,
    })).toBe(false)
  })

  it('does not override Monitor or mobile layouts', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 2,
      activeCount: 3,
      viewMode: 'monitor',
      isMobile: false,
    })).toBe(false)
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 2,
      activeCount: 3,
      viewMode: 'agent',
      isMobile: true,
    })).toBe(false)
  })

  it('does not start with only two active agents', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 1,
      activeCount: 2,
      viewMode: 'agent',
      isMobile: false,
    })).toBe(false)
  })
})

describe('AutomaticSplitTransition', () => {
  it('announces the change and completes after the border orbit', () => {
    vi.useFakeTimers()
    const onComplete = vi.fn()
    const { container } = render(
      <AutomaticSplitTransition activeAgentCount={3} onComplete={onComplete} />,
    )

    expect(screen.getByRole('status')).toHaveAccessibleName(
      'Organizing 3 active agents into Split layout',
    )
    const rings = container.querySelectorAll('.oa-layout-switch-ring')
    expect(rings).toHaveLength(2)
    act(() => {
      vi.advanceTimersByTime(AUTOMATIC_SPLIT_TRANSITION_MS)
    })
    expect(onComplete).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })
})
