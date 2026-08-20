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

  it('renders Copilot premium requests with the correct unit and monthly reset', () => {
    render(
      <UsagePanel
        limits={[
          {
            limit_id: 'premium_interactions',
            limit_name: 'Premium requests',
            primary: {
              used_percent: 14.4,
              window_minutes: 30 * 24 * 60,
              resets_at: Date.UTC(2026, 5, 1) / 1000,
            },
            credits: {
              has_credits: true,
              unlimited: false,
              balance: '257/300',
              used: '43',
              total: '300',
              unit: 'premium requests',
            },
            plan_type: 'individual',
          },
        ]}
      />,
    )

    expect(screen.getByText('Plan: Individual')).toBeVisible()
    expect(screen.getByText('Monthly premium requests')).toBeVisible()
    expect(screen.getByText('86% remaining')).toBeVisible()
    expect(screen.getByText('43 of 300 premium requests used')).toBeVisible()
    expect(screen.getByText(/^Resets /)).toBeVisible()
    expect(
      screen.getByRole('progressbar', { name: 'Monthly premium requests' }),
    ).toHaveAttribute('aria-valuenow', '14')
  })
})
