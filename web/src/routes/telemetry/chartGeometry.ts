/**
 * Shared plotting helpers for the telemetry charts.
 *
 * Their own module rather than `charts.tsx`: a file that exports both
 * components and plain functions loses fast refresh for every component in it.
 */

import { useEffect, useRef, useState } from 'react'

import type { ObservabilitySummary } from '@/api/client'

export const DEFAULT_WIDTH = 760

export function formatBucket(
  value: string,
  bucketSize: ObservabilitySummary['bucket_size'],
) {
  const date = new Date(value)
  return new Intl.DateTimeFormat(
    undefined,
    bucketSize === 'hour'
      ? { hour: '2-digit', minute: '2-digit' }
      : { month: 'short', day: 'numeric' },
  ).format(date)
}

/** Round an axis maximum up to 1, 2, 5 or 10 times a power of ten. */
export function niceMax(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1
  const exponent = Math.floor(Math.log10(value))
  const magnitude = 10 ** exponent
  const normalized = value / magnitude
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return nice * magnitude
}

export function useChartWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(DEFAULT_WIDTH)

  useEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return

    const update = (nextWidth: number) => {
      if (nextWidth > 0) setWidth(Math.max(Math.round(nextWidth), 280))
    }
    update(element.getBoundingClientRect().width)
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) update(entry.contentRect.width)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return [ref, width]
}
