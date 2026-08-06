import { useCallback, useEffect, useRef, useState } from 'react'

const DEFAULT_BOTTOM_THRESHOLD = 48
const USER_SCROLL_DETACH_DELTA = 4
const FOLLOW_TIME_CONSTANT_MS = 52

interface UsePinnedTranscriptOptions {
  /** Reset the viewport to its initial pinned state when the transcript clears. */
  isEmpty: boolean
  /** Structural changes that may mount content before ResizeObserver fires. */
  contentKey: string | number
  /** A session/surface identity change always starts at the newest content. */
  resetKey?: string | number | null
  /** A newly submitted prompt explicitly reattaches bottom-follow. */
  followKey?: string | number | null
  /** Optional work that should run once per painted scroll frame. */
  onScrollFrame?: (element: HTMLDivElement) => void
  bottomThreshold?: number
}

/** Content growth must never detach a viewport that was already following. */
export function pinnedAfterViewportUpdate(wasPinned: boolean, isAtBottom: boolean): boolean {
  return wasPinned || isAtBottom
}

/** One frame of the pinned transcript's exponential bottom-follow. */
export function nextPinnedScrollTop(
  current: number,
  target: number,
  elapsedMs: number,
): number {
  if (target <= current) return target
  const elapsed = Math.min(48, Math.max(8, elapsedMs))
  const progress = 1 - Math.exp(-elapsed / FOLLOW_TIME_CONSTANT_MS)
  const next = current + ((target - current) * progress)
  return target - next < 0.75 ? target : next
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Codex-style transcript following.
 *
 * The viewport follows rendered height only while it is pinned. An upward
 * wheel, touch, scrollbar, or keyboard scroll detaches immediately, so a live
 * response never fights the reader. Reaching the bottom opts back in.
 */
export function usePinnedTranscript({
  isEmpty,
  contentKey,
  resetKey,
  followKey,
  onScrollFrame,
  bottomThreshold = DEFAULT_BOTTOM_THRESHOLD,
}: UsePinnedTranscriptOptions) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const showScrollButtonRef = useRef(false)
  const onScrollFrameRef = useRef(onScrollFrame)
  const followFrameRef = useRef<number | null>(null)
  const reattachFrameRef = useRef<number | null>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)

  useEffect(() => {
    onScrollFrameRef.current = onScrollFrame
  }, [onScrollFrame])

  const setScrollButtonVisible = useCallback((visible: boolean) => {
    if (showScrollButtonRef.current === visible) return
    showScrollButtonRef.current = visible
    setShowScrollButton(visible)
  }, [])

  const isAtBottom = useCallback(() => {
    const element = scrollRef.current
    if (!element) return true
    return element.scrollHeight - element.scrollTop - element.clientHeight <= bottomThreshold
  }, [bottomThreshold])

  const cancelFollow = useCallback(() => {
    if (followFrameRef.current === null) return
    cancelAnimationFrame(followFrameRef.current)
    followFrameRef.current = null
  }, [])

  const detach = useCallback(() => {
    pinnedRef.current = false
    cancelFollow()
    setScrollButtonVisible(true)
  }, [cancelFollow, setScrollButtonVisible])

  const followRenderedHeight = useCallback(() => {
    if (followFrameRef.current !== null) return
    let previousTimestamp: number | null = null

    const tick = (timestamp: number) => {
      followFrameRef.current = null
      const element = scrollRef.current
      if (!element || !pinnedRef.current) return

      const target = Math.max(0, element.scrollHeight - element.clientHeight)
      if (prefersReducedMotion()) {
        element.scrollTop = target
        return
      }

      const elapsed = previousTimestamp === null ? 16 : timestamp - previousTimestamp
      previousTimestamp = timestamp
      const next = nextPinnedScrollTop(element.scrollTop, target, elapsed)
      element.scrollTop = next
      if (Math.abs(target - next) > 0.5) {
        followFrameRef.current = requestAnimationFrame(tick)
      }
    }

    followFrameRef.current = requestAnimationFrame(tick)
  }, [])

  const scrollToBottom = useCallback((smooth = false) => {
    const element = scrollRef.current
    if (!element) return
    cancelFollow()
    pinnedRef.current = true
    setScrollButtonVisible(false)
    if (smooth) {
      element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' })
      return
    }
    element.scrollTop = element.scrollHeight
  }, [cancelFollow, setScrollButtonVisible])

  const restorePrependOffset = useCallback((previousScrollHeight: number) => {
    const element = scrollRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight - previousScrollHeight
  }, [])

  const reattach = useCallback(() => {
    pinnedRef.current = true
    cancelFollow()
    if (reattachFrameRef.current !== null) return
    reattachFrameRef.current = requestAnimationFrame(() => {
      reattachFrameRef.current = null
      setScrollButtonVisible(false)
      const element = scrollRef.current
      if (element) element.scrollTop = element.scrollHeight
    })
  }, [cancelFollow, setScrollButtonVisible])

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return

    let lastScrollTop = element.scrollTop
    let lastTouchY: number | null = null
    let scrollFrame: number | null = null

    const updateFromViewport = () => {
      scrollFrame = null
      const atBottom = isAtBottom()
      pinnedRef.current = pinnedAfterViewportUpdate(pinnedRef.current, atBottom)
      setScrollButtonVisible(!pinnedRef.current)
      onScrollFrameRef.current?.(element)
    }

    const scheduleViewportUpdate = () => {
      if (scrollFrame === null) scrollFrame = requestAnimationFrame(updateFromViewport)
    }

    const onScroll = () => {
      const nextScrollTop = element.scrollTop
      if (nextScrollTop < lastScrollTop - USER_SCROLL_DETACH_DELTA) detach()
      lastScrollTop = nextScrollTop
      scheduleViewportUpdate()
    }

    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < -USER_SCROLL_DETACH_DELTA) detach()
    }

    const onTouchMove = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY
      if (y == null) return
      if (lastTouchY !== null && y > lastTouchY + USER_SCROLL_DETACH_DELTA) detach()
      lastTouchY = y
    }

    const clearTouch = () => {
      lastTouchY = null
    }

    element.addEventListener('scroll', onScroll, { passive: true })
    element.addEventListener('wheel', onWheel, { passive: true })
    element.addEventListener('touchmove', onTouchMove, { passive: true })
    element.addEventListener('touchend', clearTouch, { passive: true })
    element.addEventListener('touchcancel', clearTouch, { passive: true })
    return () => {
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame)
      element.removeEventListener('scroll', onScroll)
      element.removeEventListener('wheel', onWheel)
      element.removeEventListener('touchmove', onTouchMove)
      element.removeEventListener('touchend', clearTouch)
      element.removeEventListener('touchcancel', clearTouch)
    }
  }, [detach, isAtBottom, setScrollButtonVisible])

  useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(followRenderedHeight)
    observer.observe(content)
    return () => observer.disconnect()
  }, [followRenderedHeight, isEmpty])

  useEffect(() => {
    followRenderedHeight()
  }, [contentKey, followRenderedHeight])

  useEffect(() => {
    if (resetKey == null) return
    reattach()
  }, [reattach, resetKey])

  useEffect(() => {
    if (followKey == null) return
    reattach()
  }, [followKey, reattach])

  useEffect(() => {
    if (!isEmpty) return
    pinnedRef.current = true
    if (scrollRef.current) scrollRef.current.scrollTop = 0
    const frame = requestAnimationFrame(() => setScrollButtonVisible(false))
    return () => cancelAnimationFrame(frame)
  }, [isEmpty, setScrollButtonVisible])

  useEffect(() => () => {
    cancelFollow()
    if (reattachFrameRef.current !== null) {
      cancelAnimationFrame(reattachFrameRef.current)
      reattachFrameRef.current = null
    }
  }, [cancelFollow])

  return {
    contentRef,
    detach,
    isPinned: () => pinnedRef.current,
    restorePrependOffset,
    scrollRef,
    scrollToBottom,
    showScrollButton,
  }
}
