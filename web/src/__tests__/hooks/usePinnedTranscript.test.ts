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
  SCROLL_TO_END,
  pinnedAfterViewportUpdate,
  usePinnedTranscript,
} from '@/hooks/usePinnedTranscript'

type ObserverCallback = (entries: { isIntersecting: boolean }[]) => void

/** Lets a test say "the bottom came into view" without a layout engine. */
const observers: { callback: ObserverCallback; targets: Element[] }[] = []
/** Lets a test say "a streamed chunk landed" without a layout engine. */
const resizeCallbacks: (() => void)[] = []

function reportContentResized(): void {
  act(() => {
    for (const callback of [...resizeCallbacks]) callback()
  })
}

function reportBottomVisible(isIntersecting: boolean): void {
  act(() => {
    for (const observer of observers) {
      observer.callback([{ isIntersecting }])
    }
  })
}

beforeEach(() => {
  observers.length = 0
  resizeCallbacks.length = 0
  vi.stubGlobal(
    'ResizeObserver',
    class {
      callback: () => void
      constructor(callback: () => void) {
        this.callback = callback
        resizeCallbacks.push(callback)
      }
      observe() {}
      disconnect() {
        const index = resizeCallbacks.indexOf(this.callback)
        if (index !== -1) resizeCallbacks.splice(index, 1)
      }
      unobserve() {}
    },
  )
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
    expect(calls).toEqual([{ top: SCROLL_TO_END, behavior: 'auto' }])
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

    expect(calls).toEqual([{ top: SCROLL_TO_END, behavior: 'auto' }])
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
    expect(calls).toEqual([{ top: SCROLL_TO_END, behavior: 'auto' }])
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
    expect(calls.at(-1)).toEqual({ top: SCROLL_TO_END, behavior: 'auto' })
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
    expect(calls.at(-1)).toEqual({ top: SCROLL_TO_END, behavior: 'smooth' })

    act(() => result.current.scrollToBottom())
    expect(calls.at(-1)).toEqual({ top: SCROLL_TO_END, behavior: 'auto' })
  })
})

/**
 * The runway harness models the one thing the hook actually computes: a
 * spacer whose height makes everything below the newest prompt exactly one
 * viewport tall. The scroll range grows with the spacer — which is what
 * keeps `syncRunway` self-correcting rather than accumulating its own past
 * output. The prompt sits at offset 0, so `scrollHeight` is exactly what is
 * below it.
 */
function runwayHarness({
  clientHeight = 400,
  belowPrompt = 60,
  abovePrompt = 5_000,
}) {
  const captured: { current: ReturnType<typeof usePinnedTranscript> | null } = {
    current: null,
  }
  const scrolls: ScrollToOptions[] = []
  const state = { belowPrompt, withAnchor: true }

  function Harness({ topAnchorKey }: { topAnchorKey: string | null }) {
    const value = usePinnedTranscript({
      isEmpty: false,
      contentKey: 1,
      resetKey: null,
      topAnchorKey,
    })
    useEffect(() => {
      captured.current = value
    }, [value])
    return createElement(
      'div',
      { ref: value.scrollRef },
      createElement(
        'div',
        { ref: value.contentRef },
        state.withAnchor
          ? createElement('div', {
            key: 'anchor',
            'data-transcript-top-anchor': 'true',
          })
          : null,
        createElement('div', { key: 'runway', ref: value.runwayRef }),
        createElement('div', { key: 'sentinel', ref: value.sentinelRef }),
      ),
    )
  }

  const { container, rerender } = render(
    createElement(Harness, { topAnchorKey: null }),
  )
  const scroller = container.firstElementChild as HTMLDivElement
  const runway = captured.current!.runwayRef.current as HTMLDivElement
  const runwayHeight = () => Number.parseFloat(runway.style.blockSize) || 0
  // The transcript above the prompt is already scrolled past, so the prompt
  // sits at the top of the viewport and what remains below it is whatever
  // the turn occupies plus the spacer holding the rest open.
  const contentHeight = () =>
    abovePrompt + state.belowPrompt + runwayHeight()
  Object.defineProperties(scroller, {
    clientHeight: { configurable: true, value: clientHeight },
    scrollTop: { configurable: true, value: abovePrompt, writable: true },
    // Like a real scroller, this never reports less than one viewport.
    scrollHeight: {
      configurable: true,
      get: () => Math.max(clientHeight, contentHeight()),
    },
  })
  scroller.getBoundingClientRect = () => ({ top: 0 }) as DOMRect
  // What the hook falls back to when the transcript is shorter than the
  // viewport and `scrollHeight` is therefore clamped.
  const contentEl = scroller.firstElementChild as HTMLDivElement
  contentEl.getBoundingClientRect = () => ({ bottom: contentHeight() }) as DOMRect
  scroller.scrollTo = ((options: ScrollToOptions) => {
    scrolls.push(options)
  }) as typeof scroller.scrollTo

  runway.getBoundingClientRect = () => ({ height: runwayHeight() }) as DOMRect
  const anchor = container.querySelector<HTMLElement>(
    '[data-transcript-top-anchor="true"]',
  )
  if (anchor) anchor.getBoundingClientRect = () => ({ top: 0 }) as DOMRect

  return {
    captured,
    runwayHeight,
    scrolls,
    state,
    submit: (topAnchorKey: string) =>
      rerender(createElement(Harness, { topAnchorKey })),
  }
}

