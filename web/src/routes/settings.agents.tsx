import { Crown, Plus, Wrench } from 'lucide-react'
import { useState } from 'react'

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
import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { ModelCombobox } from '@/components/settings/AgentForm'
import { useAgentFilesQuery, useRegistryQuery, useBulkUpdateAgentModelMutation } from '@/queries'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { useToastStore } from '@/stores/useToastStore'
import { useSettingsParams, useSettingsNavigate } from '@/contexts/SettingsContext'

type Tab = 'all' | 'forge' | 'coding' | 'aim'

export function AgentsListPage() {
  const { data, isLoading, isError } = useAgentFilesQuery()
  const registry = useRegistryQuery()
  const bulkModelMut = useBulkUpdateAgentModelMutation()
  const push = useToastStore((s) => s.push)
  const { name: selectedName } = useSettingsParams() as { name?: string }
  const navigate = useSettingsNavigate()
  const [modeDialogOpen, setModeDialogOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('all')

  const agents = data?.agents ?? []
  const aimAgents = agents.filter((a) => a.name.startsWith('aim/'))
  const codingAgents = agents.filter((a) => a.name.startsWith('coding/'))
  const forgeAgents = agents.filter(
    (a) => !a.name.startsWith('coding/') && !a.name.startsWith('aim/'),
  )

  // Bulk model selection — defaults to "every agent" on first load; after
  // that the user's checkbox choices are authoritative (a later refetch
  // won't silently re-check something they unchecked).
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [bulkModel, setBulkModel] = useState('')
  // Seed `checked` once from the first successful load — adjust state
  // during render (same "adopt external value" pattern as ModelCombobox's
  // lastValue latch below) rather than an effect, so there's no extra
  // render pass where the list flashes as fully unchecked first.
  const [seeded, setSeeded] = useState(false)
  if (!seeded && data) {
    setSeeded(true)
    setChecked(new Set(data.agents.map((a) => a.name)))
  }

  const toggleChecked = (name: string) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }
  const allChecked = agents.length > 0 && agents.every((a) => checked.has(a.name))
  const toggleAllChecked = () => {
    setChecked(allChecked ? new Set() : new Set(agents.map((a) => a.name)))
  }

  const handleApplyBulkModel = async () => {
    const names = agents.map((a) => a.name).filter((name) => checked.has(name))
    if (!names.length || !bulkModel) return
    const res = await bulkModelMut.mutateAsync({ names, model: bulkModel })
    const failed = res.results.filter((r) => !r.ok)
    if (failed.length === 0) {
      push({
        tone: 'success',
        title: `Model updated for ${names.length} agent${names.length === 1 ? '' : 's'}`,
      })
    } else {
      push({
        tone: 'error',
        title: `${failed.length} of ${names.length} failed`,
        description: failed.map((f) => `${f.name}: ${f.error}`).join('; '),
      })
    }
  }

  const rows: ListViewRow[] = (() => {
    const byLeadFirst = (a: (typeof agents)[number], b: (typeof agents)[number]) => {
      if (a.role === b.role) return a.name.localeCompare(b.name)
      return a.role === 'lead' ? -1 : 1
    }

    const mapAgent = (a: (typeof agents)[number]): ListViewRow => {
      const isLead = a.role === 'lead'
      return {
        key: a.name,
        to: '/settings/agents/$name',
        params: { name: a.name },
        active: selectedName === a.name,
        title: a.name.replace(/^(?:coding|aim)\//, ''),
        badge: isLead ? 'lead' : undefined,
        description: a.description || a.model || 'No description',
        meta: a.description && a.model ? a.model : undefined,
        invalidReason: !a.valid ? (a.error ?? 'Invalid configuration') : undefined,
        selected: checked.has(a.name),
        onToggleSelect: () => toggleChecked(a.name),
        trailing: (
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)"
            aria-hidden="true"
          >
            {isLead ? <Crown size={13} /> : <Wrench size={13} />}
          </span>
        ),
      }
    }

    if (tab === 'forge') {
      return forgeAgents.sort(byLeadFirst).map(mapAgent)
    }
    if (tab === 'coding') {
      return codingAgents.sort(byLeadFirst).map(mapAgent)
    }
    if (tab === 'aim') {
      return aimAgents.sort(byLeadFirst).map(mapAgent)
    }

    const forge = forgeAgents.sort(byLeadFirst)
    const coding = codingAgents.sort(byLeadFirst)
    const aim = aimAgents.sort(byLeadFirst)
    return [
      ...(forge.length > 0
        ? [{ key: 'group-forge', kind: 'group' as const, title: 'Forge' }, ...forge.map(mapAgent)]
        : []),
      ...(coding.length > 0
        ? [{ key: 'group-coding', kind: 'group' as const, title: 'Coding' }, ...coding.map(mapAgent)]
        : []),
      ...(aim.length > 0
        ? [{ key: 'group-aim', kind: 'group' as const, title: 'AIM' }, ...aim.map(mapAgent)]
        : []),
    ]
  })()

  return (
    <>
    <SettingsListView
      title="Agents"
      icon={Wrench}
      description="Each agent is a markdown file with YAML frontmatter. Forge, Coding and AIM are separate teams with their own roster."
      newTo="/settings/agents/new"
      newLabel="New agent"
      newAction={
        <Button size="sm" onClick={() => setModeDialogOpen(true)}>
          <Plus size={13} aria-hidden="true" />
          New agent
        </Button>
      }
      filterPlaceholder="Filter agents…"
      tabs={
        <SegmentedControl
          options={[
            { value: 'all', label: 'All' },
            { value: 'forge', label: `Forge (${forgeAgents.length})` },
            { value: 'coding', label: `Coding (${codingAgents.length})` },
            { value: 'aim', label: `AIM (${aimAgents.length})` },
          ]}
          value={tab}
          onChange={setTab}
          layoutId="agents-tab"
          ariaLabel="Agent teams"
        />
      }
      headerExtra={
        agents.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) px-3 py-2">
            <label className="flex items-center gap-2 text-xs font-medium text-(--color-text)">
              <Checkbox checked={allChecked} onCheckedChange={toggleAllChecked} aria-label="Select all agents" />
              {checked.size} / {agents.length} selected
            </label>
            <div className="min-w-48 flex-1">
              <ModelCombobox
                value={bulkModel}
                onChange={setBulkModel}
                options={registry.data?.models ?? []}
                placeholder="Set model for selected…"
              />
            </div>
            <Button
              size="sm"
              disabled={checked.size === 0 || !bulkModel || bulkModelMut.isPending}
              onClick={handleApplyBulkModel}
            >
              Apply to {checked.size || ''} agent{checked.size === 1 ? '' : 's'}
            </Button>
          </div>
        ) : undefined
      }
      rows={rows}
      isLoading={isLoading}
      isError={isError}
      emptyTitle="No agents yet"
      emptyBody="Define a team member with a model, tools, and a system prompt."
    />
    <Dialog open={modeDialogOpen} onOpenChange={setModeDialogOpen}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Create agent</DialogTitle>
          <DialogDescription>Choose which team directory receives the new agent file.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-2 sm:grid-cols-3">
          <Button onClick={() => { setModeDialogOpen(false); navigate('agents/new', { search: { mode: 'forge' } }) }}>
            Forge
          </Button>
          <Button onClick={() => { setModeDialogOpen(false); navigate('agents/new', { search: { mode: 'coding' } }) }}>
            Coding
          </Button>
          <Button onClick={() => { setModeDialogOpen(false); navigate('agents/new', { search: { mode: 'aim' } }) }}>
            AIM
          </Button>
        </div>
        <DialogFooter className="p-3">
          <Button type="button" variant="outline" onClick={() => setModeDialogOpen(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  )
}
