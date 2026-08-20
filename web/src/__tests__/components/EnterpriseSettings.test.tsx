import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { EnterpriseSettingsPage } from '@/components/settings/EnterpriseSettings'
import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { SidebarFooter } from '@/components/shell/SidebarShell'
import { useUIStore } from '@/stores/useUIStore'

const enterprise = vi.hoisted(() => ({
  refetch: vi.fn(),
  sync: vi.fn(),
}))

vi.mock('@tanstack/react-router', () => ({
  useLocation: () => ({ pathname: '/settings/enterprise' }),
}))

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}))

vi.mock('@/lib/motion', () => ({
  useMotionPreset: () => ({
    distance: 0,
    spring: { duration: 0 },
    transition: { duration: 0 },
  }),
}))

vi.mock('@/components/HealthDot', () => ({
  HealthDot: () => <span>Healthy</span>,
}))

vi.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button type="button">Theme</button>,
}))

vi.mock('@/queries', () => ({
  useAgentFilesQuery: () => ({ data: { agents: [] } }),
  useSkillFilesQuery: () => ({ data: { skills: [] } }),
  useMcpServersQuery: () => ({ data: { servers: [] } }),
  useSandboxSettingsQuery: () => ({ data: { denied_patterns: [] } }),
  useConductorStatusQuery: () => ({
    data: {
      enabled: true,
      enrolled: true,
      state: 'connected',
      installation_id: 'installation-1',
      project_id: 'project-1',
      project_name: 'evolint',
      project_display_name: 'Evolint',
      project_logo_url: null,
      member_display_name: 'Wyn',
      member_primary_role: 'admin',
      collection_level: 'L1',
      heartbeat_interval_seconds: 60,
      last_heartbeat_at: '2026-08-18T10:00:00Z',
      last_sync_at: '2026-08-18T10:00:00Z',
      last_success_at: '2026-08-18T10:00:00Z',
      manifest_revision: '12',
      offline: false,
      maintenance_required: false,
      error: null,
      resources: [
        {
          project_id: 'project-1',
          project_name: 'Evolint',
          resource_id: 'agent-1',
          version_id: 'version-2',
          version: '2.0.0',
          applied_version_id: 'version-1',
          applied_version: '1.0.0',
          release_channel: 'published',
          observed_state: 'update_pending',
          update_available: true,
          kind: 'agent',
          slug: 'support-agent',
        },
        {
          project_id: 'project-1',
          project_name: 'Evolint',
          resource_id: 'skill-1',
          version_id: 'version-2',
          version: '2.0.0',
          applied_version_id: 'version-1',
          applied_version: '1.0.0',
          release_channel: 'published',
          observed_state: 'update_pending',
          update_available: true,
          kind: 'skill',
          slug: 'release-readiness',
        },
        {
          project_id: 'project-1',
          project_name: 'Evolint',
          resource_id: 'plugin-1',
          version_id: 'version-2',
          version: '2.0.0',
          applied_version_id: 'version-1',
          applied_version: '1.0.0',
          release_channel: 'published',
          observed_state: 'trust_pending',
          update_available: true,
          kind: 'plugin',
          slug: 'release-toolkit',
          message: 'Review the updated tool permissions before applying.',
        },
      ],
      sync: {
        heartbeat: { state: 'healthy', last_attempt_at: null, last_success_at: '2026-08-18T10:00:00Z', error: null },
        resources: { state: 'healthy', last_attempt_at: null, last_success_at: '2026-08-18T10:00:00Z', error: null },
        inventory: { state: 'healthy', last_attempt_at: null, last_success_at: '2026-08-18T10:00:00Z', error: null },
        telemetry: { state: 'healthy', last_attempt_at: null, last_success_at: '2026-08-18T10:00:00Z', error: null },
      },
      telemetry: {
        pending_events: 12,
        capacity: 10_000,
        utilization_percent: 0.1,
        oldest_event_at: '2026-08-18T09:59:00Z',
        pending_requests: 1,
        pending_model_calls: 8,
        pending_tool_calls: 3,
        attributed_events: 9,
        tokens_in: 1200,
        tokens_out: 200,
        cache_read_tokens: 0,
        estimated_cost_usd_micros: 42_000,
        last_flush_accepted: 100,
        last_flush_duplicates: 2,
        delivery: {
          installation_id: 'installation-1',
          window_days: 30,
          window_start: '2026-07-19T10:00:00Z',
          window_end: '2026-08-18T10:00:00Z',
          events: 201,
          requests: 10,
          model_calls: 120,
          tool_calls: 71,
          tokens_in: 90_000,
          tokens_out: 12_000,
          cache_read_tokens: 5_000,
          estimated_cost_usd_micros: 900_000,
          unpriced_model_calls: 3,
          attributed_events: 133,
          attributed_requests: 7,
          attributed_model_calls: 80,
          attributed_tool_calls: 46,
          attributed_estimated_cost_usd_micros: 640_000,
        },
      },
    },
    isLoading: false,
    isError: false,
    refetch: enterprise.refetch,
  }),
  useObservabilitySummaryQuery: () => ({
    data: {
      window_start: '2026-07-19T10:00:00Z',
      window_end: '2026-08-18T10:00:00Z',
      sample_ratio: 1,
      totals: {
        turns: 42,
        llm_calls: 84,
        tool_calls: 30,
        input_tokens: 100_000,
        output_tokens: 20_000,
        cached_tokens: 10_000,
        cache_percent: 10,
        estimated_cost_usd: 1.25,
        errors: 0,
        failed_turns: 0,
        error_spans: 0,
        error_rate: 0,
      },
      latency_ms: {
        turn_p50: 400,
        turn_p95: 900,
        llm_p50: 300,
        llm_p95: 700,
        tool_p50: 50,
        tool_p95: 120,
      },
      daily_turns: [],
      bucket_size: 'day',
      time_series: [],
      by_model: [],
      cache_by_step: [],
      by_tool: [],
    },
    isLoading: false,
    isError: false,
    refetch: enterprise.refetch,
  }),
  useSyncConductorMutation: () => ({
    mutate: enterprise.sync,
    isPending: false,
    isError: false,
    error: null,
  }),
}))

