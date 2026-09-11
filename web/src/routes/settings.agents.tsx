import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Layers3,
  Plus,
  Search,
  Sparkles,
  Users,
  Wrench,
  X,
} from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'

import type { AgentSummary } from '@/api/types'
import {
  AgentGlyph,
  AgentModelBadge,
  AgentRoleBadge,
  AgentTeamBadge,
} from '@/components/settings/AgentVisuals'
import {
  AGENT_TEAM_VISUALS,
  agentDisplayName,
  agentTeamFromName,
  type AgentTeam,
} from '@/lib/agent-visuals'
import { ModelCombobox } from '@/components/settings/AgentForm'
import { isModelConfigured } from '@/lib/model-settings'
import { ManagedResourceProviderBadge } from '@/components/settings/ManagedResourceProviderBadge'
import { SettingsPage } from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { cn } from '@/lib/utils'
import {
  useAgentFilesQuery,
  useBulkUpdateAgentModelMutation,
  useRegistryQuery,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'

type Tab = 'all' | AgentTeam

const TEAM_ORDER: AgentTeam[] = ['work', 'coding']

export function AgentsListPage() {
  const { data, isLoading, isFetching, isError, error, refetch } = useAgentFilesQuery()
  const registry = useRegistryQuery()
  const bulkModelMut = useBulkUpdateAgentModelMutation()
  const push = useToastStore((state) => state.push)
  const navigate = useSettingsNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('all')
  const [query, setQuery] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [bulkModel, setBulkModel] = useState('')

  const agents = useMemo(() => data?.agents ?? [], [data?.agents])
  const teams = useMemo(
    () =>
      Object.fromEntries(
        TEAM_ORDER.map((team) => [
          team,
          agents
            .filter((agent) => agentTeamFromName(agent.name) === team)
            .sort(sortAgents),
        ]),
      ) as Record<AgentTeam, AgentSummary[]>,
    [agents],
  )

  const normalizedQuery = query.trim().toLowerCase()
  const visibleAgents = useMemo(() => {
    const inTab = tab === 'all' ? agents : teams[tab]
    if (!normalizedQuery) return [...inTab].sort(sortAgents)
    return inTab
      .filter((agent) =>
        [agent.name, agent.description, agent.model]
          .filter(Boolean)
          .some((value) => value?.toLowerCase().includes(normalizedQuery)),
      )
      .sort(sortAgents)
  }, [agents, normalizedQuery, tab, teams])

  const groupedVisible = TEAM_ORDER.map((team) => ({
    team,
    agents: visibleAgents.filter((agent) => agentTeamFromName(agent.name) === team),
  })).filter((group) => group.agents.length > 0)

  const selectedAgents = agents.filter((agent) => agent.editable && checked.has(agent.name))
  const selectableVisibleAgents = visibleAgents.filter((agent) => agent.editable)
  const allVisibleChecked =
    selectableVisibleAgents.length > 0 &&
    selectableVisibleAgents.every((agent) => checked.has(agent.name))
  const someVisibleChecked = selectableVisibleAgents.some((agent) => checked.has(agent.name))

  const toggleChecked = (name: string) => {
    setChecked((previous) => {
      const next = new Set(previous)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const toggleVisible = () => {
    setChecked((previous) => {
      const next = new Set(previous)
      if (allVisibleChecked) {
        for (const agent of selectableVisibleAgents) next.delete(agent.name)
      } else {
        for (const agent of selectableVisibleAgents) next.add(agent.name)
      }
      return next
    })
  }

  const toggleTeam = (team: AgentTeam) => {
    const teamAgents = teams[team].filter((agent) => agent.editable)
    if (teamAgents.length === 0) return
    const teamChecked = teamAgents.every((agent) => checked.has(agent.name))
    setChecked((previous) => {
      const next = new Set(previous)
      for (const agent of teamAgents) {
        if (teamChecked) next.delete(agent.name)
        else next.add(agent.name)
      }
      return next
    })
  }

  const toggleAgents = (names: string[]) => {
    const editable = agents.filter((agent) => agent.editable && names.includes(agent.name))
    if (editable.length === 0) return
    const allChecked = editable.every((agent) => checked.has(agent.name))
    setChecked((previous) => {
      const next = new Set(previous)
      for (const agent of editable) {
        if (allChecked) next.delete(agent.name)
        else next.add(agent.name)
      }
      return next
    })
  }

  const handleApplyBulkModel = async () => {
    const names = selectedAgents.map((agent) => agent.name)
    if (!names.length || !bulkModel) return
    const response = await bulkModelMut.mutateAsync({ names, model: bulkModel })
    const failed = response.results.filter((result) => !result.ok)
    if (failed.length === 0) {
      push({
        tone: 'success',
        title: `Model updated for ${names.length} agent${names.length === 1 ? '' : 's'}`,
      })
      setChecked(new Set())
      setBulkModel('')
      return
    }
    push({
      tone: 'error',
      title: `${failed.length} of ${names.length} failed`,
      description: failed.map((item) => `${item.name}: ${item.error}`).join('; '),
    })
  }

  return (
    <>
      <SettingsPage
        icon={Users}
        title="Agent teams"
        lede="Build the roster behind each workspace. Every agent has one job, one model, and a focused set of capabilities."
        size="wide"
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus size={13} aria-hidden="true" />
            New agent
          </Button>
        }
      >
        <SettingsAsyncBoundary
          loading={isLoading || isFetching}
          hasData={!isLoading && !isError}
          error={isError ? error : undefined}
          variant="list"
          loadingLabel="Loading agents"
          errorTitle="Failed to load agents"
          onRetry={() => void refetch()}
        >
          <div className="space-y-5">
            <AgentRosterSummary agents={agents} teams={teams} />

            <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card) shadow-[0_16px_44px_rgba(0,0,0,0.035)]">
            <div className="flex flex-col gap-3 border-b border-(--color-border-subtle) p-3 sm:p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <SegmentedControl
                  options={[
                    { value: 'all', label: `All ${agents.length}` },
                    { value: 'work', label: `Work ${teams.work.length}` },
                    { value: 'coding', label: `Coding ${teams.coding.length}` },
                  ]}
                  value={tab}
                  onChange={setTab}
                  layoutId="agents-team-tab"
                  ariaLabel="Agent teams"
                  className="max-w-full overflow-x-auto"
                />

                <div className="relative min-w-0 flex-1 lg:max-w-sm">
                  <Search
                    size={14}
                    aria-hidden="true"
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-subtle)"
                  />
                  <Input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search name, role, or model…"
                    aria-label="Search agents"
                    className="h-9 pl-9 pr-9"
                  />
                  {query && (
                    <button
                      type="button"
                      onClick={() => setQuery('')}
                      aria-label="Clear agent search"
                      className="absolute right-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    >
                      <X size={12} aria-hidden="true" />
                    </button>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-between gap-3 text-xs text-(--color-text-muted)">
                <label className="flex min-h-8 cursor-pointer items-center gap-2 rounded-lg px-1.5 transition-colors hover:bg-(--bg-key)/55">
                  <Checkbox
                    checked={allVisibleChecked}
                    indeterminate={!allVisibleChecked && someVisibleChecked}
                    onCheckedChange={toggleVisible}
                    disabled={selectableVisibleAgents.length === 0}
                    aria-label="Select visible agents"
                  />
                  <span>
                    {someVisibleChecked
                      ? `${selectedAgents.length} selected`
                      : `Select ${selectableVisibleAgents.length} editable agent${selectableVisibleAgents.length === 1 ? '' : 's'}`}
                  </span>
                </label>
                <span className="font-mono text-[11px] tabular-nums">
                  {visibleAgents.length} shown
                </span>
              </div>
            </div>

            {selectedAgents.length > 0 && (
              <div className="flex flex-col gap-2 border-b border-(--color-accent)/20 bg-(--color-accent-soft) px-3 py-3 sm:flex-row sm:items-center sm:px-4">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-(--bg-card) text-(--color-accent) ring-1 ring-(--color-accent)/20">
                    <Layers3 size={14} aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-(--color-text)">
                      Update {selectedAgents.length} agent{selectedAgents.length === 1 ? '' : 's'}
                    </p>
                    <p className="truncate text-[11px] text-(--color-text-muted)">
                      Choose one model to apply to the selection.
                    </p>
                  </div>
                </div>
                <div className="min-w-0 flex-1 sm:max-w-sm">
                  <ModelCombobox
                    value={bulkModel}
                    onChange={setBulkModel}
                    options={registry.data?.models ?? []}
                    placeholder="Choose model…"
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setChecked(new Set())}
                  >
                    Clear
                  </Button>
                  <Button
                    size="sm"
                    disabled={!bulkModel || bulkModelMut.isPending}
                    onClick={handleApplyBulkModel}
                  >
                    {bulkModelMut.isPending ? 'Applying…' : 'Apply model'}
                  </Button>
                </div>
              </div>
            )}

            {agents.length === 0 ? (
              <AgentEmptyState onCreate={() => setCreateOpen(true)} />
            ) : groupedVisible.length === 0 ? (
              <div className="px-5 py-16 text-center">
                <p className="text-sm font-medium text-(--color-text)">No matching agents</p>
                <p className="mt-1 text-xs text-(--color-text-muted)">
                  Try another team or a shorter search.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-(--color-border-subtle)">
                {groupedVisible.map((group) => (
                  <AgentTeamGroup
                    key={group.team}
                    team={group.team}
                    agents={teams[group.team]}
                    visibleAgents={group.agents}
                    filtering={Boolean(normalizedQuery)}
                    checked={checked}
                    onToggleAgent={toggleChecked}
                    onToggleTeam={() => toggleTeam(group.team)}
                    onToggleAgents={toggleAgents}
                    onOpen={(name) =>
                      navigate('/settings/agents/$name', { params: { name } })
                    }
                  />
                ))}
              </div>
            )}
            </section>
          </div>
        </SettingsAsyncBoundary>
      </SettingsPage>

      <CreateAgentDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        teams={teams}
        onChoose={(team) => {
          setCreateOpen(false)
          navigate('agents/new', { search: { mode: team } })
        }}
      />
    </>
  )
}

function AgentRosterSummary({
  agents,
  teams,
}: {
  agents: AgentSummary[]
  teams: Record<AgentTeam, AgentSummary[]>
}) {
  const leads = agents.filter((agent) => agent.role === 'lead').length
  const configured = agents.filter((agent) => isModelConfigured(agent.model) && agent.valid).length
  return (
    <section className="grid grid-cols-3 overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)">
      <RosterStat value={agents.length} label="Agents" icon={Users} />
      <RosterStat value={leads} label="Team leads" icon={Sparkles} />
      <RosterStat
        value={`${configured}/${agents.length || 0}`}
        label="Ready"
        icon={Wrench}
        className="border-r-0"
      />
      <div className="col-span-3 flex flex-wrap gap-x-5 gap-y-2 border-t border-(--color-border-subtle) bg-(--bg-key)/25 px-4 py-2.5">
        {TEAM_ORDER.map((team) => {
          const visual = AGENT_TEAM_VISUALS[team]
          return (
            <span key={team} className="flex items-center gap-1.5 text-[11px] text-(--color-text-muted)">
              <span className={cn('size-1.5 rounded-full', visual.soft, visual.accent)} />
              {visual.label}
              <strong className="font-mono font-medium text-(--color-text)">{teams[team].length}</strong>
            </span>
          )
        })}
      </div>
    </section>
  )
}

function RosterStat({
  value,
  label,
  icon: Icon,
  className,
}: {
  value: number | string
  label: string
  icon: typeof Users
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 items-center gap-3 border-r border-(--color-border-subtle) px-3 py-4 sm:px-5', className)}>
      <span className="hidden size-9 shrink-0 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted) sm:flex">
        <Icon size={15} aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="font-heading text-xl font-semibold tracking-[-0.03em] text-(--color-text)">{value}</p>
        <p className="truncate text-[10px] font-medium tracking-wide text-(--color-text-subtle) uppercase sm:text-[11px]">{label}</p>
      </div>
    </div>
  )
}

function AgentTeamGroup({
  team,
  agents,
  visibleAgents,
  filtering,
  checked,
  onToggleAgent,
  onToggleTeam,
  onToggleAgents,
  onOpen,
}: {
  team: AgentTeam
  agents: AgentSummary[]
  visibleAgents: AgentSummary[]
  filtering: boolean
  checked: Set<string>
  onToggleAgent: (name: string) => void
  onToggleTeam: () => void
  onToggleAgents: (names: string[]) => void
  onOpen: (name: string) => void
}) {
  const visual = AGENT_TEAM_VISUALS[team]
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const editableAgents = agents.filter((agent) => agent.editable)
  const allChecked =
    editableAgents.length > 0 && editableAgents.every((agent) => checked.has(agent.name))
  const someChecked = editableAgents.some((agent) => checked.has(agent.name))
  const visibleNames = new Set(visibleAgents.map((agent) => agent.name))
  const leads = agents.filter((agent) => agent.role === 'lead').sort(sortAgents)
  const leadNames = new Set(leads.map(agentConfigName))
  const defaultLead = leads.find((lead) => agentConfigName(lead) === 'evoflux') ?? leads[0]
  const defaultLeadName = defaultLead ? agentConfigName(defaultLead) : null
  const members = agents.filter((agent) => agent.role === 'member')
  const groups = leads.map((lead) => {
    const ownerName = agentConfigName(lead)
    const owned = members.filter((member) => (member.lead ?? defaultLeadName) === ownerName)
    const leadMatches = visibleNames.has(lead.name)
    const visibleMembers = filtering && !leadMatches
      ? owned.filter((member) => visibleNames.has(member.name))
      : owned
    return { lead, owned, visibleMembers, visible: leadMatches || visibleMembers.length > 0 }
  }).filter((group) => group.visible)
  const orphaned = members.filter((member) => {
    const owner = member.lead ?? defaultLeadName
    return owner === null || !leadNames.has(owner)
  }).filter((member) => !filtering || visibleNames.has(member.name))

  return (
    <section aria-labelledby={`agent-team-${team}`}>
      <div className="flex items-center gap-3 bg-(--bg-key)/25 px-3 py-2.5 sm:px-4">
        <Checkbox
          checked={allChecked}
          indeterminate={!allChecked && someChecked}
          onCheckedChange={onToggleTeam}
          disabled={editableAgents.length === 0}
          aria-label={`Select ${visual.label} agents`}
        />
        <AgentTeamBadge team={team} />
        <div className="min-w-0 flex-1">
          <h2 id={`agent-team-${team}`} className="sr-only">{visual.label}</h2>
          <p className="truncate text-[11px] text-(--color-text-muted)">{visual.description}</p>
        </div>
        <span className="font-mono text-[10px] tabular-nums text-(--color-text-subtle)">{agents.length}</span>
      </div>
      <div className="divide-y divide-(--color-border-subtle)">
        {groups.map(({ lead, owned, visibleMembers }) => {
          const ownerName = agentConfigName(lead)
          const isCollapsed = collapsed.has(lead.name)
          const groupNames = [lead.name, ...owned.map((member) => member.name)]
          const groupEditable = agents.filter((agent) => groupNames.includes(agent.name) && agent.editable)
          const groupChecked = groupEditable.length > 0 && groupEditable.every((agent) => checked.has(agent.name))
          const groupSomeChecked = groupEditable.some((agent) => checked.has(agent.name))
          return (
            <section key={lead.name} aria-label={`${ownerName} team`}>
              <AgentRow
                agent={lead}
                selected={lead.editable && checked.has(lead.name)}
                onToggle={() => onToggleAgent(lead.name)}
                onOpen={() => onOpen(lead.name)}
                ownership={lead.name === defaultLead?.name ? 'Default lead' : undefined}
                descriptionSuffix={`${owned.length} ${owned.length === 1 ? 'member' : 'members'}`}
                after={(
                  <button
                    type="button"
                    onClick={() => setCollapsed((previous) => {
                      const next = new Set(previous)
                      if (next.has(lead.name)) next.delete(lead.name)
                      else next.add(lead.name)
                      return next
                    })}
                    className="mr-2 flex size-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    aria-label={`${isCollapsed ? 'Expand' : 'Collapse'} ${ownerName} team`}
                    aria-expanded={!isCollapsed}
                  >
                    <ChevronDown size={14} className={cn('transition-transform', isCollapsed && '-rotate-90')} />
                  </button>
                )}
              />
              {!isCollapsed && (
                <div className="relative ml-7 border-l border-(--color-border-strong) bg-(--bg-key)/10 sm:ml-11">
                  <div className="flex min-h-9 items-center gap-2 border-b border-(--color-border-subtle) px-3 text-[10px] text-(--color-text-muted)">
                    <Checkbox
                      checked={groupChecked}
                      indeterminate={!groupChecked && groupSomeChecked}
                      onCheckedChange={() => onToggleAgents(groupNames)}
                      disabled={groupEditable.length === 0}
                      aria-label={`Select ${ownerName} team`}
                    />
                    <span className="font-medium">Members of {ownerName}</span>
                    <span className="ml-auto font-mono tabular-nums">{owned.length}</span>
                  </div>
                  {visibleMembers.length > 0 ? visibleMembers.map((member) => (
                    <AgentRow
                      key={member.name}
                      agent={member}
                      selected={member.editable && checked.has(member.name)}
                      onToggle={() => onToggleAgent(member.name)}
                      onOpen={() => onOpen(member.name)}
                      nested
                      ownership={`Member of ${ownerName}`}
                    />
                  )) : (
                    <p className="px-4 py-3 text-xs text-(--color-text-subtle)">No members assigned to this lead.</p>
                  )}
                </div>
              )}
            </section>
          )
        })}
        {orphaned.length > 0 && (
          <section aria-label="Unassigned members">
            <div className="bg-(--color-warning)/8 px-4 py-2 text-[11px] font-medium text-(--color-warning)">Unassigned members</div>
            {orphaned.map((member) => (
              <AgentRow
                key={member.name}
                agent={member}
                selected={member.editable && checked.has(member.name)}
                onToggle={() => onToggleAgent(member.name)}
                onOpen={() => onOpen(member.name)}
                ownership="Choose an owning lead"
              />
            ))}
          </section>
        )}
      </div>
    </section>
  )
}

function agentConfigName(agent: AgentSummary): string {
  return agent.name.split('/').at(-1) ?? agent.name
}

function AgentRow({
  agent,
  selected,
  onToggle,
  onOpen,
  nested = false,
  ownership,
  descriptionSuffix,
  after,
}: {
  agent: AgentSummary
  selected: boolean
  onToggle: () => void
  onOpen: () => void
  nested?: boolean
  ownership?: string
  descriptionSuffix?: string
  after?: ReactNode
}) {
  return (
    <div className={cn('group flex min-w-0 items-stretch transition-colors hover:bg-(--bg-key)/35', nested && 'not-last:border-b not-last:border-(--color-border-subtle)', selected && 'bg-(--color-accent-soft)/45')}>
      {agent.editable ? (
        <label className={cn('flex shrink-0 cursor-pointer items-center', nested ? 'min-h-14 pl-3' : 'min-h-16 pl-3 sm:pl-4')}>
          <Checkbox checked={selected} onCheckedChange={onToggle} aria-label={`Select ${agent.name}`} />
        </label>
      ) : (
        <span className="w-7 shrink-0 sm:w-8" aria-hidden="true" />
      )}
      <button
        type="button"
        onClick={onOpen}
        className={cn('flex min-w-0 flex-1 items-center gap-3 px-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-(--focus-ring)/35 sm:px-4', nested ? 'py-2.5' : 'py-3')}
      >
        <AgentGlyph name={agent.name} role={agent.role} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-semibold text-(--color-text)">{agentDisplayName(agent.name)}</span>
            <AgentRoleBadge role={agent.role} />
            {ownership && <span className="hidden truncate rounded-full bg-(--bg-key) px-2 py-0.5 text-[10px] text-(--color-text-muted) ring-1 ring-(--color-border) md:inline-flex">{ownership}</span>}
            {agent.provider && <ManagedResourceProviderBadge provider={agent.provider} />}
            {!agent.valid && (
              <span className="inline-flex items-center gap-1 text-[10px] text-(--color-error)" title={agent.error ?? 'Invalid configuration'}>
                <AlertCircle size={11} aria-hidden="true" /> Invalid
              </span>
            )}
            {agent.valid && agent.role === 'member' && !isModelConfigured(agent.model) && (
              <span
                className="inline-flex items-center gap-1 text-[10px] text-(--color-warning)"
                title="A member with no model is left off the team roster — the lead cannot spawn it."
              >
                <AlertCircle size={11} aria-hidden="true" /> Not on the roster
              </span>
            )}
          </div>
          <p className="mt-0.5 line-clamp-1 text-xs leading-relaxed text-(--color-text-muted)">
            {agent.description || 'No description yet.'}
            {descriptionSuffix ? ` · ${descriptionSuffix}` : ''}
          </p>
          <div className="mt-1.5 flex items-center gap-3 text-[10px] text-(--color-text-subtle) sm:hidden">
            <span>{agent.tools.length} tools</span>
            <span>{agent.skills.length} skills</span>
          </div>
        </div>
        <div className="hidden shrink-0 flex-col items-end gap-1.5 sm:flex">
          <AgentModelBadge model={agent.model} />
          <span className="text-[10px] text-(--color-text-subtle)">
            {agent.tools.length} tools · {agent.skills.length} skills
            {agent.mcp.length > 0 ? ` · ${agent.mcp.length} MCP` : ''}
          </span>
        </div>
        <ChevronRight size={15} className="shrink-0 text-(--color-text-subtle) transition-transform group-hover:translate-x-0.5 group-hover:text-(--color-text-muted)" aria-hidden="true" />
      </button>
      {after}
    </div>
  )
}

function AgentEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center px-5 py-16 text-center">
      <span className="flex size-14 items-center justify-center rounded-2xl bg-(--color-accent-soft) text-(--color-accent) ring-1 ring-(--color-accent)/20">
        <Users size={22} aria-hidden="true" />
      </span>
      <h2 className="mt-4 font-heading text-base font-semibold text-(--color-text)">Build your first team</h2>
      <p className="mt-1 max-w-sm text-xs leading-relaxed text-(--color-text-muted)">
        Create a focused agent, choose its model, then grant only the capabilities it needs.
      </p>
      <Button size="sm" className="mt-4" onClick={onCreate}>
        <Plus size={12} aria-hidden="true" /> New agent
      </Button>
    </div>
  )
}

