/**
 * ```chart fence wrapper (Intelligent UI feature D).
 *
 * Parses and validates the raw spec, then lazily renders ChartBlock —
 * the Recharts chunk never lands in the initial bundle. Invalid specs
 * degrade: a skeleton while the stream is still moving, the caller's
 * CodeBlock fallback plus a one-line notice once it settles.
 */

import { Suspense, lazy, useMemo, type ReactNode } from 'react'

import { parseChartSpec } from './chart-spec'
import type { ChartBlockProps } from './ChartBlock'

const ChartBlock = lazy(() => import('./ChartBlock'))

export interface ChartFenceProps {
  rawText: string
  streaming: boolean
  fallback: ReactNode
}

export function FenceSkeleton() {
  return (
    <div
      className="my-3 h-[260px] w-full animate-pulse rounded-xl border border-(--color-border-subtle) bg-(--bg-card)"
      aria-hidden="true"
    />
  )
}

export default function ChartFence({ rawText, streaming, fallback }: ChartFenceProps) {
  const chart = useMemo(() => parseChartSpec(rawText), [rawText])

  if (!chart) {
    if (streaming) return <FenceSkeleton />
    return (
      <>
        {fallback}
        <p className="mt-1 text-xs text-(--color-text-muted)">Invalid chart spec</p>
      </>
    )
  }

  return (
    <Suspense fallback={<FenceSkeleton />}>
      <ChartBlock spec={chart} />
    </Suspense>
  )
}

export type { ChartBlockProps }
