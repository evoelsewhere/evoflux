import { useId, useState, type ReactNode } from 'react'
import {
  Activity,
  AlertTriangle,
  BellRing,
  Bot,
  Boxes,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  CloudOff,
  CloudUpload,
  Coins,
  Download,
  HeartPulse,
  LibraryBig,
  PackageCheck,
  PlugZap,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Star,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

import {
  approveConductorResource,
  pullConductorResource,
  type ConductorManagedResource,
  type ConductorStatus,
  type ConductorSyncLaneStatus,
  type LegacyConductorResource,
} from '@/api/client'
import { SettingsPage } from '@/components/settings/SettingsLayout'
import { EnterpriseAttentionDot } from '@/components/settings/EnterpriseAttentionDot'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  buildEnterpriseNotices,
  enterpriseAttentionCount,
  isEnterpriseTab,
  loadEnterpriseFavorites,
  resourceHasUpdate,
  resourceId,
  resourceState,
  saveEnterpriseFavorites,
  type EnterpriseNotice,
  type EnterpriseTab,
} from '@/lib/enterprise'
import {
  useConductorStatusQuery,
  useObservabilitySummaryQuery,
  useSyncConductorMutation,
} from '@/queries'
import { SummaryView } from '@/routes/telemetry/summary/SummaryView'
import { useUIStore } from '@/stores/useUIStore'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { formatCompact, formatUsd } from '@/utils/telemetryFormat'

type ManagedResource = ConductorManagedResource | LegacyConductorResource
type ResourceKindFilter = 'all' | 'agent' | 'skill' | 'plugin'

const TAB_LABELS: Array<{
  value: EnterpriseTab
  label: string
  shortLabel?: string
  Icon: LucideIcon
}> = [
  { value: 'overview', label: 'Overview', Icon: CircleGauge },
  { value: 'library', label: 'Library', Icon: LibraryBig },
  { value: 'usage', label: 'Usage', Icon: Activity },
  { value: 'favorites', label: 'Favorites', shortLabel: 'Saved', Icon: Star },
  { value: 'updates', label: 'Updates', Icon: BellRing },
  { value: 'sync', label: 'Sync', Icon: CloudUpload },
]

const EMPTY_LANE: ConductorSyncLaneStatus = {
  state: 'idle',
  last_attempt_at: null,
  last_success_at: null,
  error: null,
}

