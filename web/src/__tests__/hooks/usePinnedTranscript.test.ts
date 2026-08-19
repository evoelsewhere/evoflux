import { act, fireEvent, render, renderHook } from '@testing-library/react'
import { StrictMode, createElement, useEffect, type PropsWithChildren } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  nextPinnedScrollTop,
  pinnedAfterViewportUpdate,
  usePinnedTranscript,
} from '@/hooks/usePinnedTranscript'

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

describe('nextPinnedScrollTop', () => {
  it('eases toward new streamed height without jumping a full line', () => {
    const next = nextPinnedScrollTop(500, 524, 16)

    expect(next).toBeGreaterThan(500)
    expect(next).toBeLessThan(524)
  })

  it('settles exactly and handles content shrinking', () => {
    expect(nextPinnedScrollTop(523.6, 524, 16)).toBe(524)
    expect(nextPinnedScrollTop(540, 524, 16)).toBe(524)
  })
})

describe('usePinnedTranscript follow boundaries', () => {
  it('ignores layout-driven scroll events but detaches on upward wheel intent', () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const captured: { current: ReturnType<typeof usePinnedTranscript> | null } = { current: null }
    const captureHook = (value: ReturnType<typeof usePinnedTranscript>) => {
      captured.current = value
    }

    function Harness({ onHook }: { onHook: typeof captureHook }) {
      const value = usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey: null,
      })
      useEffect(() => onHook(value), [onHook, value])
      return createElement(
        'div',
        { ref: value.scrollRef },
        createElement('div', { ref: value.contentRef }),
      )
    }

    const { container } = render(createElement(Harness, { onHook: captureHook }))
    const scroller = container.firstElementChild as HTMLDivElement
    Object.defineProperties(scroller, {
      clientHeight: { configurable: true, value: 400 },
      scrollHeight: { configurable: true, value: 1_000 },
      scrollTop: { configurable: true, value: 320, writable: true },
    })

    fireEvent.scroll(scroller)
    act(() => {
      let timestamp = 0
      while (frames.length > 0) frames.shift()?.(timestamp += 16)
    })
    expect(scroller.scrollTop).toBe(600)
    expect(captured.current?.showScrollButton).toBe(false)

    fireEvent.wheel(scroller, { deltaY: -20 })
    expect(captured.current?.showScrollButton).toBe(true)
  })

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

    // A real scrolling element clamps `scrollHeight` assignments to its
    // maximum scrollTop (scrollHeight - clientHeight).
    expect(scroller.scrollTop).toBe(600)
    expect(result.current.showScrollButton).toBe(false)
  })

  it('pins a new user message to the viewport top and stops bottom-follow', () => {
    const frames = new Map<number, FrameRequestCallback>()
    let frameId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameId += 1
      frames.set(frameId, callback)
      return frameId
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))

    const { result, rerender } = renderHook(
      ({ topAnchorKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey: null,
        topAnchorKey,
      }),
      { initialProps: { topAnchorKey: null as string | null } },
    )
    const scroller = document.createElement('div')
    const anchor = document.createElement('div')
    anchor.dataset.transcriptTopAnchor = 'true'
    anchor.scrollIntoView = vi.fn()
    scroller.appendChild(anchor)
    result.current.scrollRef.current = scroller

    rerender({ topAnchorKey: 'user-2' })
    act(() => {
      for (const callback of frames.values()) callback(16)
      frames.clear()
    })

    expect(anchor.scrollIntoView).toHaveBeenCalledWith({
      behavior: 'auto',
      block: 'start',
    })
    expect(result.current.isPinned()).toBe(false)
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
