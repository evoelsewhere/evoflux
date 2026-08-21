import { render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AgentView } from '@/components/AgentView'
import { useTeamStore } from '@/stores/useTeamStore'
import type { ContentBlock } from '@/api/types'

const pinnedTranscript = vi.hoisted(() => vi.fn())

vi.mock('@/hooks/usePinnedTranscript', () => ({
  captureTranscriptPrependAnchor: () => null,
  usePinnedTranscript: (...args: unknown[]) => pinnedTranscript(...args),
}))

vi.mock('@/components/BlockRenderer', () => ({
  BlockRenderer: ({ block }: { block: ContentBlock }) => <div>{block.content}</div>,
}))

vi.mock('@/components/UserMessageNavigationRail', () => ({
  UserMessageNavigationRail: () => null,
}))

function block(id: string, type: ContentBlock['type'], content: string): ContentBlock {
  return { id, type, content }
}

describe('AgentView initial transcript position', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    pinnedTranscript.mockReset()
    pinnedTranscript.mockReturnValue({
      contentRef: { current: null },
      detach: vi.fn(),
      restorePrependOffset: vi.fn(),
      scrollRef: { current: null },
      scrollToBottom: vi.fn(),
      showScrollButton: false,
    })
    useTeamStore.setState({ sessionId: 'session-scroll-test' })
  })

  it('anchors the latest finalized user message on session hydration', () => {
    const finalizedUser = block('user-finalized', 'user', 'Keep this prompt visible')
    const { container, rerender } = render(
      <AgentView
        blocks={[finalizedUser, block('answer', 'text', 'Short answer')]}
        currentBlocks={[]}
        isWorking={false}
      />,
    )

    expect(pinnedTranscript.mock.calls.at(-1)?.[0]).toMatchObject({
      topAnchorKey: 'user-finalized',
    })
    expect(
      container.querySelector('[data-transcript-top-anchor="true"]'),
    ).toHaveTextContent('Keep this prompt visible')

    const liveUser = block('user-live', 'user', 'Newest live prompt')
    rerender(
      <AgentView
        blocks={[finalizedUser, block('answer', 'text', 'Short answer')]}
        currentBlocks={[liveUser]}
        isWorking
      />,
    )

    expect(pinnedTranscript.mock.calls.at(-1)?.[0]).toMatchObject({
      topAnchorKey: 'user-live',
    })
    expect(
      container.querySelector('[data-transcript-top-anchor="true"]'),
    ).toHaveTextContent('Newest live prompt')
  })
})