export function EnterpriseSettingsPage() {
  const [activeTab, setActiveTab] = useState<EnterpriseTab>('overview')
  const [days, setDays] = useState<7 | 30 | 90>(30)
  const statusQuery = useConductorStatusQuery()
  const usageQuery = useObservabilitySummaryQuery(days)
  const syncMutation = useSyncConductorMutation()
  const navigateSettings = useSettingsNavigate()
  const [favorites, setFavorites] = useState(loadEnterpriseFavorites)
  const [kindFilter, setKindFilter] = useState<ResourceKindFilter>('all')
  const [resourceAction, setResourceAction] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const status = statusQuery.data
  const resources = status?.resources ?? []
  const notices = status ? buildEnterpriseNotices(status) : []
  const attentionCount = enterpriseAttentionCount(status)
  const projectName = status?.project_display_name ?? status?.project_name

  const setSearch = (next: { tab?: EnterpriseTab; days?: 7 | 30 | 90 }) => {
    if (next.tab) setActiveTab(next.tab)
    if (next.days) setDays(next.days)
  }

  const toggleFavorite = (id: string) => {
    setFavorites((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      saveEnterpriseFavorites(next)
      return next
    })
  }

  const runResourceAction = async (
    resource: ManagedResource,
    action: 'pull' | 'approve',
  ) => {
    const id = resource.resource_id
    if (!id) return
    setResourceAction(`${action}:${id}`)
    setActionError(null)
    try {
      if (action === 'approve') await approveConductorResource(id)
      else await pullConductorResource(id)
      await statusQuery.refetch()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'The resource action failed.')
    } finally {
      setResourceAction(null)
    }
  }

  const openResourceSettings = (resource: ManagedResource) => {
    if (resource.kind === 'agent') {
      navigateSettings('/settings/agents/$name', {
        params: { name: resource.slug },
      })
      return
    }
    if (resource.kind === 'skill') {
      navigateSettings('/settings/skills/$name', {
        params: { name: resource.slug },
      })
      return
    }
    const ui = useUIStore.getState()
    ui.closeSettings()
    ui.openWorkbenchTool('plugins')
  }

  return (
    <SettingsPage
      icon={Building2}
      title="Enterprise"
      size="full"
      lede={
        <span className="flex flex-wrap items-center gap-2">
          <span>Managed intelligence, local usage and delivery health for this installation.</span>
          <Badge
            variant={status?.enrolled ? 'secondary' : 'outline'}
            className="max-w-[16rem]"
          >
            <span
              aria-hidden="true"
              className={`size-1.5 rounded-full ${
                status?.enrolled && !status.offline
                  ? 'bg-(--color-success)'
                  : 'bg-(--color-text-subtle)'
              }`}
            />
            <span className="truncate">{projectName ?? 'Not connected'}</span>
          </Badge>
        </span>
      }
      actions={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSearch({ tab: 'updates' })}
            aria-label="Open Enterprise notifications"
            className="relative"
          >
            <BellRing />
            {notices.filter((notice) => notice.tone !== 'success').length > 0 ? (
              <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-(--color-warning) px-1 text-center font-mono text-[9px] leading-4 text-(--color-text-on-accent)">
                {notices.filter((notice) => notice.tone !== 'success').length}
              </span>
            ) : null}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => syncMutation.mutate()}
            disabled={!status?.enrolled || syncMutation.isPending}
            aria-label="Sync Enterprise workspace"
          >
            <RefreshCw
              className={
                syncMutation.isPending ? 'animate-spin motion-reduce:animate-none' : ''
              }
            />
            <span className="hidden sm:inline">Sync now</span>
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        <div className="border-b border-(--color-border-subtle) pb-3">
          <Tabs
            value={activeTab}
            onValueChange={(value) => {
              if (isEnterpriseTab(value)) setSearch({ tab: value })
            }}
          >
            <TabsList
              aria-label="Enterprise workspace sections"
              className="h-9 max-w-full justify-start overflow-x-auto [scrollbar-width:none] md:w-fit"
            >
              {TAB_LABELS.map(({ value, label, shortLabel, Icon }) => (
                <TabsTrigger key={value} value={value} className="min-w-fit px-2.5 text-xs">
                  <Icon aria-hidden="true" />
                  <span className="hidden sm:inline">{label}</span>
                  <span className="sm:hidden">{shortLabel ?? label}</span>
                  {value === 'updates' && attentionCount > 0 ? (
                    <EnterpriseAttentionDot
                      label={`${attentionCount} Enterprise ${attentionCount === 1 ? 'notification' : 'notifications'}`}
                    />
                  ) : null}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>

        <div>
            {statusQuery.isLoading ? (
              <EnterpriseSkeleton />
            ) : statusQuery.isError ? (
              <ErrorPanel onRetry={() => void statusQuery.refetch()} />
            ) : !status?.enrolled ? (
              <DisconnectedPanel />
            ) : (
              <>
                {actionError ? (
                  <div role="alert" className="mb-4 rounded-lg border border-(--color-error)/30 bg-(--color-error-subtle) px-4 py-3 text-sm text-(--color-error)">
                    {actionError}
                  </div>
                ) : null}
                {syncMutation.isError ? (
                  <div role="alert" className="mb-4 rounded-lg border border-(--color-error)/30 bg-(--color-error-subtle) px-4 py-3 text-sm text-(--color-error)">
                    {syncMutation.error instanceof Error
                      ? syncMutation.error.message
                      : 'Manual synchronization failed.'}
                  </div>
                ) : null}

                {activeTab === 'overview' ? (
                  <OverviewPanel
                    status={status}
                    resources={resources}
                    notices={notices}
                    favorites={favorites}
                    onFavorite={toggleFavorite}
                    onNavigate={(tab) => setSearch({ tab })}
                    onOpenSettings={openResourceSettings}
                  />
                ) : null}
                {activeTab === 'library' ? (
                  <LibraryPanel
                    resources={resources}
                    filter={kindFilter}
                    onFilter={setKindFilter}
                    favorites={favorites}
                    onFavorite={toggleFavorite}
                    resourceAction={resourceAction}
                    onResourceAction={runResourceAction}
                    onOpenSettings={openResourceSettings}
                  />
                ) : null}
                {activeTab === 'usage' ? (
                  <UsagePanel
                    days={days}
                    onDaysChange={(value) => setSearch({ days: value })}
                    query={usageQuery}
                    pending={status.telemetry}
                  />
                ) : null}
                {activeTab === 'favorites' ? (
                  <ResourceListPanel
                    title="Favorite project resources"
                    description="Saved on this EvoFlux installation for quick access. Favorites do not change project policy."
                    resources={resources.filter((resource) => favorites.has(resourceId(resource)))}
                    empty="Star an Agent, Skill, or Plugin from the project library to keep it here."
                    favorites={favorites}
                    onFavorite={toggleFavorite}
                    resourceAction={resourceAction}
                    onResourceAction={runResourceAction}
                    onOpenSettings={openResourceSettings}
                  />
                ) : null}
                {activeTab === 'updates' ? (
                  <UpdatesPanel
                    notices={notices}
                    resources={resources.filter(resourceHasUpdate)}
                    favorites={favorites}
                    onFavorite={toggleFavorite}
                    resourceAction={resourceAction}
                    onResourceAction={runResourceAction}
                    onNavigate={(tab) => setSearch({ tab })}
                    onOpenSettings={openResourceSettings}
                  />
                ) : null}
                {activeTab === 'sync' ? (
                  <SyncPanel status={status} onSync={() => syncMutation.mutate()} syncing={syncMutation.isPending} />
                ) : null}
              </>
            )}
        </div>
      </div>
    </SettingsPage>
  )
}

function OverviewPanel({
  status,
  resources,
  notices,
  favorites,
  onFavorite,
  onNavigate,
  onOpenSettings,
}: {
  status: ConductorStatus
  resources: ManagedResource[]
  notices: EnterpriseNotice[]
  favorites: Set<string>
  onFavorite: (id: string) => void
  onNavigate: (tab: EnterpriseTab) => void
  onOpenSettings: (resource: ManagedResource) => void
}) {
  const pending = status.telemetry?.pending_events ?? 0
  const delivery = status.telemetry?.delivery
  const synced = resources.filter((resource) => ['applied', 'in_sync'].includes(resourceState(resource))).length
  return (
    <div className="space-y-6">
      <section aria-labelledby="enterprise-summary-title">
        <div className="mb-3 flex flex-col items-start gap-2 sm:flex-row sm:items-end sm:justify-between sm:gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-(--color-text-muted)">Workspace report</p>
            <h2 id="enterprise-summary-title" className="mt-1 text-xl font-semibold text-(--color-text)">
              Your governed workspace at a glance
            </h2>
          </div>
          <span className="text-xs text-(--color-text-subtle)">Conductor receipt · last 30 days</span>
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric icon={PackageCheck} label="Managed resources" value={`${synced}/${resources.length}`} hint="Applied or in sync" />
          <Metric icon={HeartPulse} label="Delivered events" value={delivery ? formatCompact(delivery.events) : '—'} hint={delivery ? `${formatCompact(delivery.model_calls)} model · ${formatCompact(delivery.tool_calls)} tool` : 'Waiting for delivery summary'} />
          <Metric icon={ShieldCheck} label="Governed requests" value={delivery ? formatCompact(delivery.attributed_requests) : '—'} hint={delivery ? `${formatCompact(delivery.attributed_events)} attributed events` : 'Conductor attribution only'} />
          <Metric icon={CloudUpload} label="Pending delivery" value={pending.toLocaleString()} hint={pending > 0 ? 'Durable telemetry queue' : 'Telemetry caught up'} tone={pending > 0 ? 'warning' : 'success'} />
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.6fr)]">
        <section className="min-w-0 rounded-xl border border-(--color-border) bg-(--bg-card)">
          <SectionTitle title="Managed intelligence" description="Agents, Skills, and Plugins supplied by your project." action="Open library" onAction={() => onNavigate('library')} />
          <div className="grid gap-px border-t border-(--color-border-subtle) bg-(--color-border-subtle) sm:grid-cols-3">
            <ResourceKindSummary kind="agent" resources={resources} />
            <ResourceKindSummary kind="skill" resources={resources} />
            <ResourceKindSummary kind="plugin" resources={resources} />
          </div>
          <div className="border-t border-(--color-border-subtle) p-3">
            {resources.length === 0 ? (
              <EmptyMessage>There are no visible managed resources in this project yet.</EmptyMessage>
            ) : (
              <div className="divide-y divide-(--color-border-subtle) overflow-hidden rounded-lg border border-(--color-border-subtle)">
                {resources.slice(0, 4).map((resource) => (
                  <CompactResourceRow
                    key={resourceId(resource)}
                    resource={resource}
                    favorite={favorites.has(resourceId(resource))}
                    onFavorite={onFavorite}
                    onOpenSettings={onOpenSettings}
                  />
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="rounded-xl border border-(--color-border) bg-(--bg-card)">
          <SectionTitle title="Notifications" description="Updates and sync conditions that need a decision." action="View all" onAction={() => onNavigate('updates')} />
          <div className="divide-y divide-(--color-border-subtle) border-t border-(--color-border-subtle)">
            {notices.slice(0, 4).map((notice) => (
              <button key={notice.id} type="button" onClick={() => onNavigate(notice.tab)} className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-(--bg-key)/40">
                <NoticeIcon tone={notice.tone} />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-(--color-text)">{notice.title}</span>
                  <span className="mt-0.5 block text-xs leading-5 text-(--color-text-muted)">{notice.detail}</span>
                </span>
                <ChevronRight className="mt-1 size-3.5 shrink-0 text-(--color-text-subtle)" />
              </button>
            ))}
          </div>
        </section>
      </div>

      <SyncStrip status={status} onNavigate={() => onNavigate('sync')} />
    </div>
  )
}

function LibraryPanel({
  resources,
  filter,
  onFilter,
  ...props
}: {
  resources: ManagedResource[]
  filter: ResourceKindFilter
  onFilter: (value: ResourceKindFilter) => void
  favorites: Set<string>
  onFavorite: (id: string) => void
  resourceAction: string | null
  onResourceAction: (resource: ManagedResource, action: 'pull' | 'approve') => Promise<void>
  onOpenSettings: (resource: ManagedResource) => void
}) {
  const visible = filter === 'all' ? resources : resources.filter((resource) => resource.kind === filter)
  return (
    <div className="space-y-4">
      <PageIntro title="Project library" description="Project-managed intelligence available to this EvoFlux installation. Managed resources remain read-only locally." />
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter project resources">
        {(['all', 'agent', 'skill', 'plugin'] as const).map((kind) => (
          <Button key={kind} size="sm" variant={filter === kind ? 'secondary' : 'ghost'} onClick={() => onFilter(kind)}>
            {kind === 'all' ? 'All' : `${kind[0]!.toUpperCase()}${kind.slice(1)}s`}
            <span className="font-mono text-[10px] text-(--color-text-muted)">{kind === 'all' ? resources.length : resources.filter((resource) => resource.kind === kind).length}</span>
          </Button>
        ))}
      </div>
      <ResourceListPanel title="" description="" resources={visible} empty="No managed resources match this filter." {...props} />
    </div>
  )
}

function ResourceListPanel({
  title,
  description,
  resources,
  empty,
  favorites,
  onFavorite,
  resourceAction,
  onResourceAction,
  onOpenSettings,
}: {
  title: string
  description: string
  resources: ManagedResource[]
  empty: string
  favorites: Set<string>
  onFavorite: (id: string) => void
  resourceAction: string | null
  onResourceAction: (resource: ManagedResource, action: 'pull' | 'approve') => Promise<void>
  onOpenSettings: (resource: ManagedResource) => void
}) {
  return (
    <section>
      {title ? <PageIntro title={title} description={description} /> : null}
      {resources.length === 0 ? (
        <EmptyMessage className="mt-4">{empty}</EmptyMessage>
      ) : (
        <div className="mt-4 divide-y divide-(--color-border-subtle) overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card)">
          {resources.map((resource) => (
            <ResourceListRow
              key={resourceId(resource)}
              resource={resource}
              favorite={favorites.has(resourceId(resource))}
              onFavorite={onFavorite}
              action={resourceAction}
              onAction={onResourceAction}
              onOpenSettings={onOpenSettings}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function UsagePanel({
  days,
  onDaysChange,
  query,
  pending,
}: {
  days: 7 | 30 | 90
  onDaysChange: (value: 7 | 30 | 90) => void
  query: ReturnType<typeof useObservabilitySummaryQuery>
  pending: ConductorStatus['telemetry']
}) {
  const delivery = pending?.delivery
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageIntro title="Usage report" description="Conductor receipts and local activity are shown separately because they have different retention and attribution scopes." />
        <div className="flex rounded-lg border border-(--color-border) bg-(--bg-page) p-0.5" role="group" aria-label="Usage period">
          {([7, 30, 90] as const).map((value) => (
            <button key={value} type="button" onClick={() => onDaysChange(value)} aria-pressed={days === value} className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${days === value ? 'bg-(--bg-card) text-(--color-text) shadow-sm' : 'text-(--color-text-muted) hover:text-(--color-text)'}`}>
              {value}d
            </button>
          ))}
        </div>
      </div>
      <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4" aria-labelledby="conductor-delivery-title">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="conductor-delivery-title" className="text-sm font-semibold text-(--color-text)">Delivered to Conductor</h2>
            <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">Authoritative receipt for this member and installation over the last {delivery?.window_days ?? 30} days. Governed attribution is the subset used by project analytics.</p>
          </div>
          <Badge variant="secondary">{delivery ? `As of ${formatTimestamp(delivery.window_end)}` : 'Waiting for sync'}</Badge>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric icon={Activity} label="Received events" value={delivery ? formatCompact(delivery.events) : '—'} hint={delivery ? `${formatCompact(delivery.requests)} request IDs` : 'Refreshes on telemetry sync'} />
          <Metric icon={Bot} label="Model calls" value={delivery ? formatCompact(delivery.model_calls) : '—'} hint={delivery ? `${formatCompact(delivery.tokens_in + delivery.tokens_out)} input + output tokens` : 'No server receipt yet'} />
          <Metric icon={Wrench} label="Tool calls" value={delivery ? formatCompact(delivery.tool_calls) : '—'} hint={delivery ? `${formatCompact(delivery.attributed_tool_calls)} governed-attributed` : 'No server receipt yet'} />
          <Metric icon={Coins} label="Received estimate" value={delivery ? formatUsd(delivery.estimated_cost_usd_micros / 1_000_000) : '—'} hint={delivery ? `${formatCompact(delivery.unpriced_model_calls)} unpriced model calls` : 'Estimate, not billing'} />
        </div>
        {delivery ? (
          <div className="mt-4 rounded-lg border border-(--color-border-subtle) bg-(--bg-key)/30 px-3 py-2 text-xs leading-5 text-(--color-text-muted)">
            <strong className="font-semibold text-(--color-text)">{formatCompact(delivery.attributed_events)} governed-attributed events</strong>
            {' '}across {formatCompact(delivery.attributed_requests)} requests are eligible for Conductor project analytics. The remaining received events are still delivered, but are not linked to a managed project resource.
          </div>
        ) : null}
      </section>
      <div className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-(--color-text)">Waiting to deliver</h2>
          <p className="mt-1 text-xs text-(--color-text-muted)">Durable local queue only. These values return to zero after Conductor accepts or deduplicates the events.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric icon={CloudUpload} label="Queued events" value={(pending?.pending_events ?? 0).toLocaleString()} hint={`${(pending?.attributed_events ?? 0).toLocaleString()} project-attributed`} />
          <Metric icon={Bot} label="Queued model calls" value={(pending?.pending_model_calls ?? 0).toLocaleString()} hint={`${formatCompact(pending?.tokens_in ?? 0)} input tokens`} />
          <Metric icon={Wrench} label="Queued tool calls" value={(pending?.pending_tool_calls ?? 0).toLocaleString()} hint="Metadata only" />
          <Metric icon={Coins} label="Queued estimate" value={formatUsd((pending?.estimated_cost_usd_micros ?? 0) / 1_000_000)} hint="Awaiting Conductor" />
        </div>
      </div>
      <section aria-labelledby="local-activity-title">
        <div className="mb-3">
          <h2 id="local-activity-title" className="text-sm font-semibold text-(--color-text)">Local EvoFlux activity · {days} days</h2>
          <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">Local OTEL retention can include activity from before this project was connected and internal operations that are not sent to Conductor. It is not expected to equal the receipt above.</p>
        </div>
        {query.isLoading ? <EnterpriseSkeleton compact /> : query.isError ? <ErrorPanel onRetry={() => void query.refetch()} /> : query.data ? <SummaryView data={query.data} /> : <EmptyMessage>No local activity was recorded in this period.</EmptyMessage>}
      </section>
    </div>
  )
}

function UpdatesPanel({ notices, resources, onNavigate, ...props }: {
  notices: EnterpriseNotice[]
  resources: ManagedResource[]
  favorites: Set<string>
  onFavorite: (id: string) => void
  resourceAction: string | null
  onResourceAction: (resource: ManagedResource, action: 'pull' | 'approve') => Promise<void>
  onNavigate: (tab: EnterpriseTab) => void
  onOpenSettings: (resource: ManagedResource) => void
}) {
  return (
    <div className="space-y-5">
      <PageIntro title="Notifications & updates" description="Review new project versions, local trust decisions, and delivery conditions before they affect your runtime." />
      <div className="grid gap-3 lg:grid-cols-2">
        {notices.map((notice) => (
          <button key={notice.id} type="button" onClick={() => onNavigate(notice.tab)} className="flex items-start gap-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4 text-left transition-colors hover:border-(--color-border-strong)">
            <NoticeIcon tone={notice.tone} />
            <span>
              <span className="block text-sm font-semibold text-(--color-text)">{notice.title}</span>
              <span className="mt-1 block text-xs leading-5 text-(--color-text-muted)">{notice.detail}</span>
            </span>
          </button>
        ))}
      </div>
      <ResourceListPanel title="Version updates" description="Applied and desired versions are shown separately so pending changes remain explicit." resources={resources} empty="All managed resources are on their current approved versions." {...props} />
    </div>
  )
}

function SyncPanel({ status, onSync, syncing }: { status: ConductorStatus; onSync: () => void; syncing: boolean }) {
  const sync = status.sync
  const telemetry = status.telemetry
  const lanes: Array<[string, ConductorSyncLaneStatus, LucideIcon]> = [
    ['Connection heartbeat', sync?.heartbeat ?? EMPTY_LANE, HeartPulse],
    ['Resource changes', sync?.resources ?? EMPTY_LANE, Boxes],
    ['Inventory report', sync?.inventory ?? EMPTY_LANE, PackageCheck],
    ['Usage delivery', sync?.telemetry ?? EMPTY_LANE, CloudUpload],
  ]
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageIntro title="Sync report" description="Each lane runs independently. An inventory problem cannot block usage delivery or the connection heartbeat." />
        <Button variant="outline" onClick={onSync} disabled={syncing}>
          <RefreshCw className={syncing ? 'animate-spin motion-reduce:animate-none' : ''} />
          Sync now
        </Button>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {lanes.map(([label, lane, Icon]) => <LaneCard key={label} label={label} lane={lane} Icon={Icon} />)}
      </div>
      <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-(--color-text)">Durable telemetry queue</h2>
            <p className="mt-1 text-xs text-(--color-text-muted)">Events are removed only after Conductor accepts or deduplicates the batch.</p>
          </div>
          <Badge variant={(telemetry?.utilization_percent ?? 0) >= 80 ? 'destructive' : 'secondary'}>
            {(telemetry?.pending_events ?? 0).toLocaleString()} / {(telemetry?.capacity ?? 0).toLocaleString()}
          </Badge>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-(--bg-key)" aria-label={`Telemetry queue ${telemetry?.utilization_percent ?? 0}% full`}>
          <div className={`h-full rounded-full transition-[width] duration-(--motion-base) ${(telemetry?.utilization_percent ?? 0) >= 80 ? 'bg-(--color-warning)' : 'bg-(--color-accent)'}`} style={{ width: `${Math.min(100, telemetry?.utilization_percent ?? 0)}%` }} />
        </div>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <QueueStat label="Oldest event" value={formatTimestamp(telemetry?.oldest_event_at)} />
          <QueueStat label="Last batch accepted" value={(telemetry?.last_flush_accepted ?? 0).toLocaleString()} />
          <QueueStat label="Last batch duplicates" value={(telemetry?.last_flush_duplicates ?? 0).toLocaleString()} />
          <QueueStat label="Delivery summary" value={formatTimestamp(telemetry?.delivery?.window_end)} />
          <QueueStat label="Collection level" value={status.collection_level ?? 'Not reported'} />
        </dl>
      </section>
      <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
        <h2 className="text-sm font-semibold text-(--color-text)">Connection identity</h2>
        <dl className="mt-3 grid gap-x-8 gap-y-3 text-xs sm:grid-cols-2">
          <IdentityRow label="Project" value={status.project_display_name ?? status.project_name ?? '—'} />
          <IdentityRow label="Member" value={status.member_display_name ?? '—'} />
          <IdentityRow label="Primary role" value={status.member_primary_role ?? '—'} />
          <IdentityRow label="Installation" value={status.installation_id ? `${status.installation_id.slice(0, 8)}…` : '—'} mono />
        </dl>
      </section>
    </div>
  )
}

function ResourceListRow({
  resource,
  favorite,
  onFavorite,
  action,
  onAction,
  onOpenSettings,
}: {
  resource: ManagedResource
  favorite: boolean
  onFavorite: (id: string) => void
  action: string | null
  onAction: (resource: ManagedResource, action: 'pull' | 'approve') => Promise<void>
  onOpenSettings: (resource: ManagedResource) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const reactId = useId()
  const id = resourceId(resource)
  const panelId = `enterprise-resource-${reactId.replaceAll(':', '')}`
  const state = resourceState(resource)
  const currentVersion = resource.applied_version ?? resource.version ?? 'Not applied'
  const desiredVersion = resource.version ?? '—'
  const waitingForTrust = resource.kind === 'plugin' && state === 'trust_pending'
  const canPull = Boolean(resource.resource_id) && resourceHasUpdate(resource) && !waitingForTrust
  const hasUpdate = resourceHasUpdate(resource)
  const description =
    'description' in resource && resource.description
      ? resource.description
      : `Managed ${resource.kind} supplied by the connected project.`
  const settingsLabel =
    resource.kind === 'agent'
      ? 'Open Agent settings'
      : resource.kind === 'skill'
        ? 'Open Skill settings'
        : 'Open Plugin settings'

  return (
    <article className="transition-colors hover:bg-(--bg-key)/25">
      <div className="flex min-w-0 items-center gap-1 px-3 py-2 sm:px-4">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-3 rounded-lg px-1 py-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => setExpanded((value) => !value)}
        >
          <ResourceIcon kind={resource.kind} compact />
          <span className="min-w-0 flex-1">
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-semibold text-(--color-text)">
                {resource.slug}
              </span>
              {hasUpdate ? (
                <EnterpriseAttentionDot
                  label={`${resource.slug} has an update or notification`}
                />
              ) : null}
              <span className="hidden sm:inline-flex">
                <StateBadge state={state} />
              </span>
            </span>
            <span className="mt-0.5 block truncate text-xs text-(--color-text-muted)">
              {description}
            </span>
          </span>
          <span className="hidden shrink-0 items-center gap-2 text-xs sm:flex">
            <span className="font-mono text-(--color-text-subtle)">{currentVersion}</span>
            <ChevronDown
              aria-hidden="true"
              className={`size-4 text-(--color-text-subtle) transition-transform ${expanded ? 'rotate-180' : ''}`}
            />
          </span>
          <ChevronDown
            aria-hidden="true"
            className={`size-4 shrink-0 text-(--color-text-subtle) transition-transform sm:hidden ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={() => onFavorite(id)}
          aria-label={
            favorite
              ? `Remove ${resource.slug} from favorites`
              : `Add ${resource.slug} to favorites`
          }
        >
          <Star
            className={favorite ? 'fill-(--color-warning) text-(--color-warning)' : ''}
          />
        </Button>
      </div>

      {expanded ? (
        <div
          id={panelId}
          className="border-t border-(--color-border-subtle) bg-(--bg-key)/20 px-4 py-4 sm:pl-16"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 sm:hidden">
                <StateBadge state={state} />
              </div>
              <p className="mt-2 max-w-3xl text-xs leading-5 text-(--color-text-muted) sm:mt-0">
                {description}
              </p>
              <dl className="mt-3 grid gap-x-8 gap-y-2 text-xs sm:grid-cols-3">
                <div>
                  <dt className="text-(--color-text-subtle)">Applied version</dt>
                  <dd className="mt-0.5 font-mono text-(--color-text-2)">
                    {currentVersion}
                  </dd>
                </div>
                <div>
                  <dt className="text-(--color-text-subtle)">Project version</dt>
                  <dd className="mt-0.5 font-mono text-(--color-text-2)">
                    {desiredVersion}
                  </dd>
                </div>
                <div>
                  <dt className="text-(--color-text-subtle)">Release channel</dt>
                  <dd className="mt-0.5 capitalize text-(--color-text-2)">
                    {resource.release_channel ?? 'Not reported'}
                  </dd>
                </div>
              </dl>
              {resource.message ? (
                <p className="mt-3 rounded-lg border border-(--color-warning)/25 bg-(--color-warning-subtle) px-3 py-2 text-xs text-(--color-text-2)">
                  {resource.message}
                </p>
              ) : null}
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => onOpenSettings(resource)}>
                <Settings2 />
                {settingsLabel}
              </Button>
              {canPull || waitingForTrust ? (
                <Button
                  size="sm"
                  variant={waitingForTrust ? 'default' : 'outline'}
                  disabled={action !== null}
                  onClick={() =>
                    void onAction(resource, waitingForTrust ? 'approve' : 'pull')
                  }
                >
                  {action ===
                  `${waitingForTrust ? 'approve' : 'pull'}:${resource.resource_id}` ? (
                    <RefreshCw className="animate-spin motion-reduce:animate-none" />
                  ) : waitingForTrust ? (
                    <ShieldCheck />
                  ) : (
                    <Download />
                  )}
                  {waitingForTrust ? 'Review & approve' : 'Apply update'}
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </article>
  )
}

function CompactResourceRow({ resource, favorite, onFavorite, onOpenSettings }: {
  resource: ManagedResource
  favorite: boolean
  onFavorite: (id: string) => void
  onOpenSettings: (resource: ManagedResource) => void
}) {
  return (
    <div className="flex min-w-0 items-center gap-1 bg-(--bg-card) px-2 py-1.5">
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-3 rounded-lg px-1 py-1.5 text-left transition-colors hover:bg-(--bg-key)/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)"
        onClick={() => onOpenSettings(resource)}
      >
        <ResourceIcon kind={resource.kind} compact />
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate text-xs font-medium text-(--color-text)">
              {resource.slug}
            </span>
            {resourceHasUpdate(resource) ? (
              <EnterpriseAttentionDot
                label={`${resource.slug} has an update or notification`}
              />
            ) : null}
          </span>
          <span className="mt-0.5 block truncate font-mono text-[10px] text-(--color-text-subtle)">
            {resource.applied_version ?? resource.version ?? 'Not applied'}
          </span>
        </span>
        <StateBadge state={resourceState(resource)} />
        <ChevronRight className="size-3.5 shrink-0 text-(--color-text-subtle)" />
      </button>
      <Button variant="ghost" size="icon-xs" onClick={() => onFavorite(resourceId(resource))} aria-label={favorite ? `Remove ${resource.slug} from favorites` : `Add ${resource.slug} to favorites`}>
        <Star className={favorite ? 'fill-(--color-warning) text-(--color-warning)' : ''} />
      </Button>
    </div>
  )
}

function ResourceKindSummary({ kind, resources }: { kind: 'agent' | 'skill' | 'plugin'; resources: ManagedResource[] }) {
  const rows = resources.filter((resource) => resource.kind === kind)
  const Icon = kind === 'agent' ? Bot : kind === 'skill' ? Sparkles : PlugZap
  return (
    <div className="bg-(--bg-card) px-4 py-4">
      <div className="flex items-center gap-2 text-(--color-text-muted)"><Icon className="size-4" /><span className="text-xs font-medium capitalize">{kind}s</span></div>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-(--color-text)">{rows.length}</p>
      <p className="mt-0.5 text-[11px] text-(--color-text-subtle)">{rows.filter(resourceHasUpdate).length} awaiting review</p>
    </div>
  )
}

function SyncStrip({ status, onNavigate }: { status: ConductorStatus; onNavigate: () => void }) {
  const lanes = status.sync
  const rows = [lanes?.heartbeat, lanes?.resources, lanes?.inventory, lanes?.telemetry].filter(Boolean) as ConductorSyncLaneStatus[]
  const healthy = rows.filter((lane) => lane.state === 'healthy').length
  return (
    <button type="button" onClick={onNavigate} className="flex w-full flex-wrap items-center gap-3 rounded-xl border border-(--color-border) bg-(--bg-card) px-4 py-3 text-left transition-colors hover:border-(--color-border-strong)">
      <span className="flex size-9 items-center justify-center rounded-lg bg-(--color-success-subtle) text-(--color-success)"><CloudUpload className="size-4" /></span>
      <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-(--color-text)">Independent sync lanes</span><span className="mt-0.5 block text-xs text-(--color-text-muted)">{healthy}/{rows.length || 4} healthy · heartbeat, resources, inventory, usage</span></span>
      <ChevronRight className="size-4 text-(--color-text-subtle)" />
    </button>
  )
}

function LaneCard({ label, lane, Icon }: { label: string; lane: ConductorSyncLaneStatus; Icon: LucideIcon }) {
  return (
    <article className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
      <div className="flex items-center justify-between gap-3"><span className="flex size-8 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted)"><Icon className="size-4" /></span><StateBadge state={lane.state} /></div>
      <h2 className="mt-3 text-sm font-semibold text-(--color-text)">{label}</h2>
      <p className="mt-1 text-xs text-(--color-text-muted)">{lane.error ?? (lane.last_success_at ? `Last success ${formatTimestamp(lane.last_success_at)}` : 'Waiting for first successful run')}</p>
    </article>
  )
}

function Metric({ icon: Icon, label, value, hint, tone }: { icon: LucideIcon; label: string; value: string | null; hint: string; tone?: 'warning' | 'success' }) {
  return (
    <article className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
      <div className="flex items-center gap-2 text-(--color-text-muted)"><Icon className={`size-4 ${tone === 'warning' ? 'text-(--color-warning)' : tone === 'success' ? 'text-(--color-success)' : ''}`} /><span className="text-xs font-medium">{label}</span></div>
      {value === null ? <Skeleton className="mt-3 h-7 w-24" /> : <p className="mt-2 text-2xl font-semibold tabular-nums text-(--color-text)">{value}</p>}
      <p className="mt-1 truncate text-[11px] text-(--color-text-subtle)">{hint}</p>
    </article>
  )
}

function ResourceIcon({ kind, compact = false }: { kind: string; compact?: boolean }) {
  const Icon = kind === 'agent' ? Bot : kind === 'skill' ? Sparkles : PlugZap
  return <span className={`flex shrink-0 items-center justify-center rounded-lg bg-(--color-accent-soft) text-(--color-accent) ${compact ? 'size-8' : 'size-10'}`}><Icon className={compact ? 'size-3.5' : 'size-4'} /></span>
}

function StateBadge({ state }: { state: string }) {
  const healthy = ['healthy', 'applied', 'in_sync', 'connected'].includes(state)
  const warning = ['syncing', 'pending', 'staged', 'trust_pending', 'update_pending'].includes(state)
  return <span className={`inline-flex max-w-32 items-center rounded-full px-2 py-0.5 font-mono text-[10px] ${healthy ? 'bg-(--color-success-subtle) text-(--color-success)' : warning ? 'bg-(--color-warning-subtle) text-(--color-warning)' : state === 'idle' || state === 'paused' ? 'bg-(--bg-key) text-(--color-text-muted)' : 'bg-(--color-error-subtle) text-(--color-error)'}`}>{state.replaceAll('_', ' ')}</span>
}

function NoticeIcon({ tone }: { tone: EnterpriseNotice['tone'] }) {
  if (tone === 'danger') return <AlertTriangle className="mt-0.5 size-4 shrink-0 text-(--color-error)" />
  if (tone === 'warning') return <BellRing className="mt-0.5 size-4 shrink-0 text-(--color-warning)" />
  if (tone === 'success') return <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-(--color-success)" />
  return <CloudUpload className="mt-0.5 size-4 shrink-0 text-(--color-accent)" />
}

function SectionTitle({ title, description, action, onAction }: { title: string; description: string; action?: string; onAction?: () => void }) {
  return <div className="flex items-start justify-between gap-3 px-4 py-3"><div><h2 className="text-sm font-semibold text-(--color-text)">{title}</h2><p className="mt-0.5 text-xs text-(--color-text-muted)">{description}</p></div>{action && onAction ? <Button variant="ghost" size="sm" onClick={onAction}>{action}<ChevronRight /></Button> : null}</div>
}

function PageIntro({ title, description }: { title: string; description: string }) {
  return <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-(--color-text-muted)">Enterprise</p><h2 className="mt-1 text-xl font-semibold text-(--color-text)">{title}</h2><p className="mt-1 max-w-3xl text-sm leading-6 text-(--color-text-muted)">{description}</p></div>
}

function QueueStat({ label, value }: { label: string; value: string }) { return <div><dt className="text-[11px] text-(--color-text-subtle)">{label}</dt><dd className="mt-1 text-sm font-medium text-(--color-text)">{value}</dd></div> }
function IdentityRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) { return <div className="flex items-center justify-between gap-3 border-b border-(--color-border-subtle) pb-2"><dt className="text-(--color-text-muted)">{label}</dt><dd className={`truncate text-right text-(--color-text) ${mono ? 'font-mono' : ''}`}>{value}</dd></div> }

function EmptyMessage({ children, className = '' }: { children: ReactNode; className?: string }) { return <div className={`rounded-xl border border-dashed border-(--color-border) bg-(--bg-key)/25 px-5 py-10 text-center text-sm text-(--color-text-muted) ${className}`}>{children}</div> }

function ErrorPanel({ onRetry }: { onRetry: () => void }) { return <div role="alert" className="mx-auto max-w-xl rounded-xl border border-(--color-error)/30 bg-(--color-error-subtle) p-6 text-center"><CloudOff className="mx-auto size-6 text-(--color-error)" /><h2 className="mt-3 text-base font-semibold text-(--color-text)">Could not load Enterprise status</h2><p className="mt-1 text-sm text-(--color-text-muted)">EvoFlux remains usable. Retry the local status request when the backend is ready.</p><Button className="mt-4" variant="outline" onClick={onRetry}><RefreshCw />Retry</Button></div> }

function DisconnectedPanel() {
  return <div className="mx-auto max-w-2xl rounded-2xl border border-(--color-border) bg-(--bg-card) p-8 text-center"><span className="mx-auto flex size-12 items-center justify-center rounded-xl bg-(--color-accent-soft) text-(--color-accent)"><PlugZap className="size-5" /></span><h2 className="mt-4 text-xl font-semibold text-(--color-text)">Connect your Enterprise workspace</h2><p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-(--color-text-muted)">Connect EvoFlux to an Evo Conductor project to receive governed Agents, Skills, Plugins, version updates, and privacy-safe usage reporting.</p><Button className="mt-5" onClick={() => useUIStore.getState().openSettings('connection')}>Open connection settings</Button></div>
}

function EnterpriseSkeleton({ compact = false }: { compact?: boolean }) {
  return <div aria-label="Loading Enterprise workspace" className="space-y-4" role="status"><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 4 }, (_, index) => <div key={index} className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4"><Skeleton className="h-3 w-24" /><Skeleton className="mt-4 h-7 w-20" /><Skeleton className="mt-2 h-2.5 w-32" /></div>)}</div>{!compact ? <div className="grid gap-4 lg:grid-cols-2">{Array.from({ length: 2 }, (_, index) => <Skeleton key={index} className="h-64 rounded-xl" />)}</div> : <Skeleton className="h-72 rounded-xl" />}</div>
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Not yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown'
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default EnterpriseSettingsPage
