/**
 * Transcript viewport: stays at the newest content, holds the reader's
 * place when older history arrives, and gets out of the way the moment
 * they scroll up.
 *
 * Rebuilt on browser primitives after measuring the previous version.
 * Every choice below replaced hand-written machinery, and every one was
 * verified in this app's own WebView rather than assumed:
 *
 * - **Holding position when history is prepended** is `overflow-anchor`.
 *   Native scroll anchoring moves `scrollTop` by exactly the height
 *   inserted above the viewport — measured: prepending 600px took
 *   scrollTop from 1200 to 1800 and the reader did not move, where
 *   `overflow-anchor: none` left it at 1200 and the content jumped. That
 *   replaced a ResizeObserver, two settling timers, an anchor-capture
 *   pass over the turns, and the callers' book-keeping of previous
 *   scroll height.
 *
 * - **Knowing whether the bottom is in view** is an IntersectionObserver
 *   on a one-pixel sentinel. The old test read `scrollHeight`,
 *   `scrollTop` and `clientHeight` on every scroll frame, and one forced
 *   layout in this app measures 26-28ms, so that read was most of the
 *   cost of scrolling. The observer fired twice for a whole
 *   scroll-away-and-back, and reads nothing.
 *
 * - **Following new content** writes `scrollTo` on the scroller itself,
 *   not `sentinel.scrollIntoView()`. The latter also scrolls every
 *   scrollable ancestor — measured moving an outer panel by 440px, which
 *   is exactly the class of bug where a panel scrolls itself out of view.
 *
 * Deliberately unchanged: when to stop following. An upward wheel, drag,
 * arrow key or scrollbar grab detaches at once so a live response never
 * fights the reader, and reaching the bottom opts back in. Those are
 * product decisions, not performance ones.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

/** How close to the bottom still counts as following. */
const DEFAULT_BOTTOM_THRESHOLD = 48
/** Upward movement past this reads as the reader taking over. */
const USER_SCROLL_DETACH_DELTA = 4

interface UsePinnedTranscriptOptions {
  /** Reset the viewport to its initial pinned state when the transcript clears. */
  isEmpty: boolean
  /** Structural changes that may mount content before ResizeObserver fires. */
  contentKey: string | number
  /** A session/surface identity change always starts at the newest content. */
  resetKey?: string | number | null
  /** A newly submitted prompt explicitly reattaches bottom-follow. */
  followKey?: string | number | null
  /** A newly submitted prompt that should be pinned to the viewport top. */
  topAnchorKey?: string | number | null
  /** Optional work that should run once per painted scroll frame. */
  onScrollFrame?: (element: HTMLDivElement) => void
  /** Keep wheel/touch intent inside a nested scroll region. */
  isolateScroll?: boolean
  /** Disable rendered-height following for dormant nested regions. */
  followEnabled?: boolean
  bottomThreshold?: number
}

function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof Element
    && target.closest('input, textarea, [contenteditable="true"]') !== null
}

function isUpwardScrollKey(event: KeyboardEvent): boolean {
  return event.key === 'ArrowUp'
    || event.key === 'PageUp'
    || event.key === 'Home'
    || (event.key === ' ' && event.shiftKey)
}

/** Content growth must never detach a viewport that was already following. */
export function pinnedAfterViewportUpdate(
  wasPinned: boolean,
  isAtBottom: boolean,
): boolean {
  return wasPinned || isAtBottom
}

