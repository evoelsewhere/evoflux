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
 * - **Putting a newly submitted prompt at the top** is a measured spacer,
 *   not a second scroll mode. `syncRunway` sizes the runway element so that
 *   everything below the newest prompt is exactly one viewport tall, which
 *   makes "scrolled to the bottom" and "prompt at the top" the same
 *   position. The previous version scrolled the prompt up by hand one frame
 *   after the commit and turned bottom-follow off for the rest of the turn;
 *   measured in this app, all three of its failure modes were visible on
 *   every send. The frame in between painted the prompt 244px *above* the
 *   viewport. The trailing turn's fixed 70svh runway then collapsed under
 *   it — scrollHeight 3844 → 3471 on the very next frame — and left the
 *   prompt 217px *below* the top instead of at it. And a reply longer than
 *   the viewport streamed off the bottom edge with scrollTop frozen at 2464
 *   while scrollHeight ran past 4700, because nothing ever re-armed follow.
 *   The spacer has no frame in between, nothing to fight `overflow-anchor`
 *   over, and it reaches zero exactly when the reply outgrows the viewport —
 *   at which point ordinary bottom-follow takes over on its own.
 *
 * Deliberately unchanged: when to stop following. An upward wheel, drag,
 * arrow key or scrollbar grab detaches at once so a live response never
 * fights the reader, and reaching the bottom opts back in. Those are
 * product decisions, not performance ones.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/** How close to the bottom still counts as following. */
const DEFAULT_BOTTOM_THRESHOLD = 48
/** Upward movement past this reads as the reader taking over. */
const USER_SCROLL_DETACH_DELTA = 4
/** Sub-pixel churn must not rewrite the runway on every streamed chunk. */
const RUNWAY_EPSILON_PX = 1
/**
 * A scroll position past the end is clamped to the end by the engine, so
 * following costs no `scrollHeight` read — which matters because the runway
 * is resized in the same callback and a read after that write would force
 * the layout this hook was rebuilt to avoid.
 */
export const SCROLL_TO_END = 1e9

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

/**
 * How tall the scrolled content actually is.
 *
 * `scrollHeight` answers that exactly — but never reports less than one
 * viewport, and a transcript shorter than the viewport is exactly the case
 * the runway has to reason about. Measured through the clamp, each pass
 * overstates what sits below the prompt and the runway crawls upward a
 * padding's worth at a time instead of landing in one step. Below the clamp
 * the children are measured directly; that path is off the streaming one,
 * since an open runway always overflows.
 */
function scrollContentHeight(container: HTMLElement): number {
  if (container.scrollHeight > container.clientHeight) return container.scrollHeight
  const top = container.getBoundingClientRect().top
  let bottom = 0
  for (const child of container.children) {
    bottom = Math.max(bottom, child.getBoundingClientRect().bottom - top)
  }
  // The scroller's own bottom padding trails every child.
  return bottom
    + Number.parseFloat(getComputedStyle(container).paddingBottom || '0')
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
  /**
   * A spacer the caller renders between the transcript and the sentinel.
   * Its height is the whole of the "newest prompt sits at the top" behaviour
   * — see `syncRunway`.
   */
  const runwayRef = useRef<HTMLDivElement>(null)
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
   * No layout read at all: the engine clamps a past-the-end position to the
   * end. The previous implementation read `scrollHeight` on every animation
   * frame of an easing loop until the loop converged.
   */
  const jumpToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const element = scrollRef.current
    if (!element) return
    element.scrollTo({ top: SCROLL_TO_END, behavior })
  }, [])

  /**
   * Size the spacer that sits between the newest prompt and the end of the
   * transcript, so that everything below that prompt is exactly one viewport
   * tall.
   *
   * That one invariant is what puts a newly submitted prompt at the top:
   * with it, the bottom of the scroll range *is* the position where the
   * prompt sits at the top of the viewport, so the ordinary bottom-follow
   * above needs no special case and there is no second scroll pass to go
   * wrong. It also expires on its own — as the answer grows the spacer
   * shrinks by the same amount, reaching zero the moment the answer fills
   * the viewport by itself, and from there following the bottom simply keeps
   * the newest output in view.
   *
   * Capped at the transcript above the prompt, because that is all the
   * runway can ever buy: raising the prompt by `promptTop` is the whole
   * point of holding space open, and space beyond that is blank nobody
   * asked for. Uncapped, a brand new chat held 558px of white open to gain
   * a 16px scroll range — measured, with the scroll-to-latest button along
   * with it. Capped, a transcript with nothing above the prompt opens no
   * runway and does not scroll at all, and a long one is unaffected: its
   * `promptTop` runs to thousands of pixels, so the viewport-sized runway
   * is still the smaller of the two.
   *
   * Measured against the end of the scrolled *content*, not against the last
   * element: the scroller's own padding lives past the sentinel, and
   * measuring to the sentinel left the runway that much too tall — 17px in
   * this app, which is 17px of the prompt hanging off the top of the
   * viewport once the transcript is scrolled to the end.
   *
   * Reads only: `scrollTop`, `clientHeight`, the content height and two
   * rects. It runs from the ResizeObserver callback, where the layout is
   * already clean, and writes after every read.
   */
  const syncRunway = useCallback(() => {
    const runway = runwayRef.current
    const container = scrollRef.current
    if (!runway || !container) return
    const current = runway.getBoundingClientRect().height
    const anchor = container.querySelector<HTMLElement>(
      '[data-transcript-top-anchor="true"]',
    )
    if (!anchor) {
      if (current > RUNWAY_EPSILON_PX) runway.style.blockSize = '0px'
      return
    }
    const promptTop = container.scrollTop
      + anchor.getBoundingClientRect().top
      - container.getBoundingClientRect().top
    // Everything between the top of the prompt and the end of the
    // transcript, with the spacer's own contribution taken back out.
    const occupied = scrollContentHeight(container) - promptTop - current
    const next = Math.max(
      0,
      Math.min(container.clientHeight - occupied, promptTop),
    )
    if (Math.abs(next - current) < RUNWAY_EPSILON_PX) return
    runway.style.blockSize = `${next}px`
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
  // that; a ResizeObserver can. The scroller is observed too, so a window
  // resize re-derives the runway against the new viewport height.
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return
    const content = contentRef.current
    const container = scrollRef.current
    if (!content && !container) return
    // Read-then-write, in that order: the runway is sized from a clean
    // layout and `follow` needs no read of its own, so a streamed chunk
    // still costs one layout pass and not two.
    const observer = new ResizeObserver(() => {
      syncRunway()
      follow()
    })
    if (content) observer.observe(content)
    if (container) observer.observe(container)
    return () => observer.disconnect()
  }, [follow, isEmpty, syncRunway])

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

  // A newly submitted prompt sits at the top of the viewport so the reader
  // watches the answer arrive beneath it instead of chasing it. The runway
  // is what puts it there, so all this has to do is size the runway for the
  // new prompt and stay at the bottom. Before paint, in one pass: the
  // version that scrolled the prompt up a frame later painted it off the
  // top of the viewport in between.
  useLayoutEffect(() => {
    if (topAnchorKey == null || !followEnabled) return
    syncRunway()
    pinnedRef.current = true
    jumpToBottom()
    // The button is not hidden from here. The bottom is now in view, and the
    // observer that watches the sentinel is what reports that — one source of
    // truth, and no setState inside an effect body.
  }, [followEnabled, jumpToBottom, syncRunway, topAnchorKey])

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
    runwayRef,
    scrollRef,
    scrollToBottom,
    sentinelRef,
    showScrollButton,
  }
}
