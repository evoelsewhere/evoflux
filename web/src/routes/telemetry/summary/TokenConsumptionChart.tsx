/**
 * Token consumption over time, in two readings of the same bars.
 *
 * "All models" stacks each bucket by model, which answers where the tokens
 * went. "Single model" stacks one model's input by what the provider charged
 * for it — cache read, cache write, fresh — which answers whether the prefix
 * is holding. `by_model` cannot show the first (no time axis) and the token
 * totals cannot show the second (no cache split), so both readings come from
 * `tokens_by_model`.
 *
 * Input and output keep the separate aligned panels the previous chart
 * established. Output runs two to three orders of magnitude below input, so
 * stacking the two together — as the dashboards this chart is modelled on do
 * — renders output as a line of pixels that is never readable.
 */

import { useMemo, useState } from 'react'

import type { ObservabilitySummary } from '@/api/client'
import { SelectControl } from '@/components/ui/select'
import { formatCompact, formatInt, formatPercent } from '@/utils/telemetryFormat'

import { ChartCard, ChartEmpty } from '../charts'
import { formatBucket, niceMax, useChartWidth } from '../chartGeometry'

type Point = ObservabilitySummary['time_series'][number]
type ModelBucket = NonNullable<ObservabilitySummary['tokens_by_model']>[number]

/**
 * Fixed categorical order, assigned by entity and never cycled.
 *
 * Three is where this palette stops separating: it is the largest subset of
 * the product's marker tokens that clears the all-pairs colour checks on both
 * surfaces (worst normal-vision ΔE 16.7 dark / 15.1 light, worst CVD ΔE 10.9 /
 * 9.1). Adding the violet token collapses it — blue against violet is ΔE 0.3
 * under deuteranopia and 10.2 with full colour vision. So a fourth model folds
 * into a deliberately grey "Other" instead of taking a generated hue; the
 * Models tab still lists every one of them by name.
 */
const MODEL_COLORS = [
  'var(--color-marker-blue)',
  'var(--color-marker-orange)',
  'var(--color-marker-pink)',
]
const OTHER_COLOR = 'var(--color-text-subtle)'
const OTHER_ID = '__other__'

/**
 * The cache composition, ordered cheapest first so the bar reads bottom-up as
 * increasing price — and cool to warm, so the escalation is visible before the
 * legend is read. Same names and same hues as `ContextBudgetBar`, so a reader
 * who learned the vocabulary there does not learn it twice.
 */
const INPUT_SEGMENTS = [
  { id: 'cached_tokens', label: 'Cache read', color: 'var(--color-marker-blue)' },
  { id: 'cache_write_tokens', label: 'Cache write', color: 'var(--color-marker-pink)' },
  { id: 'fresh_input_tokens', label: 'Fresh input', color: 'var(--color-marker-orange)' },
] as const

/**
 * Output is alone in its own labelled panel, so it needs a hue that no input
 * segment is using rather than one that separates from them — violet fails
 * against blue in a shared stack, and the two are never in one.
 */
const OUTPUT_SEGMENT: Segment = {
  id: 'output',
  label: 'Output',
  color: 'var(--color-violet)',
}

interface Segment {
  id: string
  label: string
  color: string
}

type Mode = 'all' | 'single'