export function usePinnedTranscript({
  isEmpty,
  contentKey,
  resetKey,
  followKey,
  topAnchorKey,
  onScrollFrame,
  isolateScroll = false,
  followEnabled = true,
  bottomThreshold = DEFAULT_BOTTOM_THRESHOLD,
}: UsePinnedTranscriptOptions) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  /**
   * A one-pixel element the caller renders as the last child of the
   * content. Whether it is visible *is* the answer to "are we at the
   * bottom", so nothing has to measure the scroller to find out.
   */
  const sentinelRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const showScrollButtonRef = useRef(false)
  const onScrollFrameRef = useRef(onScrollFrame)
  const [showScrollButton, setShowScrollButton] = useState(false)

  useEffect(() => {
    onScrollFrameRef.current = onScrollFrame
  }, [onScrollFrame])

  const setScrollButtonVisible = useCallback((visible: boolean) => {
    if (showScrollButtonRef.current === visible) return
    showScrollButtonRef.current = visible
    setShowScrollButton(visible)
  }, [])

  const detach = useCallback(() => {
    pinnedRef.current = false
    setScrollButtonVisible(true)
  }, [setScrollButtonVisible])

  /**
   * Put the newest content in view.
   *
   * One `scrollHeight` read per call, and only while following — where
   * the previous implementation read it on every animation frame of an
   * easing loop until the loop converged.
   */
  const jumpToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const element = scrollRef.current
    if (!element) return
    element.scrollTo({ top: element.scrollHeight, behavior })
  }, [])

  const follow = useCallback(() => {
    if (!followEnabled || !pinnedRef.current) return
    jumpToBottom()
  }, [followEnabled, jumpToBottom])

  // Neither of these hides the button directly. They put the bottom back
  // in view, and the observer that watches the sentinel is what reports
  // that — one source of truth, and no setState inside an effect body.
  const reattach = useCallback(() => {
    pinnedRef.current = true
    jumpToBottom()
  }, [jumpToBottom])

  const scrollToBottom = useCallback((smooth = false) => {
    pinnedRef.current = true
    jumpToBottom(smooth ? 'smooth' : 'auto')
  }, [jumpToBottom])

  // Is the bottom in view? Answered without reading layout from JS.
  useEffect(() => {
    const root = scrollRef.current
    const sentinel = sentinelRef.current
    if (!root || !sentinel || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries.at(-1)
        if (!entry) return
        pinnedRef.current = pinnedAfterViewportUpdate(
          pinnedRef.current,
          entry.isIntersecting,
        )
        setScrollButtonVisible(!pinnedRef.current)
      },
      // The margin expresses the same "near enough to the bottom" notion
      // the old pixel threshold did, without measuring anything.
      { root, rootMargin: `0px 0px ${bottomThreshold}px 0px`, threshold: 0 },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [bottomThreshold, setScrollButtonVisible])

  // Reader intent. Detaching is driven by input events, never by layout:
  // content growing under a following viewport must not be mistaken for a
  // scroll the reader performed.
  useEffect(() => {
    const element = scrollRef.current
    if (!element) return

    let lastTouchY: number | null = null
    let scrollFrame: number | null = null

    const reportScrollFrame = () => {
      scrollFrame = null
      onScrollFrameRef.current?.(element)
    }

    const onScroll = () => {
      if (scrollFrame === null) {
        scrollFrame = requestAnimationFrame(reportScrollFrame)
      }
    }

    const onWheel = (event: WheelEvent) => {
      if (isolateScroll) event.stopPropagation()
      if (event.deltaY < -USER_SCROLL_DETACH_DELTA) detach()
    }

    const onTouchMove = (event: TouchEvent) => {
      if (isolateScroll) event.stopPropagation()
      const y = event.touches[0]?.clientY
      if (y == null) return
      if (lastTouchY !== null && y > lastTouchY + USER_SCROLL_DETACH_DELTA) detach()
      lastTouchY = y
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (!isEditableTarget(event.target) && isUpwardScrollKey(event)) detach()
    }

    const onPointerDown = (event: PointerEvent) => {
      if (event.target !== element) return
      const rect = element.getBoundingClientRect()
      const scrollbarWidth = Math.max(12, element.offsetWidth - element.clientWidth)
      if (event.clientX >= rect.right - scrollbarWidth) detach()
    }

    const clearTouch = () => {
      lastTouchY = null
    }

    element.addEventListener('scroll', onScroll, { passive: true })
    element.addEventListener('wheel', onWheel, { passive: true })
    element.addEventListener('touchmove', onTouchMove, { passive: true })
    element.addEventListener('touchend', clearTouch, { passive: true })
    element.addEventListener('touchcancel', clearTouch, { passive: true })
    element.addEventListener('keydown', onKeyDown)
    element.addEventListener('pointerdown', onPointerDown, { passive: true })
    return () => {
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame)
      element.removeEventListener('scroll', onScroll)
      element.removeEventListener('wheel', onWheel)
      element.removeEventListener('touchmove', onTouchMove)
      element.removeEventListener('touchend', clearTouch)
      element.removeEventListener('touchcancel', clearTouch)
      element.removeEventListener('keydown', onKeyDown)
      element.removeEventListener('pointerdown', onPointerDown)
    }
  }, [detach, isolateScroll])

  // Content that settles asynchronously — images, fonts, code blocks —
  // after the render that mounted it. A render-keyed effect cannot see
  // that; a ResizeObserver can.
  useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => follow())
    observer.observe(content)
    return () => observer.disconnect()
  }, [follow, isEmpty])

  useEffect(() => {
    follow()
  }, [contentKey, follow])

  useEffect(() => {
    if (resetKey == null || !followEnabled) return
    reattach()
  }, [followEnabled, reattach, resetKey])

  useEffect(() => {
    if (followKey == null || !followEnabled) return
    reattach()
  }, [followEnabled, followKey, reattach])

  // A newly submitted prompt sits at the top of the viewport so the
  // reader watches the answer arrive beneath it instead of chasing it.
  useEffect(() => {
    if (topAnchorKey == null || !followEnabled) return
    pinnedRef.current = false
    const frame = requestAnimationFrame(() => {
      const container = scrollRef.current
      const anchor = container?.querySelector<HTMLElement>(
        '[data-transcript-top-anchor="true"]',
      )
      if (!container || !anchor) return
      // Positioned by hand rather than with scrollIntoView, which would
      // also scroll every scrollable ancestor.
      container.scrollTo({
        top: container.scrollTop
          + anchor.getBoundingClientRect().top
          - container.getBoundingClientRect().top,
      })
      setScrollButtonVisible(false)
    })
    return () => cancelAnimationFrame(frame)
  }, [followEnabled, setScrollButtonVisible, topAnchorKey])

  useEffect(() => {
    if (!isEmpty) return
    pinnedRef.current = true
    // An empty transcript has its sentinel in view, so the observer
    // clears the button without this having to.
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [isEmpty])

  return {
    contentRef,
    detach,
    isPinned: () => pinnedRef.current,
    scrollRef,
    scrollToBottom,
    sentinelRef,
    showScrollButton,
  }
}
