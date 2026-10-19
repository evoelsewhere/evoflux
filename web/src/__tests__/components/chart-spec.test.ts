import { describe, expect, it } from 'vitest'

import { parseChartSpec } from '@/components/markdown/chart-spec'

const VALID_LINE = JSON.stringify({
  type: 'line',
  title: 'Weekly signups',
  xKey: 'week',
  series: [{ key: 'signups', label: 'Signups' }],
  data: [
    { week: 'W1', signups: 10 },
    { week: 'W2', signups: 14 },
  ],
  unit: '',
})

describe('parseChartSpec', () => {
  it('accepts a valid line/bar/area/pie spec', () => {
    expect(parseChartSpec(VALID_LINE)?.type).toBe('line')

    const pie = JSON.parse(VALID_LINE) as Record<string, unknown>
    pie.type = 'pie'
    expect(parseChartSpec(JSON.stringify(pie))?.type).toBe('pie')

    pie.type = 'area'
    expect(parseChartSpec(JSON.stringify(pie))?.type).toBe('area')

    pie.type = 'bar'
    pie.stacked = true
    const bar = parseChartSpec(JSON.stringify(pie))
    expect(bar?.type).toBe('bar')
    expect(bar?.stacked).toBe(true)
  })

  it('rejects malformed JSON', () => {
    expect(parseChartSpec('{oops')).toBeNull()
    expect(parseChartSpec('null')).toBeNull()
    expect(parseChartSpec('[1,2,3]')).toBeNull()
  })

  it('rejects an unknown chart type', () => {
    const spec = { ...(JSON.parse(VALID_LINE) as Record<string, unknown>), type: 'radar' }
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  it('rejects a missing or empty xKey', () => {
    const spec = JSON.parse(VALID_LINE) as Record<string, unknown>
    delete spec.xKey
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()

    spec.xKey = ''
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  it('rejects an empty, oversized, or malformed series list', () => {
    const spec = JSON.parse(VALID_LINE) as Record<string, unknown>

    spec.series = []
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()

    spec.series = Array.from({ length: 7 }, (_, i) => ({ key: `s${i}` }))
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()

    spec.series = [{ label: 'no-key' }]
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  it('rejects empty, oversized, or non-object data rows', () => {
    const spec = JSON.parse(VALID_LINE) as Record<string, unknown>

    spec.data = []
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()

    spec.data = Array.from({ length: 501 }, (_, i) => ({ week: `W${i}`, signups: i }))
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()

    spec.data = [['not', 'a', 'row']]
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  it('rejects a row that is missing the xKey', () => {
    const spec = JSON.parse(VALID_LINE) as Record<string, unknown>
    spec.data = [{ week: 'W1', signups: 10 }, { signups: 12 }]
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  it('rejects a pie with more than one series', () => {
    const spec = JSON.parse(VALID_LINE) as Record<string, unknown>
    spec.type = 'pie'
    spec.series = [
      { key: 'a' },
      { key: 'b' },
    ]
    expect(parseChartSpec(JSON.stringify(spec))).toBeNull()
  })

  it('drops an overlong title instead of discarding the whole chart', () => {
    const spec = JSON.parse(VALID_LINE) as Record<string, unknown>
    spec.title = 'x'.repeat(121)
    const parsed = parseChartSpec(JSON.stringify(spec))
    expect(parsed).not.toBeNull()
    expect(parsed?.title).toBeUndefined()
  })
})

describe('parseChartSpec lenient tabular form', () => {
  const BARS = ['bar', 'Mon 12', 'Tue 19', 'Wed 7'].join('\n')

  it('accepts a type line plus label/value rows', () => {
    const parsed = parseChartSpec(BARS)
    expect(parsed?.type).toBe('bar')
    expect(parsed?.xKey).toBe('label')
    expect(parsed?.series).toEqual([{ key: 'value' }])
    expect(parsed?.data).toEqual([
      { label: 'Mon', value: 12 },
      { label: 'Tue', value: 19 },
      { label: 'Wed', value: 7 },
    ])
  })

  it('handles quoted labels, thousands separators, decimals and a % marker', () => {
    const parsed = parseChartSpec(
      ['line', '"North region" 1,250', 'South 8.5%', 'West -3'].join('\n'),
    )
    expect(parsed?.type).toBe('line')
    expect(parsed?.data).toEqual([
      { label: '"North region"', value: 1250 },
      { label: 'South', value: 8.5 },
      { label: 'West', value: -3 },
    ])
  })

  it('supports pie', () => {
    expect(parseChartSpec(['pie', 'A 3', 'B 4'].join('\n'))?.type).toBe('pie')
  })

  it('still rejects ambiguous shapes', () => {
    // Not a known type on the first line.
    expect(parseChartSpec(['column', 'Mon 12'].join('\n'))).toBeNull()
    // A row without a trailing number.
    expect(parseChartSpec(['bar', 'Mon twelve'].join('\n'))).toBeNull()
    // A bare type with no rows.
    expect(parseChartSpec('bar')).toBeNull()
    // JSON-looking text that fails structural validation stays invalid.
    expect(parseChartSpec('{"type":"bar","xKey":"a","series":[]}')).toBeNull()
  })

  it('caps the lenient form at the same data-point limit', () => {
    const rows = Array.from({ length: 501 }, (_, i) => `r${i} ${i}`)
    expect(parseChartSpec(['bar', ...rows].join('\n'))).toBeNull()
  })
})
