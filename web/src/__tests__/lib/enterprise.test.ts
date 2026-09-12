import { beforeEach, describe, expect, it } from 'vitest'

import type { ConductorStatus } from '@/api/client'
import {
  buildEnterpriseNotices,
  enterpriseAttentionCount,
  loadEnterpriseFavorites,
  resourceFailed,
  resourceHasUpdate,
  resourceIsLocal,
  saveEnterpriseFavorites,
} from '@/lib/enterprise'

const status = (): ConductorStatus => ({
  enabled: true,
  enrolled: true,
  state: 'in_sync',
  installation_id: 'installation-1',
  project_id: 'project-1',
  project_name: 'platform-core',
  project_display_name: 'Platform Core',
  project_logo_url: null,
  member_display_name: 'Mai',
  member_primary_role: 'user',
  collection_level: 'L1',
  heartbeat_interval_seconds: 60,
  last_heartbeat_at: '2026-08-18T00:00:00Z',
  last_sync_at: '2026-08-18T00:00:00Z',
  last_success_at: '2026-08-18T00:00:00Z',
  manifest_revision: 'cursor-1',
  offline: false,
  maintenance_required: false,
  error: null,
  resources: [],
  sync: {
    heartbeat: { state: 'healthy', last_attempt_at: null, last_success_at: null, error: null },
    resources: { state: 'healthy', last_attempt_at: null, last_success_at: null, error: null },
    inventory: { state: 'healthy', last_attempt_at: null, last_success_at: null, error: null },
    telemetry: { state: 'healthy', last_attempt_at: null, last_success_at: null, error: null },
  },
  telemetry: {
    pending_events: 0,
    capacity: 10_000,
    utilization_percent: 0,
    oldest_event_at: null,
    pending_requests: 0,
    pending_model_calls: 0,
    pending_tool_calls: 0,
    attributed_events: 0,
    tokens_in: 0,
    tokens_out: 0,
    cache_read_tokens: 0,
    estimated_cost_usd_micros: 0,
    last_flush_accepted: 0,
    last_flush_duplicates: 0,
    delivery: null,
  },
})

beforeEach(() => localStorage.clear())

describe('Enterprise view model', () => {
  it('prioritizes sync errors, updates and queue pressure', () => {
    const value = status()
    if (!value.telemetry) throw new Error('telemetry fixture missing')
    value.error = 'Inventory validation failed.'
    value.telemetry.pending_events = 8_500
    value.telemetry.utilization_percent = 85
    value.resources = [
      { kind: 'agent_team', slug: 'reviewer', state: 'update_pending' },
    ]

    expect(buildEnterpriseNotices(value).map((notice) => notice.id)).toEqual([
      'sync-error',
      'updates',
      'telemetry-capacity',
    ])
    expect(resourceHasUpdate(value.resources[0]!)).toBe(true)
    expect(enterpriseAttentionCount(value)).toBe(3)
  })

  it('does not mark a healthy connected workspace as attention', () => {
    expect(enterpriseAttentionCount(status())).toBe(0)
  })

  it('persists project resource favorites locally', () => {
    saveEnterpriseFavorites(new Set(['resource-b', 'resource-a']))

    expect([...loadEnterpriseFavorites()]).toEqual(['resource-a', 'resource-b'])
  })
})

describe('Enterprise view model · a resource that failed to apply', () => {
  const failing = (message: string | null = null) => {
    const value = status()
    value.resources = [
      {
        kind: 'skill',
        slug: 'integration-ping',
        state: 'error',
        observed_state: 'error',
        message,
      },
    ]
    return value
  }

  it('never reports the workspace as synchronized', () => {
    // No notice covered a failed resource, so the summary fell through to the
    // healthy branch and told the operator everything was fine.
    const notices = buildEnterpriseNotices(failing())
    expect(notices.some((notice) => notice.id === 'healthy')).toBe(false)
    expect(notices.some((notice) => notice.id === 'resource-errors')).toBe(true)
  })

  it('surfaces the reason, which names what has to change', () => {
    const notices = buildEnterpriseNotices(
      failing('Managed resource modes may contain only work and coding.'),
    )
    const notice = notices.find((item) => item.id === 'resource-errors')
    expect(notice?.tone).toBe('danger')
    expect(notice?.detail).toContain('work and coding')
  })

  it('counts towards the attention badge', () => {
    expect(enterpriseAttentionCount(failing())).toBeGreaterThan(0)
  })

  it('reports a failed sync lane even when the error field is empty', () => {
    // `state` can say error while `error` is null; only the latter was checked.
    const value = status()
    value.state = 'error'
    value.error = null
    const notices = buildEnterpriseNotices(value)
    expect(notices.some((notice) => notice.id === 'sync-error')).toBe(true)
    expect(notices.some((notice) => notice.id === 'healthy')).toBe(false)
  })
})

describe('Enterprise view model · resourceIsLocal', () => {
  it('is true only once the resource exists on this machine', () => {
    for (const state of ['applied', 'in_sync', 'drifted', 'dependency_missing']) {
      expect(
        resourceIsLocal({ kind: 'skill', slug: 's', state, observed_state: state }),
      ).toBe(true)
    }
    // Delivered but not applied: a local settings page for it would 404.
    for (const state of ['update_pending', 'trust_pending', 'error', 'incompatible']) {
      expect(
        resourceIsLocal({ kind: 'skill', slug: 's', state, observed_state: state }),
      ).toBe(false)
    }
  })

  it('is true for an update_pending resource that already has a version applied', () => {
    expect(
      resourceIsLocal({
        kind: 'agent_team',
        slug: 'release-review',
        state: 'update_pending',
        observed_state: 'update_pending',
        applied_version: '0.1.3',
      }),
    ).toBe(true)
  })

  it('treats a failed resource as retryable', () => {
    const record = (observed: string) => ({
      kind: 'skill' as const,
      slug: 's',
      state: observed,
      observed_state: observed,
    })
    expect(resourceFailed(record('error'))).toBe(true)
    expect(resourceFailed(record('incompatible'))).toBe(true)
    expect(resourceFailed(record('applied'))).toBe(false)
  })
})

describe('Enterprise view model · a resource whose dependencies did not resolve', () => {
  const withUnresolved = (): ConductorStatus => ({
    ...status(),
    resources: [
      {
        kind: 'agent_team',
        slug: 'release-review',
        state: 'dependency_missing',
        observed_state: 'dependency_missing',
        applied_version: '0.1.3',
        message: 'Published capabilities are not available — missing skills: release-audit.',
      },
    ],
  })

  it('never reports the workspace as synchronized', () => {
    const ids = buildEnterpriseNotices(withUnresolved()).map((notice) => notice.id)
    expect(ids).toContain('resource-dependencies')
    expect(ids).not.toContain('healthy')
  })

  it('names what did not resolve', () => {
    const notice = buildEnterpriseNotices(withUnresolved()).find(
      (item) => item.id === 'resource-dependencies',
    )
    expect(notice?.detail).toContain('release-audit')
  })

  it('counts towards the attention badge', () => {
    expect(enterpriseAttentionCount(withUnresolved())).toBe(1)
  })
})