describe('Enterprise settings', () => {
  beforeEach(() => {
    enterprise.refetch.mockReset()
    enterprise.sync.mockReset()
    useUIStore.setState({
      settingsOpen: true,
      settingsPath: 'enterprise',
      workbenchOpen: false,
      activeWorkbenchTool: null,
      activeWorkbenchTabId: null,
      workbenchTabs: [],
    })
  })

  it('shows the connected project, managed resources, usage, updates, and sync state', () => {
    render(<EnterpriseSettingsPage />)

    expect(screen.getByRole('heading', { name: 'Enterprise' })).toBeInTheDocument()
    expect(screen.getAllByText('Evolint').length).toBeGreaterThan(0)
    expect(screen.getByRole('tab', { name: /Library/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Usage/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Favorites/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Updates/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Sync/ })).toBeInTheDocument()
    expect(screen.getByText('support-agent')).toBeInTheDocument()
    expect(screen.getByText('release-readiness')).toBeInTheDocument()
    expect(screen.getByText('201')).toBeInTheDocument()
    expect(screen.getByText('Governed requests')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('Independent sync lanes')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Usage/ }))
    expect(screen.getByRole('heading', { name: 'Delivered to Conductor' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Local EvoFlux activity · 30 days' })).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('$1.25')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync Enterprise workspace' })).toBeEnabled()
  })

  it('lives in Settings and shows the connected project on the sidebar item', () => {
    render(<SettingsSidebar currentPath="/settings/enterprise" />)

    const item = screen.getByRole('button', { name: /Enterprise.*Evolint/ })
    expect(item).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('1 managed Agent update available')).toBeInTheDocument()
    expect(screen.getByText('1 managed Skill update available')).toBeInTheDocument()
    expect(screen.getByText('2 Enterprise notifications')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Enterprise' })).not.toBeInTheDocument()
  })

  it('uses vertical resource rows that disclose details and open native settings', () => {
    render(<EnterpriseSettingsPage />)

    fireEvent.click(screen.getByRole('tab', { name: /Library/ }))

    const agentRow = screen.getByText('support-agent').closest('button')
    expect(agentRow).not.toBeNull()
    if (!agentRow) throw new Error('Agent resource row is missing')
    expect(agentRow).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(agentRow)
    expect(agentRow).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Applied version')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open Agent settings' }))
    expect(useUIStore.getState().settingsPath).toBe('agents/support-agent')

    const pluginRow = screen.getByText('release-toolkit').closest('button')
    expect(pluginRow).not.toBeNull()
    if (!pluginRow) throw new Error('Plugin resource row is missing')
    fireEvent.click(pluginRow)
    expect(
      screen.getByText('Review the updated tool permissions before applying.'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open Plugin settings' }))
    expect(useUIStore.getState().settingsOpen).toBe(false)
    expect(useUIStore.getState().activeWorkbenchTool).toBe('plugins')
    expect(useUIStore.getState().workbenchOpen).toBe(true)
  })

  it('marks the global Settings gear when Enterprise needs attention', () => {
    render(<SidebarFooter />)

    expect(
      screen.getByRole('button', { name: 'Settings, 2 Enterprise notifications' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('settings-enterprise-attention')).toBeInTheDocument()
  })
})
