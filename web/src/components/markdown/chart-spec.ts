/**
 * Chart spec contract for the ```chart fence (Intelligent UI feature D).
 *
 * Kept dependency-free and side-effect-free so it can be imported by the
 * fence dispatcher, the lazy ChartBlock chunk, and unit tests without
 * pulling Recharts into any of them.
 *
 * Stream 2's `UiChart` re-uses this parser for the `ui_block` event's
 * `spec` field — see §8.3 of documents/plans/2026-10-13-intelligent-ui.md.
 */

export interface ChartSeries {
  key: string
  label?: string
  color?: string
}

export interface ChartSpec {
  type: 'line' | 'bar' | 'area' | 'pie'
  title?: string
  xKey: string
  series: ChartSeries[]
  data: Array<Record<string, string | number>>
  yLabel?: string
  /** bar only */
  stacked?: boolean
  unit?: string
}

const CHART_TYPES = new Set(['line', 'bar', 'area', 'pie'])
const MAX_TITLE_LENGTH = 120
const MAX_SERIES = 6
const MAX_DATA_POINTS = 500

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Parse and structurally validate a fenced chart spec.
 *
 * Returns the spec when valid and `null` for any structural violation
 * (bad JSON, unknown type, missing `xKey`, too many series or rows, a
 * multi-series pie, …). Limits are enforced here as a last line of
 * defence — the server clamps them too.
 */
export function parseChartSpec(text: string): ChartSpec | null {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return null
  }
  if (!isRecord(raw)) return null

  const { type, xKey, series, data } = raw
  if (typeof type !== 'string' || !CHART_TYPES.has(type)) return null
  if (typeof xKey !== 'string' || xKey.length === 0) return null
  if (!Array.isArray(series) || series.length < 1 || series.length > MAX_SERIES) {
    return null
  }
  if (!Array.isArray(data) || data.length < 1 || data.length > MAX_DATA_POINTS) {
    return null
  }

  const parsedSeries: ChartSeries[] = []
  for (const entry of series) {
    if (!isRecord(entry) || typeof entry.key !== 'string' || entry.key.length === 0) {
      return null
    }
    const item: ChartSeries = { key: entry.key }
    if (typeof entry.label === 'string') item.label = entry.label
    if (typeof entry.color === 'string') item.color = entry.color
    parsedSeries.push(item)
  }
  // A pie has exactly one slice; more than one series is a spec error.
  if (type === 'pie' && parsedSeries.length > 1) return null

  for (const row of data) {
    if (!isRecord(row)) return null
    if (!(xKey in row)) return null
  }

  const spec: ChartSpec = {
    type: type as ChartSpec['type'],
    xKey,
    series: parsedSeries,
    data: data as Array<Record<string, string | number>>,
  }
  if (typeof raw.title === 'string' && raw.title.length <= MAX_TITLE_LENGTH) {
    spec.title = raw.title
  }
  if (typeof raw.yLabel === 'string') spec.yLabel = raw.yLabel
  if (raw.stacked === true) spec.stacked = true
  if (typeof raw.unit === 'string') spec.unit = raw.unit
  return spec
}
