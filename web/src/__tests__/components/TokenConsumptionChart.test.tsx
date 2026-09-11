import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TokenConsumptionChart } from '@/routes/telemetry/summary/TokenConsumptionChart'

const buckets = [
  {
    bucket_start: '2026-01-01T00:00:00Z',
    turns: 2,
    llm_calls: 3,
    tool_calls: 4,
    failed_turns: 0,
    error_spans: 0,
    input_tokens: 5_400_000,
    output_tokens: 111_000,
    estimated_cost_usd: 1.2,
    turn_p95_ms: 2_000,
  },
  {
    bucket_start: '2026-01-02T00:00:00Z',
    turns: 1,
    llm_calls: 2,
    tool_calls: 1,
    failed_turns: 0,
    error_spans: 0,
    input_tokens: 1_800_000,
    output_tokens: 42_000,
    estimated_cost_usd: 0.5,
    turn_p95_ms: 1_500,
  },
]

function modelRow(
  bucket: string,
  providerModel: string,
  input: number,
  output: number,
  cached = 0,
  cacheWrite = 0,
) {
  const [provider, model] = providerModel.split(':')
  return {
    bucket_start: bucket,
    provider,
    model,
    provider_model: providerModel,
    input_tokens: input,
    output_tokens: output,
    cached_tokens: cached,
    cache_write_tokens: cacheWrite,
    fresh_input_tokens: Math.max(input - cached - cacheWrite, 0),
    cache_percent: input > 0 ? (cached / input) * 100 : 0,
    calls: 1,
  }
}

const tokensByModel = [
  modelRow('2026-01-01T00:00:00Z', 'openai:gpt-5.6', 4_000_000, 90_000, 3_000_000, 200_000),
  modelRow('2026-01-01T00:00:00Z', 'anthropic:sonnet', 1_400_000, 21_000, 700_000),
  modelRow('2026-01-02T00:00:00Z', 'openai:gpt-5.6', 1_800_000, 42_000, 1_200_000),
]

function renderChart() {
  return render(
    <TokenConsumptionChart
      data={buckets}
      bucketSize="day"
      tokensByModel={tokensByModel}
    />,
  )
}

describe('TokenConsumptionChart', () => {
  it('opens on every model, stacked, with the window total in the header', () => {
    const { container } = renderChart()

    expect(container).toHaveTextContent('7,353,000 tokens')
    // Both panels keep their own scale — the peak is the stack, not one model.
    expect(container).toHaveTextContent('Peak 5.4M')
    expect(container).toHaveTextContent('Peak 111K')
    // The legend names every model rather than leaving identity to colour.
    expect(screen.getByText('openai:gpt-5.6')).toBeInTheDocument()
    expect(screen.getByText('anthropic:sonnet')).toBeInTheDocument()
  })

  it('reports each model and the bucket cache rate on hover', () => {
    const { container } = renderChart()

    fireEvent.mouseEnter(container.querySelector('[data-chart-bucket="0"]')!)

    const tooltip = container.querySelector('[data-token-tooltip]')
    expect(tooltip).not.toBeNull()
    expect(tooltip).toHaveTextContent('4,000,000')
    expect(tooltip).toHaveTextContent('1,400,000')
    // 3.7M of this bucket's 5.4M input came from cache.
    expect(tooltip).toHaveTextContent('69% cached')
  })

  it('switches to one model split by what the provider charged for', () => {
    const { container } = renderChart()

    fireEvent.click(screen.getByRole('button', { name: 'Single model' }))

    expect(screen.getByText('Cache read')).toBeInTheDocument()
    expect(screen.getByText('Cache write')).toBeInTheDocument()
    expect(screen.getByText('Fresh input')).toBeInTheDocument()

    fireEvent.mouseEnter(container.querySelector('[data-chart-bucket="0"]')!)
    const tooltip = container.querySelector('[data-token-tooltip]')
    // The heaviest model is selected by default: 3M cached, 200K written,
    // 800K fresh — disjoint, and summing to its 4M input.
    expect(tooltip).toHaveTextContent('3,000,000')
    expect(tooltip).toHaveTextContent('200,000')
    expect(tooltip).toHaveTextContent('800,000')
  })

  it('drops a segment a bucket has none of instead of listing a zero', () => {
    const { container } = renderChart()

    fireEvent.click(screen.getByRole('button', { name: 'Single model' }))
    fireEvent.mouseEnter(container.querySelector('[data-chart-bucket="1"]')!)

    // Second bucket has no cache writes for this model.
    const tooltip = container.querySelector('[data-token-tooltip]')
    expect(tooltip).toHaveTextContent('Cache read')
    expect(tooltip).not.toHaveTextContent('Cache write')
  })

  it('falls back to every model when the window has none to single out', () => {
    render(
      <TokenConsumptionChart data={buckets} bucketSize="day" tokensByModel={[]} />,
    )

    expect(screen.getByRole('button', { name: 'Single model' })).toBeDisabled()
  })

  it('renders against a backend too old to send the breakdown', () => {
    // The desktop app can point at an externally managed backend. One built
    // before `tokens_by_model` existed omits it, and the whole telemetry page
    // used to go down with the chart.
    const { container } = render(
      <TokenConsumptionChart
        data={buckets}
        bucketSize="day"
        tokensByModel={undefined}
      />,
    )

    expect(container).toHaveTextContent('0 tokens')
    expect(screen.getByRole('button', { name: 'Single model' })).toBeDisabled()
  })
})
