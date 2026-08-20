import type {
  ConductorManagedResource,
  ConductorStatus,
  LegacyConductorResource,
} from '@/api/client'
import { STORAGE_KEYS } from '@/lib/storage-keys'

export const ENTERPRISE_TABS = [
  'overview',
  'library',
  'usage',
  'favorites',
  'updates',
  'sync',
] as const

export type EnterpriseTab = (typeof ENTERPRISE_TABS)[number]

export type EnterpriseNotice = {
  id: string
  tone: 'danger' | 'warning' | 'info' | 'success'
  title: string
  detail: string
  tab: EnterpriseTab
}

export function isEnterpriseTab(value: unknown): value is EnterpriseTab {
  return typeof value === 'string' && ENTERPRISE_TABS.includes(value as EnterpriseTab)
}

export function resourceId(
  resource: ConductorManagedResource | LegacyConductorResource,
): string {
  return resource.resource_id ?? `${resource.kind}:${resource.slug}`
}

export function resourceState(
  resource: ConductorManagedResource | LegacyConductorResource,
): string {
  return resource.observed_state ?? resource.state ?? 'pending'
}

export function resourceHasUpdate(
  resource: ConductorManagedResource | LegacyConductorResource,
): boolean {
  return (
    ('update_available' in resource && resource.update_available === true) ||
    ['update_pending', 'trust_pending'].includes(resourceState(resource))
  )
}

export function buildEnterpriseNotices(status: ConductorStatus): EnterpriseNotice[] {
  const notices: EnterpriseNotice[] = []
  const telemetry = status.telemetry
  if (status.state === 'offline' || status.offline) {
    notices.push({
      id: 'offline',
      tone: 'danger',
      title: 'Conductor is offline',
      detail: 'Local work continues, but project changes and telemetry are waiting.',
      tab: 'sync',
    })
  } else if (status.error) {
    notices.push({
      id: 'sync-error',
      tone: 'danger',
      title: 'A sync lane needs attention',
      detail: status.error,
      tab: 'sync',
    })
  }
  const updates = status.resources.filter(resourceHasUpdate).length
  if (updates > 0) {
    notices.push({
      id: 'updates',
      tone: 'warning',
      title: `${updates} managed ${updates === 1 ? 'resource' : 'resources'} ready to review`,
      detail: 'Review versions and trust changes before applying them locally.',
      tab: 'updates',
    })
  }
  const utilization = telemetry?.utilization_percent ?? 0
  if (utilization >= 80) {
    notices.push({
      id: 'telemetry-capacity',
      tone: utilization >= 95 ? 'danger' : 'warning',
      title: 'Telemetry queue is filling up',
      detail: `${(telemetry?.pending_events ?? 0).toLocaleString()} events are waiting for Conductor.`,
      tab: 'sync',
    })
  } else if ((telemetry?.pending_events ?? 0) > 0) {
    notices.push({
      id: 'telemetry-pending',
      tone: 'info',
      title: 'Usage delivery is catching up',
      detail: `${(telemetry?.pending_events ?? 0).toLocaleString()} events remain in the durable queue.`,
      tab: 'sync',
    })
  }
  if (notices.length === 0 && status.enrolled) {
    notices.push({
      id: 'healthy',
      tone: 'success',
      title: 'Enterprise workspace is synchronized',
      detail: 'No project updates or telemetry backlog need attention.',
      tab: 'sync',
    })
  }
  return notices
}

export function enterpriseAttentionCount(status: ConductorStatus | undefined): number {
  if (!status?.enrolled) return 0
  return buildEnterpriseNotices(status).filter((notice) => notice.tone !== 'success').length
}

export function loadEnterpriseFavorites(): Set<string> {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEYS.enterprise.favorites) ?? '[]')
    if (!Array.isArray(value)) return new Set()
    return new Set(value.filter((item): item is string => typeof item === 'string'))
  } catch {
    return new Set()
  }
}

export function saveEnterpriseFavorites(values: ReadonlySet<string>): void {
  try {
    localStorage.setItem(
      STORAGE_KEYS.enterprise.favorites,
      JSON.stringify([...values].sort()),
    )
  } catch {
    // Favorites are a local convenience. A full/unavailable storage area must
    // never prevent the managed resource library from rendering.
  }
}