export function TokenConsumptionChart({
  data,
  bucketSize,
  /**
   * Absent when the backend predates this field — the desktop app can be
   * pointed at an externally managed one. The card degrades to an empty
   * breakdown rather than taking the telemetry page down with it.
   */
  tokensByModel: rawTokensByModel,
}: {
  data: Point[]
  bucketSize: ObservabilitySummary['bucket_size']
  tokensByModel: ModelBucket[] | undefined
}) {
  const [mode, setMode] = useState<Mode>('all')
  const [selected, setSelected] = useState<string | null>(null)

  const tokensByModel = useMemo(() => rawTokensByModel ?? [], [rawTokensByModel])
  const models = useMemo(() => rankModels(tokensByModel), [tokensByModel])
  // A model can drop out of the window when the range changes, and a mode
  // that has nothing to show would render an empty card.
  const model = selected && models.includes(selected) ? selected : (models[0] ?? null)
  const effectiveMode: Mode = model === null ? 'all' : mode

  const { segments, outputSegments, series } = useMemo(
    () =>
      effectiveMode === 'single' && model
        ? singleModelSeries(data, tokensByModel, model)
        : allModelsSeries(data, tokensByModel, models),
    [effectiveMode, model, models, data, tokensByModel],
  )

  const totalTokens = useMemo(
    () =>
      tokensByModel.reduce((sum, row) => sum + row.input_tokens + row.output_tokens, 0),
    [tokensByModel],
  )

  return (
    <ChartCard
      title="Token consumption"
      titleSuffix={`${formatInt(totalTokens)} tokens`}
      description={
        effectiveMode === 'single'
          ? 'One model, input split by what the provider charged for'
          : 'Every model in the window, stacked per bucket'
      }
      legend={legendFor(segments, outputSegments)}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <ModeToggle
            mode={effectiveMode}
            onChange={setMode}
            disabled={models.length === 0}
          />
          {effectiveMode === 'single' && model && (
            <SelectControl
              size="sm"
              ariaLabel="Model"
              value={model}
              onValueChange={setSelected}
              options={models.map((id) => ({ value: id, label: id }))}
            />
          )}
        </div>
      }
    >
      <StackedTokenPanels
        data={data}
        bucketSize={bucketSize}
        segments={segments}
        outputSegments={outputSegments}
        series={series}
        summaryLabel={
          effectiveMode === 'single' && model
            ? `${model}, split by what the provider charged for`
            : 'all models'
        }
      />
    </ChartCard>
  )
}

/* ── Series construction ─────────────────────────────────────────────────── */

interface SeriesShape {
  /** Stack of the input panel, bottom-up. */
  segments: Segment[]
  /** Stack of the output panel, bottom-down — the same models, or just output. */
  outputSegments: Segment[]
  series: Map<string, BucketSeries>
}

/** Bucket → segment id → input tokens, plus that bucket's output stack. */
interface BucketSeries {
  input: Record<string, number>
  output: Record<string, number>
  /** Cache share of this bucket's input, or null when nothing ran. */
  cachePercent: number | null
}

/** Models present in the window, heaviest first — a stable colour order. */
function rankModels(rows: ModelBucket[]): string[] {
  const totals = new Map<string, number>()
  for (const row of rows) {
    totals.set(
      row.provider_model,
      (totals.get(row.provider_model) ?? 0) + row.input_tokens + row.output_tokens,
    )
  }
  return [...totals.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([id]) => id)
}

function emptySeries(data: Point[]): Map<string, BucketSeries> {
  return new Map(
    data.map((point) => [
      point.bucket_start,
      { input: {}, output: {}, cachePercent: null },
    ]),
  )
}

function allModelsSeries(
  data: Point[],
  rows: ModelBucket[],
  models: string[],
): SeriesShape {
  const named = models.slice(0, MODEL_COLORS.length)
  const hasSlot = new Set(named)
  const segments: Segment[] = named.map((id, index) => ({
    id,
    label: id,
    color: MODEL_COLORS[index],
  }))
  if (models.length > named.length) {
    segments.push({
      id: OTHER_ID,
      label: `Other (${models.length - named.length})`,
      color: OTHER_COLOR,
    })
  }

  const series = emptySeries(data)
  const cached = new Map<string, number>()
  const inputs = new Map<string, number>()
  for (const row of rows) {
    const bucket = series.get(row.bucket_start)
    if (!bucket) continue
    const id = hasSlot.has(row.provider_model) ? row.provider_model : OTHER_ID
    bucket.input[id] = (bucket.input[id] ?? 0) + row.input_tokens
    bucket.output[id] = (bucket.output[id] ?? 0) + row.output_tokens
    cached.set(row.bucket_start, (cached.get(row.bucket_start) ?? 0) + row.cached_tokens)
    inputs.set(row.bucket_start, (inputs.get(row.bucket_start) ?? 0) + row.input_tokens)
  }
  for (const [bucketStart, bucket] of series) {
    const total = inputs.get(bucketStart) ?? 0
    bucket.cachePercent = total > 0 ? ((cached.get(bucketStart) ?? 0) / total) * 100 : null
  }
  // Output stacks by model too: one hue per model across both panels, so the
  // legend explains the whole card rather than half of it.
  return { segments, outputSegments: segments, series }
}

