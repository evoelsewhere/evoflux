import { act, renderHook } from '@testing-library/react'
import { StrictMode, createElement, type PropsWithChildren } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { pinnedAfterViewportUpdate, usePinnedTranscript } from '@/hooks/usePinnedTranscript'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('pinnedAfterViewportUpdate', () => {
  it('keeps following when streamed content temporarily moves the bottom', () => {
    expect(pinnedAfterViewportUpdate(true, false)).toBe(true)
  })

  it('reattaches after a detached reader reaches the bottom', () => {
    expect(pinnedAfterViewportUpdate(false, true)).toBe(true)
  })

  it('keeps an explicitly detached reader detached above the bottom', () => {
    expect(pinnedAfterViewportUpdate(false, false)).toBe(false)
  })
})

describe('usePinnedTranscript follow boundaries', () => {
  it('reattaches and scrolls when a new prompt is submitted', () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    const { result, rerender } = renderHook(
      ({ followKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey: 'session-1',
        followKey,
      }),
      { initialProps: { followKey: null as string | null } },
    )

    const scroller = { scrollTop: 100, scrollHeight: 1_000, clientHeight: 400 }
    result.current.scrollRef.current = scroller as HTMLDivElement

    rerender({ followKey: 'user-2' })
    act(() => {
      while (frames.length > 0) frames.shift()?.(16)
    })

    expect(scroller.scrollTop).toBe(1_000)
    expect(result.current.showScrollButton).toBe(false)
  })

  it('still follows after StrictMode replays mount effects', () => {
    const frames = new Map<number, FrameRequestCallback>()
    let frameId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameId += 1
      frames.set(frameId, callback)
      return frameId
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))

    const wrapper = ({ children }: PropsWithChildren) => createElement(StrictMode, null, children)
    const { result, rerender } = renderHook(
      ({ resetKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey,
      }),
      {
        initialProps: { resetKey: 'session-1' },
        wrapper,
      },
    )

    const scroller = { scrollTop: 0, scrollHeight: 1_413, clientHeight: 555 }
    result.current.scrollRef.current = scroller as HTMLDivElement

    rerender({ resetKey: 'session-2' })
    act(() => {
      for (const callback of frames.values()) callback(16)
      frames.clear()
    })

    expect(scroller.scrollTop).toBe(1_413)
  })
})