function CreateAgentDialog({
  open,
  onOpenChange,
  teams,
  onChoose,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  teams: Record<AgentTeam, AgentSummary[]>
  onChoose: (team: AgentTeam) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" showCloseButton={false}>
        <DialogHeader className="p-1">
          <DialogTitle>Choose a team</DialogTitle>
          <DialogDescription>
            The team determines where the agent appears and which built-in capabilities it inherits.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2 py-1">
          {TEAM_ORDER.map((team) => {
            const visual = AGENT_TEAM_VISUALS[team]
            return (
              <button
                key={team}
                type="button"
                onClick={() => onChoose(team)}
                className="group flex items-center gap-3 rounded-xl border border-(--color-border) bg-(--bg-input) p-3 text-left outline-none transition-[border-color,background-color,transform] hover:border-(--color-border-strong) hover:bg-(--bg-key)/45 active:scale-[0.99] focus-visible:ring-3 focus-visible:ring-(--focus-ring)/35"
              >
                <AgentGlyph name={team === 'work' ? 'new' : `${team}/new`} role="member" size="lg" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-heading text-sm font-semibold text-(--color-text)">{visual.label}</span>
                    <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 font-mono text-[9px] text-(--color-text-subtle)">{teams[team].length} agents</span>
                  </div>
                  <p className="mt-0.5 text-xs text-(--color-text-muted)">{visual.description}</p>
                </div>
                <ChevronRight size={16} className="text-(--color-text-subtle) transition-transform group-hover:translate-x-0.5 group-hover:text-(--color-text)" aria-hidden="true" />
              </button>
            )
          })}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function sortAgents(a: AgentSummary, b: AgentSummary): number {
  if (a.role !== b.role) return a.role === 'lead' ? -1 : 1
  return agentDisplayName(a.name).localeCompare(agentDisplayName(b.name))
}