function singleModelSeries(
  data: Point[],
  rows: ModelBucket[],
  model: string,
): SeriesShape {
  const series = emptySeries(data)
  for (const row of rows) {
    if (row.provider_model !== model) continue
    const bucket = series.get(row.bucket_start)
    if (!bucket) continue
    for (const segment of INPUT_SEGMENTS) {
      bucket.input[segment.id] = (bucket.input[segment.id] ?? 0) + row[segment.id]
    }
    bucket.output[OUTPUT_SEGMENT.id] =
      (bucket.output[OUTPUT_SEGMENT.id] ?? 0) + row.output_tokens
    bucket.cachePercent = row.cache_percent
  }
  return {
    segments: INPUT_SEGMENTS.map((segment) => ({ ...segment })),
    outputSegments: [OUTPUT_SEGMENT],
    series,
  }
}

/**
 * One entry per hue on the card. When both panels stack by model the two lists
 * are the same object, and repeating every model would double the legend.
 */
function legendFor(segments: Segment[], outputSegments: Segment[]) {
  const entries = [...segments]
  for (const segment of outputSegments) {
    if (!entries.some((existing) => existing.id === segment.id)) entries.push(segment)
  }
  return entries.map((segment) => ({ label: segment.label, color: segment.color }))
}

/* ── Plot ────────────────────────────────────────────────────────────────── */

const CHART_HEIGHT = 252
const PANEL_HEIGHT = 82
const INPUT_TOP = 30
const INPUT_BASELINE = INPUT_TOP + PANEL_HEIGHT
const OUTPUT_BASELINE = 134
const OUTPUT_BOTTOM = OUTPUT_BASELINE + PANEL_HEIGHT
/** Surface gap between stacked segments — separation without a border. */
const SEGMENT_GAP = 2
const CORNER = 4

