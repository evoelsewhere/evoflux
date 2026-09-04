/**
 * The transcript viewport's contract, after it was rebuilt on browser
 * primitives.
 *
 * Three things moved out of JavaScript and cannot be asserted here, so
 * they were verified in the app's own WebView instead and are recorded in
 * the hook's own comments: `overflow-anchor` holding the reader's place
 * when history is prepended, the sentinel's visibility answering "are we
 * at the bottom", and `scrollTo` being used in place of `scrollIntoView`
 * because that one also scrolls every scrollable ancestor.
 *
 * What is left to test here is the part that is still logic: when the
 * viewport follows, and what makes it stop.
 */

import { act, fireEvent, render, renderHook } from '@testing-library/react'
import { StrictMode, createElement, useEffect, type PropsWithChildren } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  pinnedAfterViewportUpdate,
  usePinnedTranscript,
} from '@/hooks/usePinnedTranscript'

type ObserverCallback = (entries: { isIntersecting: boolean }[]) => void

/** Lets a test say "the bottom came into view" without a layout engine. */
const observers: { callback: ObserverCallback; targets: Element[] }[] = []

function reportBottomVisible(isIntersecting: boolean): void {
  act(() => {
    for (const observer of observers) {
      observer.callback([{ isIntersecting }])
    }
  })
}

beforeEach(() => {
  observers.length = 0
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      callback: ObserverCallback
      targets: Element[] = []
      constructor(callback: ObserverCallback) {
        this.callback = callback
      }
      observe(target: Element) {
        this.targets.push(target)
        observers.push({ callback: this.callback, targets: this.targets })
      }
      disconnect() {
        const index = observers.findIndex((o) => o.callback === this.callback)
        if (index !== -1) observers.splice(index, 1)
      }
      unobserve() {}
      takeRecords() {
        return []
      }
    },
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** A scroller whose `scrollTo` records where it was asked to go. */
function fakeScroller(scrollHeight = 1_000) {
  const calls: ScrollToOptions[] = []
  const element = document.createElement('div')
  Object.defineProperties(element, {
    scrollHeight: { configurable: true, value: scrollHeight },
    clientHeight: { configurable: true, value: 400 },
    scrollTop: { configurable: true, value: 0, writable: true },
    offsetHeight: { configurable: true, value: 400 },
    offsetWidth: { configurable: true, value: 500 },
    clientWidth: { configurable: true, value: 488 },
  })
  element.scrollTo = ((options: ScrollToOptions) => {
    calls.push(options)
  }) as typeof element.scrollTo
  return { element, calls }
}

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

describe('following new content', () => {
  it('goes to the bottom when content grows while pinned', () => {
    const { result, rerender } = renderHook(
      ({ contentKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey,
        resetKey: null,
      }),
      { initialProps: { contentKey: 1 } },
    )
    const { element, calls } = fakeScroller()
    result.current.scrollRef.current = element

    rerender({ contentKey: 2 })
    expect(calls).toEqual([{ top: 1_000, behavior: 'auto' }])
  })

  it('leaves a detached reader alone when content grows', () => {
    const { result, rerender } = renderHook(
      ({ contentKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey,
        resetKey: null,
      }),
      { initialProps: { contentKey: 1 } },
    )
    const { element, calls } = fakeScroller()
    result.current.scrollRef.current = element

    act(() => result.current.detach())
    calls.length = 0
    rerender({ contentKey: 2 })
    expect(calls).toEqual([])
  })

  it('does not follow when following is disabled for a dormant pane', () => {
    const { result, rerender } = renderHook(
      ({ contentKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey,
        resetKey: null,
        followEnabled: false,
      }),
      { initialProps: { contentKey: 1 } },
    )
    const { element, calls } = fakeScroller()
    result.current.scrollRef.current = element

    rerender({ contentKey: 2 })
    expect(calls).toEqual([])
  })
})

describe('what stops the viewport following', () => {
  const harness = () => {
    const captured: { current: ReturnType<typeof usePinnedTranscript> | null } = {
      current: null,
    }
    function Harness() {
      const value = usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey: null,
      })
      useEffect(() => {
        captured.current = value
      }, [value])
      return createElement(
        'div',
        { ref: value.scrollRef },
        createElement('div', { ref: value.contentRef }),
        createElement('div', { ref: value.sentinelRef }),
      )
    }
    const { container } = render(createElement(Harness))
    const scroller = container.firstElementChild as HTMLDivElement
    Object.defineProperties(scroller, {
      offsetWidth: { configurable: true, value: 500 },
      clientWidth: { configurable: true, value: 488 },
    })
    scroller.getBoundingClientRect = () =>
      ({ right: 500, left: 0, top: 0, bottom: 400 }) as DOMRect
    return { captured, scroller }
  }

  it('detaches on an upward wheel and offers the way back', () => {
    const { captured, scroller } = harness()
    expect(captured.current?.showScrollButton).toBe(false)

    fireEvent.wheel(scroller, { deltaY: -20 })
    expect(captured.current?.isPinned()).toBe(false)
    expect(captured.current?.showScrollButton).toBe(true)
  })

  it('ignores a downward wheel', () => {
    const { captured, scroller } = harness()
    fireEvent.wheel(scroller, { deltaY: 20 })
    expect(captured.current?.isPinned()).toBe(true)
  })

  it.each([
    ['ArrowUp', {}],
    ['PageUp', {}],
    ['Home', {}],
    [' ', { shiftKey: true }],
  ])('detaches on %s', (key, modifiers) => {
    const { captured, scroller } = harness()
    fireEvent.keyDown(scroller, { key, ...modifiers })
    expect(captured.current?.isPinned()).toBe(false)
  })

  it('leaves typing in an input alone', () => {
    const { captured, scroller } = harness()
    const input = document.createElement('input')
    scroller.appendChild(input)
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(captured.current?.isPinned()).toBe(true)
  })

  it('detaches when the scrollbar itself is grabbed', () => {
    const { captured, scroller } = harness()
    fireEvent.pointerDown(scroller, { clientX: 496 })
    expect(captured.current?.isPinned()).toBe(false)
  })

  it('reattaches once the bottom is back in view', () => {
    const { captured, scroller } = harness()
    fireEvent.wheel(scroller, { deltaY: -20 })
    expect(captured.current?.isPinned()).toBe(false)

    reportBottomVisible(true)
    expect(captured.current?.isPinned()).toBe(true)
    expect(captured.current?.showScrollButton).toBe(false)
  })

  it('does not detach just because content pushed the bottom away', () => {
    const { captured } = harness()
    // This is what a streaming turn looks like to the observer, and it
    // must not be mistaken for the reader scrolling up.
    reportBottomVisible(false)
    expect(captured.current?.isPinned()).toBe(true)
    expect(captured.current?.showScrollButton).toBe(false)
  })
})

