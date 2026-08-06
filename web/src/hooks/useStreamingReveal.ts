import { startTransition, useEffect, useRef, useState } from 'react'

const STREAM_FRAME_MS = 24

/**
 * Advance quickly enough to stay close to the network stream while smoothing
 * bursty provider chunks into a small number of visual frames.
 */
export function nextStreamingRevealLength(
  currentLength: number,
  targetLength: number,
): number {
  const lag = Math.max(0, targetLength - currentLength)
  if (lag <= 12) return targetLength
  const maxStep = lag > 600 ? 96 : 48
  const step = Math.min(maxStep, Math.max(4, Math.ceil(lag * 0.3)))
  return Math.min(targetLength, currentLength + step)
}

function preserveUnicodeBoundary(content: string, length: number): number {
  if (length <= 0 || length >= content.length) return length
  const previous = content.charCodeAt(length - 1)
  const next = content.charCodeAt(length)
  const splitSurrogatePair =
    previous >= 0xd800 &&
    previous <= 0xdbff &&
    next >= 0xdc00 &&
    next <= 0xdfff
  return splitSurrogatePair ? length + 1 : length
}

/** Avoid exposing half a combining sequence while a token is being painted. */
export function streamingRevealBoundary(content: string, length: number): number {
  const safeLength = preserveUnicodeBoundary(content, length)
  if (safeLength <= 0 || safeLength >= content.length) return safeLength

  // Combining marks and variation selectors belong to the preceding glyph.
  // Include them in the same frame so accents/emoji never visibly mutate.
  let boundary = safeLength
  while (boundary < content.length) {
    const codePoint = content.codePointAt(boundary)
    if (codePoint === undefined) break
    const character = String.fromCodePoint(codePoint)
    if (!/[\p{Mark}\uFE0E\uFE0F]/u.test(character)) break
    boundary += character.length
  }
  return boundary
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Smooth an append-only streaming string without delaying finalized content.
 *
 * Raw SSE chunks can arrive several times inside one paint. The hook keeps
 * the newest target in a ref, commits at most once per visual frame window,
 * and uses a catch-up step for large bursts. React transitions keep Markdown
 * parsing below input and scroll interactions in scheduling priority.
 */
export function useStreamingReveal(
  content: string,
  isStreaming: boolean,
  isRenderActive = true,
): string {
  const initial = isStreaming && !prefersReducedMotion() ? '' : content
  const [displayedContent, setDisplayedContent] = useState(initial)
  const displayedRef = useRef(initial)
  const targetRef = useRef(content)
  const streamingRef = useRef(isStreaming)
  const renderActiveRef = useRef(isRenderActive)
  const frameRef = useRef<number | null>(null)
  const lastPaintRef = useRef(0)
  const scheduleRef = useRef<() => void>(() => {})

  useEffect(() => {
    let active = true

    const schedule = () => {
      if (!active || frameRef.current !== null) return
      frameRef.current = requestAnimationFrame(tick)
    }

    const tick = (timestamp: number) => {
      frameRef.current = null
      if (!active || !streamingRef.current || !renderActiveRef.current) return

      const target = targetRef.current
      const current = displayedRef.current
      if (!target.startsWith(current)) {
        displayedRef.current = target
        setDisplayedContent(target)
        return
      }
      if (current.length >= target.length) return
      if (timestamp - lastPaintRef.current < STREAM_FRAME_MS) {
        schedule()
        return
      }

      const rawLength = nextStreamingRevealLength(current.length, target.length)
      const nextLength = streamingRevealBoundary(target, rawLength)
      const next = target.slice(0, nextLength)
      displayedRef.current = next
      lastPaintRef.current = timestamp
      startTransition(() => setDisplayedContent(next))

      if (nextLength < target.length) schedule()
    }

    scheduleRef.current = schedule
    if (renderActiveRef.current) schedule()

    return () => {
      active = false
      scheduleRef.current = () => {}
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [])

  useEffect(() => {
    targetRef.current = content
    streamingRef.current = isStreaming
    renderActiveRef.current = isRenderActive

    if (!isStreaming || prefersReducedMotion()) {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
      displayedRef.current = content
      setDisplayedContent(content) // eslint-disable-line react-hooks/set-state-in-effect
      return
    }

    // When the live tail is well outside the viewport, keep only the newest
    // authoritative target in a ref. This avoids parsing/reconciling invisible
    // Markdown on every SSE frame; becoming visible schedules a normal catch-up.
    if (!isRenderActive) {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
      return
    }

    if (!content.startsWith(displayedRef.current)) {
      // A provider correction (or reused component) is not append-only.
      // Show the authoritative value directly instead of flashing blank and
      // replaying the whole response from the beginning.
      displayedRef.current = content
      setDisplayedContent(content)
    }
    scheduleRef.current()
  }, [content, isRenderActive, isStreaming])

  return displayedContent
}