function StackedTokenPanels({
  data,
  bucketSize,
  segments,
  outputSegments,
  series,
  summaryLabel,
}: {
  data: Point[]
  bucketSize: ObservabilitySummary['bucket_size']
  segments: Segment[]
  outputSegments: Segment[]
  series: Map<string, BucketSeries>
  summaryLabel: string
}) {
  const [containerRef, width] = useChartWidth()
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  if (data.length === 0) return <ChartEmpty />

  const left = width < 440 ? 44 : 52
  const right = width < 440 ? 10 : 16
  const plotWidth = width - left - right
  const bandWidth = plotWidth / Math.max(data.length, 1)
  const barWidth = Math.max(2, Math.min(18, bandWidth * 0.5))
  const x = (index: number) => left + bandWidth * (index + 0.5)
  const labelEvery = Math.max(1, Math.ceil(data.length / 7))

  const totalsFor = (bucket: BucketSeries | undefined, side: 'input' | 'output') =>
    bucket ? Object.values(bucket[side]).reduce((sum, value) => sum + value, 0) : 0
  const inputTotals = data.map((point) => totalsFor(series.get(point.bucket_start), 'input'))
  const outputTotals = data.map((point) => totalsFor(series.get(point.bucket_start), 'output'))
  const inputMax = niceMax(Math.max(...inputTotals, 1))
  const outputMax = niceMax(Math.max(...outputTotals, 1))
  const inputPeak = Math.max(...inputTotals, 0)
  const outputPeak = Math.max(...outputTotals, 0)

  const hovered =
    hoveredIndex === null ? null : (series.get(data[hoveredIndex].bucket_start) ?? null)
  // When both panels stack the same entities, one row carries that entity's
  // input and output side by side. Listing them separately doubles the rows
  // and grows a tooltip that already covers the bars it describes.
  const paired = outputSegments === segments
  // Only what this bucket actually held: a zero row is a colour the reader has
  // to check and discard.
  const tooltipRows =
    hovered === null
      ? []
      : paired
        ? segments
            .map((segment) => ({
              key: segment.id,
              label: segment.label,
              color: segment.color,
              value: hovered.input[segment.id] ?? 0,
              output: hovered.output[segment.id] ?? 0,
            }))
            .filter((row) => row.value > 0 || row.output > 0)
        : [
            ...segments.map((segment) => ({
              key: `in-${segment.id}`,
              label: segment.label,
              color: segment.color,
              value: hovered.input[segment.id] ?? 0,
              output: null as number | null,
            })),
            ...outputSegments.map((segment) => ({
              key: `out-${segment.id}`,
              label: segment.label,
              color: segment.color,
              value: hovered.output[segment.id] ?? 0,
              output: null as number | null,
            })),
          ].filter((row) => row.value > 0)
  const tooltipWidth = Math.min(
    Math.max(plotWidth - 16, 150),
    paired ? 300 : 240,
  )
  const tooltipHeight =
    tooltipRows.length === 0
      ? 44
      : (paired ? 30 : 22) + tooltipRows.length * 14 + 10
  // Beside the hovered column, on whichever side has room — centred on it, as
  // the previous chart did, the panel covers the bars it is describing.
  const tooltipX =
    hoveredIndex === null
      ? 0
      : x(hoveredIndex) < left + plotWidth / 2
        ? Math.min(width - right - tooltipWidth, x(hoveredIndex) + bandWidth / 2 + 8)
        : Math.max(left, x(hoveredIndex) - bandWidth / 2 - 8 - tooltipWidth)
  const tooltipY = Math.min(INPUT_TOP + 6, OUTPUT_BOTTOM - tooltipHeight)

  const renderGridLine = (key: string, y: number, value: number, emphasized = false) => (
    <g key={key}>
      <line
        x1={left}
        x2={width - right}
        y1={y}
        y2={y}
        stroke={emphasized ? 'var(--color-border-strong)' : 'var(--color-border)'}
        strokeWidth="1"
        opacity={emphasized ? 0.8 : 0.46}
      />
      <text x={left - 8} y={y + 3.5} textAnchor="end" fill="var(--color-text-subtle)" fontSize="9">
        {formatCompact(value)}
      </text>
    </g>
  )

  /** Segments of one bucket, bottom-up, with the stack's end rounded. */
  const renderStack = (
    index: number,
    bucket: BucketSeries | undefined,
    side: 'input' | 'output',
  ) => {
    if (!bucket) return null
    const stack = side === 'input' ? segments : outputSegments
    const scale = side === 'input' ? PANEL_HEIGHT / inputMax : PANEL_HEIGHT / outputMax
    const baseline = side === 'input' ? INPUT_BASELINE : OUTPUT_BASELINE
    const grows = side === 'input' ? -1 : 1
    const values = stack.map((segment) => bucket[side][segment.id] ?? 0)
    const lastFilled = values.reduce((last, value, i) => (value > 0 ? i : last), -1)
    if (lastFilled < 0) return null

    let offset = 0
    return stack.map((segment, i) => {
      const value = values[i]
      if (value <= 0) return null
      const full = value * scale
      const start = offset
      offset += full
      // The gap comes out of the segment, not the stack, so the bar's total
      // height still reads against the axis.
      const height = Math.max(full - (i === lastFilled ? 0 : SEGMENT_GAP), 1)
      const top = grows === -1 ? baseline - start - height : baseline + start
      return (
        <path
          key={`${side}-${index}-${segment.id}`}
          d={barPath(
            x(index) - barWidth / 2,
            top,
            barWidth,
            height,
            i === lastFilled ? Math.min(CORNER, barWidth / 2, height) : 0,
            grows === -1 ? 'top' : 'bottom',
          )}
          fill={segment.color}
          opacity={hoveredIndex === null || hoveredIndex === index ? 0.9 : 0.42}
        />
      )
    })
  }

  return (
    <div
      ref={containerRef}
      className="overflow-hidden rounded-md bg-(--bg-page)/20"
      role="img"
      aria-label={`Token consumption, ${summaryLabel}. Input and output on separate scales. Input peak ${formatCompact(inputPeak)}, output peak ${formatCompact(outputPeak)}.`}
    >
      <svg
        viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
        className="h-[15.75rem] w-full"
        aria-hidden="true"
        onMouseLeave={() => setHoveredIndex(null)}
      >
        {/* Neutral panel grounds. The old chart tinted these blue and orange
            to name their series; the bars now carry several hues each, and a
            tinted ground would claim one of them. */}
        <rect
          x={left}
          y={INPUT_TOP - 7}
          width={plotWidth}
          height={PANEL_HEIGHT + 7}
          rx="7"
          fill="var(--color-text-subtle)"
          opacity="0.05"
        />
        <rect
          x={left}
          y={OUTPUT_BASELINE}
          width={plotWidth}
          height={PANEL_HEIGHT + 7}
          rx="7"
          fill="var(--color-text-subtle)"
          opacity="0.05"
        />

        {hoveredIndex !== null && (
          <rect
            x={left + bandWidth * hoveredIndex + 1}
            y={INPUT_TOP - 7}
            width={Math.max(1, bandWidth - 2)}
            height={OUTPUT_BOTTOM - INPUT_TOP + 14}
            rx="5"
            fill="var(--bg-key)"
            opacity="0.75"
          />
        )}

        <text x={left + 8} y={INPUT_TOP - 13} fill="var(--color-text-2)" fontSize="10" fontWeight="650">
          Input tokens
        </text>
        <text x={width - right - 8} y={INPUT_TOP - 13} textAnchor="end" fill="var(--color-text-muted)" fontSize="9.5">
          Peak {formatCompact(inputPeak)}
        </text>
        <text x={left + 8} y={OUTPUT_BASELINE - 8} fill="var(--color-text-2)" fontSize="10" fontWeight="650">
          Output tokens
        </text>
        <text x={width - right - 8} y={OUTPUT_BASELINE - 8} textAnchor="end" fill="var(--color-text-muted)" fontSize="9.5">
          Peak {formatCompact(outputPeak)}
        </text>

        {renderGridLine('input-max', INPUT_TOP, inputMax)}
        {renderGridLine('input-half', INPUT_TOP + PANEL_HEIGHT / 2, inputMax / 2)}
        {renderGridLine('input-zero', INPUT_BASELINE, 0, true)}
        {renderGridLine('output-zero', OUTPUT_BASELINE, 0, true)}
        {renderGridLine('output-half', OUTPUT_BASELINE + PANEL_HEIGHT / 2, outputMax / 2)}
        {renderGridLine('output-max', OUTPUT_BOTTOM, outputMax)}

        {data.map((point, index) => (
          <g key={`stacks-${point.bucket_start}`}>
            {renderStack(index, series.get(point.bucket_start), 'input')}
            {renderStack(index, series.get(point.bucket_start), 'output')}
          </g>
        ))}

        {data.map((point, index) => (
          <rect
            key={`hit-${point.bucket_start}`}
            data-chart-bucket={index}
            x={left + bandWidth * index}
            y={INPUT_TOP - 7}
            width={bandWidth}
            height={OUTPUT_BOTTOM - INPUT_TOP + 14}
            fill="transparent"
            onMouseEnter={() => setHoveredIndex(index)}
          />
        ))}

        {data.map((point, index) => {
          if (index % labelEvery !== 0 && index !== data.length - 1) return null
          return (
            <text
              key={point.bucket_start}
              x={x(index)}
              y={CHART_HEIGHT - 9}
              textAnchor="middle"
              fill="var(--color-text-subtle)"
              fontSize="9.5"
            >
              {formatBucket(point.bucket_start, bucketSize)}
            </text>
          )
        })}

        {hovered && hoveredIndex !== null && (
          <g data-token-tooltip pointerEvents="none">
            <line
              x1={x(hoveredIndex)}
              x2={x(hoveredIndex)}
              y1={INPUT_TOP - 5}
              y2={OUTPUT_BOTTOM + 5}
              stroke="var(--color-text-subtle)"
              strokeWidth="1"
              opacity="0.55"
            />
            <rect
              x={tooltipX}
              y={tooltipY}
              width={tooltipWidth}
              height={tooltipHeight}
              rx="7"
              fill="var(--bg-card)"
              stroke="var(--color-border-strong)"
            />
            <text x={tooltipX + 10} y={tooltipY + 16} fill="var(--color-text)" fontSize="10" fontWeight="650">
              {formatBucket(data[hoveredIndex].bucket_start, bucketSize)}
            </text>
            <text
              x={tooltipX + tooltipWidth - 10}
              y={tooltipY + 16}
              textAnchor="end"
              fill="var(--color-text-muted)"
              fontSize="9.5"
            >
              {hovered.cachePercent === null
                ? '—'
                : `${formatPercent(hovered.cachePercent)} cached`}
            </text>
            {tooltipRows.length === 0 && (
              <text
                x={tooltipX + 10}
                y={tooltipY + 32}
                fill="var(--color-text-subtle)"
                fontSize="9.5"
              >
                No traffic in this bucket
              </text>
            )}
            {paired && tooltipRows.length > 0 && (
              <text
                x={tooltipX + tooltipWidth - 10}
                y={tooltipY + 28}
                textAnchor="end"
                fill="var(--color-text-subtle)"
                fontSize="8.5"
              >
                in · out
              </text>
            )}
            {tooltipRows.map((row, rowIndex) => {
              const y = tooltipY + 32 + rowIndex * 14
              const outColumn = tooltipX + tooltipWidth - 10
              const inColumn = paired ? outColumn - 62 : outColumn
              return (
                <g key={row.key}>
                  <circle cx={tooltipX + 13} cy={y - 3} r="3" fill={row.color} />
                  <text x={tooltipX + 21} y={y} fill="var(--color-text-muted)" fontSize="9.5">
                    {truncate(
                      row.label,
                      Math.max(Math.floor((inColumn - tooltipX - 90) / 5), 6),
                    )}
                  </text>
                  <text
                    x={inColumn}
                    y={y}
                    textAnchor="end"
                    fill="var(--color-text)"
                    fontSize="9.5"
                    fontWeight="600"
                  >
                    {formatInt(row.value)}
                  </text>
                  {row.output !== null && (
                    <text
                      x={outColumn}
                      y={y}
                      textAnchor="end"
                      fill="var(--color-text-muted)"
                      fontSize="9.5"
                    >
                      {formatInt(row.output)}
                    </text>
                  )}
                </g>
              )
            })}
          </g>
        )}
      </svg>
    </div>
  )
}