describe('jumping to the newest content', () => {
  it('goes to the bottom when a new prompt is submitted', () => {
    const { result, rerender } = renderHook(
      ({ followKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey: 'session-1',
        followKey,
      }),
      { initialProps: { followKey: null as string | null } },
    )
    const { element, calls } = fakeScroller()
    result.current.scrollRef.current = element

    act(() => result.current.detach())
    calls.length = 0
    rerender({ followKey: 'user-2' })

    expect(calls).toEqual([{ top: 1_000, behavior: 'auto' }])
    expect(result.current.isPinned()).toBe(true)
  })

  it('goes to the bottom on a session change', () => {
    const { result, rerender } = renderHook(
      ({ resetKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey,
      }),
      { initialProps: { resetKey: 'session-1' } },
    )
    const { element, calls } = fakeScroller(1_413)
    result.current.scrollRef.current = element

    calls.length = 0
    rerender({ resetKey: 'session-2' })
    expect(calls).toEqual([{ top: 1_413, behavior: 'auto' }])
  })

  it('still follows after StrictMode replays mount effects', () => {
    const wrapper = ({ children }: PropsWithChildren) =>
      createElement(StrictMode, null, children)
    const { result, rerender } = renderHook(
      ({ resetKey }) => usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey,
      }),
      { initialProps: { resetKey: 'session-1' }, wrapper },
    )
    const { element, calls } = fakeScroller(1_413)
    result.current.scrollRef.current = element

    calls.length = 0
    rerender({ resetKey: 'session-2' })
    expect(calls.at(-1)).toEqual({ top: 1_413, behavior: 'auto' })
  })

  it('animates only when the reader asked for it', () => {
    const { result } = renderHook(() => usePinnedTranscript({
      isEmpty: false,
      contentKey: 1,
      resetKey: null,
    }))
    const { element, calls } = fakeScroller()
    result.current.scrollRef.current = element

    act(() => result.current.scrollToBottom(true))
    expect(calls.at(-1)).toEqual({ top: 1_000, behavior: 'smooth' })

    act(() => result.current.scrollToBottom())
    expect(calls.at(-1)).toEqual({ top: 1_000, behavior: 'auto' })
  })
})

describe('a newly submitted prompt', () => {
  it('sits at the top of the viewport and stops bottom-follow', () => {
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
    const { element, calls } = fakeScroller()
    element.scrollTop = 120
    const anchor = document.createElement('div')
    anchor.dataset.transcriptTopAnchor = 'true'
    anchor.getBoundingClientRect = () => ({ top: 260 }) as DOMRect
    element.getBoundingClientRect = () => ({ top: 60 }) as DOMRect
    element.appendChild(anchor)
    result.current.scrollRef.current = element

    calls.length = 0
    rerender({ topAnchorKey: 'user-2' })
    act(() => {
      for (const callback of frames.values()) callback(16)
      frames.clear()
    })

    // scrollTop 120 + (anchor 260 - container 60) puts the prompt at the top.
    expect(calls).toEqual([{ top: 320 }])
    expect(result.current.isPinned()).toBe(false)
    expect(result.current.showScrollButton).toBe(false)
  })
})

describe('an emptied transcript', () => {
  it('returns to the top, following', () => {
    const { result, rerender } = renderHook(
      ({ isEmpty }) => usePinnedTranscript({
        isEmpty,
        contentKey: 1,
        resetKey: null,
      }),
      { initialProps: { isEmpty: false } },
    )
    const { element } = fakeScroller()
    element.scrollTop = 500
    result.current.scrollRef.current = element

    act(() => result.current.detach())
    rerender({ isEmpty: true })

    expect(element.scrollTop).toBe(0)
    expect(result.current.isPinned()).toBe(true)
  })
})

describe('scroll frame reporting', () => {
  it('reports the scroller once per frame for history loading', () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const onScrollFrame = vi.fn()

    function Harness() {
      const value = usePinnedTranscript({
        isEmpty: false,
        contentKey: 1,
        resetKey: null,
        onScrollFrame,
      })
      return createElement(
        'div',
        { ref: value.scrollRef },
        createElement('div', { ref: value.contentRef }),
        createElement('div', { ref: value.sentinelRef }),
      )
    }
    const { container } = render(createElement(Harness))
    const scroller = container.firstElementChild as HTMLDivElement

    fireEvent.scroll(scroller)
    fireEvent.scroll(scroller)
    act(() => {
      while (frames.length > 0) frames.shift()?.(16)
    })

    // Two events, one frame: coalesced.
    expect(onScrollFrame).toHaveBeenCalledTimes(1)
    expect(onScrollFrame).toHaveBeenCalledWith(scroller)
  })
})
