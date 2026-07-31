import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SideChatTranscript } from '@/components/SideChatPanel/SideChatTranscript'

vi.mock('@/components/BlockRenderer', () => ({
  BlockRenderer: ({ block }: { block: { content: string } }) => <div>{block.content}</div>,
}))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('chat scroll scheduling', () => {
  it('coalesces a burst of scroll events into one animation frame', () => {
    let frameId = 0
    const requestFrame = vi.fn((_callback: FrameRequestCallback) => {
      frameId += 1
      return frameId
    })
    vi.stubGlobal('requestAnimationFrame', requestFrame)
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    render(
      <SideChatTranscript
        blocks={[{ id: 'user-1', type: 'user', content: 'Hello' }]}
        currentBlocks={[]}
        isWorking={false}
      />,
    )
    requestFrame.mockClear()

    const scroller = screen.getByTestId('side-chat-scroll')
    fireEvent.scroll(scroller)
    fireEvent.scroll(scroller)
    fireEvent.scroll(scroller)

    expect(requestFrame).toHaveBeenCalledOnce()
  })
})