/* ── Bits ────────────────────────────────────────────────────────────────── */

function ModeToggle({
  mode,
  onChange,
  disabled,
}: {
  mode: Mode
  onChange: (mode: Mode) => void
  disabled: boolean
}) {
  const options: Array<{ value: Mode; label: string }> = [
    { value: 'all', label: 'All models' },
    { value: 'single', label: 'Single model' },
  ]
  return (
    <div
      role="group"
      aria-label="Token breakdown"
      className="inline-flex rounded-md border border-(--color-border) bg-(--bg-page) p-0.5"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          disabled={disabled}
          aria-pressed={mode === option.value}
          onClick={() => onChange(option.value)}
          className={`rounded-sm px-2 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
            mode === option.value
              ? 'bg-(--bg-key) font-medium text-(--color-text)'
              : 'text-(--color-text-muted) hover:text-(--color-text)'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

/** A rect with only the stack's end rounded, so segments meet flush. */
function barPath(
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
  end: 'top' | 'bottom',
): string {
  const r = Math.max(0, Math.min(radius, width / 2, height))
  if (r === 0) return `M ${x} ${y} h ${width} v ${height} h ${-width} Z`
  return end === 'top'
    ? `M ${x} ${y + height} V ${y + r} A ${r} ${r} 0 0 1 ${x + r} ${y} H ${x + width - r} A ${r} ${r} 0 0 1 ${x + width} ${y + r} V ${y + height} Z`
    : `M ${x} ${y} V ${y + height - r} A ${r} ${r} 0 0 0 ${x + r} ${y + height} H ${x + width - r} A ${r} ${r} 0 0 0 ${x + width} ${y + height - r} V ${y} Z`
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, Math.max(max - 1, 1))}…`
}
