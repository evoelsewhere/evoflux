import { useEffect, useRef, useState } from 'react'
import type { ObservabilitySummary } from '@/api/client'
import { formatCompact } from '@/utils/telemetryFormat'

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

const DEFAULT_WIDTH = 760
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

/**
 * Token input and output differ by orders of magnitude. Plotting them on one
 * axis makes output effectively invisible, so this chart uses aligned small
 * multiples with independent, clearly labelled scales and a shared time axis.
 */
export function TokenVolumeChart({
  data,
  bucketSize,
}: {
  data: Point[]
  bucketSize: ObservabilitySummary['bucket_size']
}) {
  const [containerRef, width] = useChartWidth()
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  if (data.length === 0) return <ChartEmpty />

  const chartHeight = 252
  const left = width < 440 ? 44 : 52
  const right = width < 440 ? 10 : 16
  const plotWidth = width - left - right
  const panelHeight = 82
  const inputTop = 30
  const inputBaseline = inputTop + panelHeight
  const outputBaseline = 134
  const outputBottom = outputBaseline + panelHeight
  const inputMax = niceMax(Math.max(...data.map((point) => point.input_tokens), 1))
  const outputMax = niceMax(Math.max(...data.map((point) => point.output_tokens), 1))
  const bandWidth = plotWidth / Math.max(data.length, 1)
  const barWidth = Math.max(2, Math.min(18, bandWidth * 0.5))
  const x = (index: number) => left + bandWidth * (index + 0.5)
  const labelEvery = Math.max(1, Math.ceil(data.length / 7))
  const inputPeak = Math.max(...data.map((point) => point.input_tokens))
  const outputPeak = Math.max(...data.map((point) => point.output_tokens))
  const hovered = hoveredIndex === null ? null : data[hoveredIndex]
  const tooltipWidth = 164
  const tooltipHeight = 58
  const tooltipX = hoveredIndex === null
    ? 0
    : Math.min(
        width - right - tooltipWidth,
        Math.max(left, x(hoveredIndex) - tooltipWidth / 2),
      )

  const renderGridLine = (
    key: string,
    y: number,
    value: number,
    emphasized = false,
  ) => (
    <g key={key}>
      <line
        x1={left}
        x2={width - right}
        y1={y}
        y2={y}
        stroke={emphasized ? 'var(--color-border-strong)' : 'var(--color-border)'}
        strokeWidth="1"
        strokeDasharray={emphasized ? undefined : '3 4'}
        opacity={emphasized ? 0.8 : 0.46}
      />
      <text
        x={left - 8}
        y={y + 3.5}
        textAnchor="end"
        fill="var(--color-text-subtle)"
        fontSize="9"
      >
        {formatCompact(value)}
      </text>
    </g>
  )

  return (
    <div
      ref={containerRef}
      className="overflow-hidden rounded-md bg-(--bg-page)/20"
      role="img"
      aria-label={`Input and output token volume with independent scales. Input peak ${formatCompact(inputPeak)}, output peak ${formatCompact(outputPeak)}.`}
    >
      <svg
        viewBox={`0 0 ${width} ${chartHeight}`}
        className="h-[15.75rem] w-full"
        aria-hidden="true"
        onMouseLeave={() => setHoveredIndex(null)}
      >
        <rect
          x={left}
          y={inputTop - 7}
          width={plotWidth}
          height={panelHeight + 7}
          rx="7"
          fill="var(--color-marker-blue)"
          opacity="0.035"
        />
        <rect
          x={left}
          y={outputBaseline}
          width={plotWidth}
          height={panelHeight + 7}
          rx="7"
          fill="var(--color-marker-orange)"
          opacity="0.04"
        />

        {hoveredIndex !== null && (
          <rect
            x={left + bandWidth * hoveredIndex + 1}
            y={inputTop - 7}
            width={Math.max(1, bandWidth - 2)}
            height={outputBottom - inputTop + 14}
            rx="5"
            fill="var(--bg-key)"
            opacity="0.75"
          />
        )}

        <text x={left + 8} y={inputTop - 13} fill="var(--color-marker-blue)" fontSize="10" fontWeight="650">
          Input tokens
        </text>
        <text x={width - right - 8} y={inputTop - 13} textAnchor="end" fill="var(--color-text-muted)" fontSize="9.5">
          Peak {formatCompact(inputPeak)}
        </text>
        <text x={left + 8} y={outputBaseline - 8} fill="var(--color-marker-orange)" fontSize="10" fontWeight="650">
          Output tokens
        </text>
        <text x={width - right - 8} y={outputBaseline - 8} textAnchor="end" fill="var(--color-text-muted)" fontSize="9.5">
          Peak {formatCompact(outputPeak)}
        </text>

        {renderGridLine('input-max', inputTop, inputMax)}
        {renderGridLine('input-half', inputTop + panelHeight / 2, inputMax / 2)}
        {renderGridLine('input-zero', inputBaseline, 0, true)}
        {renderGridLine('output-zero', outputBaseline, 0, true)}
        {renderGridLine('output-half', outputBaseline + panelHeight / 2, outputMax / 2)}
        {renderGridLine('output-max', outputBottom, outputMax)}

        {data.map((point, index) => {
          const value = point.input_tokens
          const height = (value / inputMax) * panelHeight
          return (
            <rect
              key={`input-${point.bucket_start}`}
              x={x(index) - barWidth / 2}
              y={inputBaseline - height}
              width={barWidth}
              height={Math.max(height, value > 0 ? 1 : 0)}
              rx="2.5"
              fill="var(--color-marker-blue)"
              opacity={hoveredIndex === null || hoveredIndex === index ? 0.88 : 0.48}
            />
          )
        })}

        {data.map((point, index) => {
          const value = point.output_tokens
          const height = (value / outputMax) * panelHeight
          return (
            <rect
              key={`output-${point.bucket_start}`}
              x={x(index) - barWidth / 2}
              y={outputBaseline}
              width={barWidth}
              height={Math.max(height, value > 0 ? 1 : 0)}
              rx="2.5"
              fill="var(--color-marker-orange)"
              opacity={hoveredIndex === null || hoveredIndex === index ? 0.88 : 0.48}
            />
          )
        })}

        {data.map((point, index) => (
          <rect
            key={`hit-${point.bucket_start}`}
            data-chart-bucket={index}
            x={left + bandWidth * index}
            y={inputTop - 7}
            width={bandWidth}
            height={outputBottom - inputTop + 14}
            fill="transparent"
            onMouseEnter={() => setHoveredIndex(index)}
          />
        ))}

        {data.map((point, index) => {
          if (index % labelEvery !== 0 && index !== data.length - 1) return null
          return (
            <text key={point.bucket_start} x={x(index)} y={chartHeight - 9} textAnchor="middle" fill="var(--color-text-subtle)" fontSize="9.5">
              {formatBucket(point.bucket_start, bucketSize)}
            </text>
          )
        })}

        {hovered && hoveredIndex !== null && (
          <g data-token-tooltip pointerEvents="none">
            <line
              x1={x(hoveredIndex)}
              x2={x(hoveredIndex)}
              y1={inputTop - 5}
              y2={outputBottom + 5}
              stroke="var(--color-text-subtle)"
              strokeWidth="1"
              opacity="0.55"
            />
            <rect
              x={tooltipX}
              y={inputTop + 8}
              width={tooltipWidth}
              height={tooltipHeight}
              rx="7"
              fill="var(--bg-card)"
              stroke="var(--color-border-strong)"
            />
            <text x={tooltipX + 10} y={inputTop + 24} fill="var(--color-text)" fontSize="10" fontWeight="650">
              {formatBucket(hovered.bucket_start, bucketSize)}
            </text>
            <circle cx={tooltipX + 12} cy={inputTop + 39} r="3" fill="var(--color-marker-blue)" />
            <text x={tooltipX + 20} y={inputTop + 42} fill="var(--color-text-muted)" fontSize="9.5">
              Input
            </text>
            <text x={tooltipX + 100} y={inputTop + 42} fill="var(--color-text)" fontSize="9.5" fontWeight="600">
              {formatCompact(hovered.input_tokens)}
            </text>
            <circle cx={tooltipX + 12} cy={inputTop + 54} r="3" fill="var(--color-marker-orange)" />
            <text x={tooltipX + 20} y={inputTop + 57} fill="var(--color-text-muted)" fontSize="9.5">
              Output
            </text>
            <text x={tooltipX + 100} y={inputTop + 57} fill="var(--color-text)" fontSize="9.5" fontWeight="600">
              {formatCompact(hovered.output_tokens)}
            </text>
          </g>
        )}
      </svg>
    </div>
  )
}

export function ChartCard({
  title,
  description,
  legend,
  children,
}: {
  title: string
  description: string
  legend: Array<{ label: string; color: string }>
  children: React.ReactNode
}) {
  return (
    <section className="min-w-0 rounded-lg border border-(--color-border) bg-(--bg-card) p-3 sm:p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-(--color-text)">{title}</h3>
          <p className="mt-0.5 text-xs text-(--color-text-muted)">{description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-(--color-text-muted)">
          {legend.map((item) => (
            <span key={item.label} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ background: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      </div>
      {children}
    </section>
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

function ChartEmpty() {
  return <div className="flex h-48 items-center justify-center text-xs text-(--color-text-muted)">No data in this window.</div>
}

function formatBucket(value: string, bucketSize: ObservabilitySummary['bucket_size']) {
  const date = new Date(value)
  return new Intl.DateTimeFormat(undefined, bucketSize === 'hour'
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: 'short', day: 'numeric' }).format(date)
}

function niceMax(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1
  const exponent = Math.floor(Math.log10(value))
  const magnitude = 10 ** exponent
  const normalized = value / magnitude
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return nice * magnitude
}

function useChartWidth(): [React.RefObject<HTMLDivElement | null>, number] {
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
