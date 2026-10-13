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
