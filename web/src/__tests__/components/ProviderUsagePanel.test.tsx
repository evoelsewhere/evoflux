import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UsagePanel } from '@/routes/settings.providers'

describe('provider usage panel', () => {
  it('renders a monthly remaining quota with absolute credit usage', () => {
    render(
      <UsagePanel
        limits={[
          {
            limit_id: 'codex',
            primary: {
              used_percent: 85.7635,
              window_minutes: 30 * 24 * 60,
              resets_at: Date.UTC(2026, 8, 1) / 1000,
            },
            credits: {
              has_credits: true,
              unlimited: false,
              balance: '28473',
              used: '171527',
              total: '200000',
            },
            plan_type: 'enterprise_cbp_usage_based',
          },
        ]}
      />,
    )

    expect(screen.getByText('General usage limits')).toBeVisible()
    expect(screen.getByText('Plan: Enterprise usage-based')).toBeVisible()
    expect(screen.getByText('Monthly usage')).toBeVisible()
    expect(screen.getByText('14% remaining')).toBeVisible()
    expect(screen.getByText('171,527 of 200,000 credits used')).toBeVisible()
    expect(screen.getByText(/^Resets /)).toBeVisible()
    expect(screen.getByRole('progressbar', { name: 'Monthly usage' })).toHaveAttribute(
      'aria-valuenow',
      '86',
    )
  })

  it('keeps remaining-credit text when no quota window or total is available', () => {
    render(
      <UsagePanel
        limits={[
          {
            limit_id: 'codex',
            credits: {
              has_credits: true,
              unlimited: false,
              balance: '115125.62',
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('115,125.62 credits remaining')).toBeVisible()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})
