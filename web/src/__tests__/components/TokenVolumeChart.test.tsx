import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TokenVolumeChart } from '@/routes/telemetry/charts'

const data = [
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

describe('TokenVolumeChart', () => {
  it('renders aligned independent scales and a bucket tooltip', () => {
    const { container } = render(
      <TokenVolumeChart data={data} bucketSize="day" />,
    )

    expect(container).toHaveTextContent('Input tokens')
    expect(container).toHaveTextContent('Output tokens')
    expect(container).toHaveTextContent('Peak 5.4M')
    expect(container).toHaveTextContent('Peak 111K')

    const secondBucket = container.querySelector('[data-chart-bucket="1"]')
    expect(secondBucket).not.toBeNull()
    fireEvent.mouseEnter(secondBucket!)

    const tooltip = container.querySelector('[data-token-tooltip]')
    expect(tooltip).not.toBeNull()
    expect(tooltip).toHaveTextContent('1.8M')
    expect(tooltip).toHaveTextContent('42K')
  })
})