describe('the runway under a newly submitted prompt', () => {
  it('opens exactly enough room for the prompt to reach the top', () => {
    const harness = runwayHarness({ clientHeight: 400, belowPrompt: 60 })
    harness.submit('user-2')

    // 60px of prompt and empty turn, 340px of runway: one viewport below the
    // prompt, so the bottom of the scroll range is the prompt at the top.
    expect(harness.runwayHeight()).toBe(340)
  })

  it('stays at the bottom rather than running a scroll pass of its own', () => {
    const harness = runwayHarness({ clientHeight: 400, belowPrompt: 60 })
    harness.scrolls.length = 0
    harness.submit('user-2')

    expect(harness.scrolls).toEqual([{ top: SCROLL_TO_END, behavior: 'auto' }])
    // The version this replaced turned follow off here, which is why a reply
    // longer than the viewport used to stream off the bottom edge unwatched.
    expect(harness.captured.current?.isPinned()).toBe(true)
  })

  it('gives back the room as the answer grows into it', () => {
    const harness = runwayHarness({ clientHeight: 400, belowPrompt: 60 })
    harness.submit('user-2')
    expect(harness.runwayHeight()).toBe(340)

    // A streamed chunk lands: the same prompt, 190px more answer under it.
    harness.state.belowPrompt = 250
    reportContentResized()
    // The total below the prompt is unchanged, so the prompt does not move
    // while the answer fills the space it was holding open.
    expect(harness.runwayHeight()).toBe(150)
  })

  it('closes once the answer fills the viewport, and follows from there', () => {
    const harness = runwayHarness({ clientHeight: 400, belowPrompt: 60 })
    harness.submit('user-2')

    harness.state.belowPrompt = 900
    harness.scrolls.length = 0
    reportContentResized()

    expect(harness.runwayHeight()).toBe(0)
    // Nothing special happens at the handover: the viewport was following the
    // bottom the whole time, and now the bottom is the newest output.
    expect(harness.captured.current?.isPinned()).toBe(true)
    expect(harness.scrolls).toEqual([{ top: SCROLL_TO_END, behavior: 'auto' }])
  })

  it('lands in one pass on a transcript shorter than the viewport', () => {
    // `scrollHeight` is pinned at one viewport here, which is what used to
    // make each pass overstate the answer and grow the runway by a padding
    // at a time instead of settling.
    const harness = runwayHarness({ clientHeight: 400, belowPrompt: 40 })
    harness.submit('user-2')
    expect(harness.runwayHeight()).toBe(360)

    reportContentResized()
    expect(harness.runwayHeight()).toBe(360)
  })

  it('holds no room open when there is nothing above the prompt to hide', () => {
    // A brand new chat: the prompt is already at the top, so a runway buys
    // nothing. Uncapped this opened most of a screen of white to gain a few
    // pixels of scroll range, scroll-to-latest button and all.
    const harness = runwayHarness({
      clientHeight: 400,
      belowPrompt: 60,
      abovePrompt: 16,
    })
    harness.submit('user-2')

    expect(harness.runwayHeight()).toBe(16)
  })

  it('holds no room open when there is no prompt to anchor', () => {
    const harness = runwayHarness({ clientHeight: 400, belowPrompt: 60 })
    harness.submit('user-2')
    expect(harness.runwayHeight()).toBe(340)

    harness.state.withAnchor = false
    harness.submit('user-3')
    reportContentResized()
    expect(harness.runwayHeight()).toBe(0)
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
