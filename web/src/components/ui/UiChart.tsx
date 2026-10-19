/**
 * UiChart — shared renderer for `chart` blocks emitted by the `ui_block` tool.
 *
 * Merge re-point (spec §8.3): this body now validates the wire spec with
 * Stream 1's canonical `parseChartSpec` and lazily renders the shared
 * Recharts `ChartBlock`. `UiChartProps` keeps the stub-era contract
 * (`spec: unknown`, optional `title`) so the swap stayed a one-file edit.
 * Recharts only ever loads through the lazy chunk below.
 */

import { Suspense, lazy, useMemo, type ReactNode } from 'react'
import { BarChart3 } from 'lucide-react'

import { parseChartSpec, type ChartSpec } from '@/components/markdown/chart-spec'

const ChartBlock = lazy(() => import('@/components/markdown/ChartBlock'))

export interface UiChartProps {
  spec: unknown
  title?: string
}

/** Neutral shell shown while the Recharts chunk loads or when validation fails. */
function ChartShell({
  title,
  label,
  children,
}: {
  title?: string
  label: string
  children?: ReactNode
}) {
  return (
    <figure className="rounded-md border border-(--color-border) bg-(--bg-key) p-3">
      {title ? (
        <figcaption className="mb-2 flex items-center gap-1.5 text-xs font-medium text-(--color-text-muted)">
          <BarChart3 size={14} aria-hidden />
          {title}
        </figcaption>
      ) : null}
      {children ?? (
        <div
          className="h-[200px] w-full animate-pulse rounded-lg border border-(--color-border-subtle) bg-(--bg-card)"
          role="img"
          aria-label={label}
        />
      )}
    </figure>
  )
}

function describeSpec(spec: unknown): string {
  if (spec && typeof spec === 'object') {
    const keys = Object.keys(spec as Record<string, unknown>)
    if (keys.length > 0) return keys.slice(0, 6).join(', ')
  }
  return 'no chart spec'
}

export function UiChart({ spec, title }: UiChartProps) {
  // Wire spec arrives as a parsed object (UiChartBlock.spec is dict[str, Any]);
  // a raw JSON string is tolerated too. parseChartSpec re-validates either way.
  const chart: ChartSpec | null = useMemo(() => {
    const raw =
      typeof spec === 'string' ? spec : spec !== undefined && spec !== null ? JSON.stringify(spec) : ''
    return raw ? parseChartSpec(raw) : null
  }, [spec])

  if (!chart) {
    return (
      <ChartShell
        title={title || 'Chart'}
        label={title ? `Invalid chart preview for ${title}` : 'Invalid chart preview'}
      >
        <div className="flex items-center gap-1.5 text-xs text-(--color-text-muted)">
          <BarChart3 size={14} aria-hidden />
          Invalid chart spec — keys: {describeSpec(spec)}
        </div>
      </ChartShell>
    )
  }

  return (
    <ChartShell
      title={title || chart.title}
      label={title ? `Chart preview for ${title}` : 'Chart preview'}
    >
      <Suspense
        fallback={
          <div
            className="h-[200px] w-full animate-pulse rounded-lg border border-(--color-border-subtle) bg-(--bg-card)"
            aria-hidden="true"
          />
        }
      >
        <ChartBlock spec={chart} />
      </Suspense>
    </ChartShell>
  )
}
