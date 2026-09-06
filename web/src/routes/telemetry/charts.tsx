import type { ObservabilitySummary } from '@/api/client'
import { formatCompact } from '@/utils/telemetryFormat'

import { formatBucket, useChartWidth } from './chartGeometry'

type Point = ObservabilitySummary['time_series'][number]
type NumericKey = {
  [K in keyof Point]: Point[K] extends number ? K : never
}[keyof Point]

interface Series {
  key: NumericKey
  label: string
  color: string
  kind?: 'bar' | 'line'
}

const HEIGHT = 220
const PAD = { left: 44, right: 14, top: 16, bottom: 32 }

export function TimeChart({
  data,
  series,
  valueFormatter = formatCompact,
  bucketSize,
}: {
  data: Point[]
  series: Series[]
  valueFormatter?: (value: number) => string
  bucketSize: ObservabilitySummary['bucket_size']
}) {
  const [containerRef, width] = useChartWidth()
  if (data.length === 0) return <ChartEmpty />

  const plotWidth = width - PAD.left - PAD.right
  const plotHeight = HEIGHT - PAD.top - PAD.bottom
  const values = data.flatMap((point) => series.map((item) => Number(point[item.key])))
  const max = Math.max(...values, 1)
  const x = (index: number) =>
    PAD.left + (data.length <= 1 ? plotWidth / 2 : (index / (data.length - 1)) * plotWidth)
  const y = (value: number) => PAD.top + plotHeight - (value / max) * plotHeight
  const labelEvery = Math.max(1, Math.ceil(data.length / 6))
  const barSeries = series.filter((item) => item.kind === 'bar')
  const barWidth = Math.max(2, Math.min(18, plotWidth / Math.max(data.length, 1) / 1.7))

  return (
    <div ref={containerRef} className="overflow-hidden" role="img" aria-label={series.map((item) => item.label).join(', ')}>
      <svg viewBox={`0 0 ${width} ${HEIGHT}`} className="h-56 w-full" aria-hidden="true">
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const gridY = PAD.top + plotHeight * ratio
          const value = max * (1 - ratio)
          return (
            <g key={ratio}>
              <line x1={PAD.left} x2={width - PAD.right} y1={gridY} y2={gridY} stroke="var(--color-border)" strokeWidth="1" opacity="0.65" />
              <text x={PAD.left - 8} y={gridY + 4} textAnchor="end" fill="var(--color-text-muted)" fontSize="10">
                {valueFormatter(value)}
              </text>
            </g>
          )
        })}

        {barSeries.map((item, seriesIndex) =>
          data.map((point, index) => {
            const value = Number(point[item.key])
            const offset = (seriesIndex - (barSeries.length - 1) / 2) * barWidth
            return (
              <rect
                key={`${String(item.key)}-${point.bucket_start}`}
                x={x(index) - barWidth / 2 + offset}
                y={y(value)}
                width={Math.max(barWidth - 1, 1)}
                height={Math.max(PAD.top + plotHeight - y(value), value > 0 ? 1 : 0)}
                rx="2"
                fill={item.color}
                opacity="0.72"
              >
                <title>{`${item.label}: ${valueFormatter(value)} · ${formatBucket(point.bucket_start, bucketSize)}`}</title>
              </rect>
            )
          }),
        )}

        {series.filter((item) => item.kind !== 'bar').map((item) => {
          const path = data
            .map((point, index) => `${index === 0 ? 'M' : 'L'} ${x(index)} ${y(Number(point[item.key]))}`)
            .join(' ')
          return (
            <g key={String(item.key)}>
              <path d={path} fill="none" stroke={item.color} strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" />
              {data.map((point, index) => (
                <circle key={point.bucket_start} cx={x(index)} cy={y(Number(point[item.key]))} r="2.5" fill={item.color}>
                  <title>{`${item.label}: ${valueFormatter(Number(point[item.key]))} · ${formatBucket(point.bucket_start, bucketSize)}`}</title>
                </circle>
              ))}
            </g>
          )
        })}

        {data.map((point, index) => {
          if (index % labelEvery !== 0 && index !== data.length - 1) return null
          return (
            <text key={point.bucket_start} x={x(index)} y={HEIGHT - 10} textAnchor="middle" fill="var(--color-text-muted)" fontSize="10">
              {formatBucket(point.bucket_start, bucketSize)}
            </text>
          )
        })}
      </svg>
    </div>
  )
}

export function ChartCard({
  title,
  titleSuffix,
  description,
  legend,
  actions,
  children,
}: {
  title: string
  /** Headline figure shown beside the title, e.g. a window total. */
  titleSuffix?: React.ReactNode
  description: string
  legend: Array<{ label: string; color: string }>
  /** View controls for this card — a mode toggle, a series selector. */
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="min-w-0 rounded-lg border border-(--color-border) bg-(--bg-card) p-3 sm:p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <h3 className="text-sm font-semibold text-(--color-text)">{title}</h3>
            {titleSuffix && (
              <span className="text-xs text-(--color-text-muted)">{titleSuffix}</span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-(--color-text-muted)">{description}</p>
        </div>
        {actions ?? <Legend items={legend} />}
      </div>
      {/* A card with controls has no room left in its header row, so its
          legend moves to a line of its own rather than crowding them. */}
      {actions && legend.length > 0 && (
        <div className="mb-3">
          <Legend items={legend} />
        </div>
      )}
      {children}
    </section>
  )
}

function Legend({ items }: { items: Array<{ label: string; color: string }> }) {
  if (items.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-(--color-text-muted)">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  )
}

export function RankedBars({
  rows,
  valueFormatter = formatCompact,
}: {
  rows: Array<{ label: string; value: number; secondary?: string; tone?: 'danger' }>
  valueFormatter?: (value: number) => string
}) {
  const max = Math.max(...rows.map((row) => row.value), 1)
  if (rows.length === 0) return <ChartEmpty />
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="min-w-0 truncate font-medium text-(--color-text)" title={row.label}>{row.label}</span>
            <span className={row.tone === 'danger' ? 'text-(--color-error)' : 'text-(--color-text-2)'}>
              {valueFormatter(row.value)}{row.secondary ? ` · ${row.secondary}` : ''}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-(--bg-key)">
            <div
              className={`h-full rounded-full ${row.tone === 'danger' ? 'bg-(--color-error)' : 'bg-(--color-marker-blue)'}`}
              style={{ width: `${Math.max((row.value / max) * 100, row.value > 0 ? 1 : 0)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

export function ChartEmpty() {
  return <div className="flex h-48 items-center justify-center text-xs text-(--color-text-muted)">No data in this window.</div>
}

