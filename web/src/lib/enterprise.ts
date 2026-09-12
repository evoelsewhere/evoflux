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

/** Whether the resource exists on this machine, so a local settings page for
 * it will resolve. A delivered-but-unapplied resource has no local record. */
export function resourceIsLocal(
  resource: ConductorManagedResource | LegacyConductorResource,
): boolean {
  // "Is a version of this on disk right now?" — which is what decides whether
  // a local settings page exists to open. ``dependency_missing`` is applied
  // (its capabilities just did not resolve) and ``update_pending`` still has
  // the previous version applied, so neither belongs on the not-local side.
  if (
    ['applied', 'in_sync', 'drifted', 'dependency_missing'].includes(
      resourceState(resource),
    )
  ) {
    return true
  }
  return Boolean('applied_version' in resource && resource.applied_version)
}

export function resourceFailed(
  resource: ConductorManagedResource | LegacyConductorResource,
): boolean {
  // ``ownership_conflict`` belongs here: the release is not running as
  // published, and a pull is exactly the documented way back — the backend
  // accepts one for this state, so the card has to offer it.
  return ['error', 'incompatible', 'ownership_conflict'].includes(
    resourceState(resource),
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
  } else if (status.error || status.state === 'error') {
    notices.push({
      id: 'sync-error',
      tone: 'danger',
      title: 'A sync lane needs attention',
      detail: status.error ?? 'A sync lane reported a failure.',
      tab: 'sync',
    })
  }
  const failed = status.resources.filter(resourceFailed)
  if (failed.length > 0) {
    notices.push({
      id: 'resource-errors',
      tone: 'danger',
      title: `${failed.length} managed ${failed.length === 1 ? 'resource' : 'resources'} could not be applied`,
      // The reason names the file or field that was rejected, which is the
      // only thing that tells an operator what to change.
      detail:
        failed
          .map((resource) => resource.message)
          .find((message): message is string => Boolean(message)) ??
        'Open the resource for the reason it was rejected.',
      tab: 'updates',
    })
  }
  // An applied release whose Skills or MCP servers did not resolve is running
  // differently from what the project published. It is not "synchronized", and
  // the summary said exactly that until this notice existed.
  const unresolved = status.resources.filter(
    (resource) => resourceState(resource) === 'dependency_missing',
  )
  if (unresolved.length > 0) {
    notices.push({
      id: 'resource-dependencies',
      tone: 'warning',
      title: `${unresolved.length} managed ${unresolved.length === 1 ? 'resource is' : 'resources are'} missing a dependency`,
      detail:
        unresolved
          .map((resource) => resource.message)
          .find((message): message is string => Boolean(message)) ??
        'Open the resource to see which Skill or MCP server did not resolve.',
      tab: 'library',
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
