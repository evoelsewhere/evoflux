import { beforeEach, describe, expect, it } from 'vitest'

import type { ConductorStatus } from '@/api/client'
import {
  buildEnterpriseNotices,
  enterpriseAttentionCount,
  loadEnterpriseFavorites,
  resourceHasUpdate,
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
      { kind: 'agent', slug: 'reviewer', state: 'update_pending' },
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
