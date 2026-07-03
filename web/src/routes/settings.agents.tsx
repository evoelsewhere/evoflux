import { Crown, Plus, Wrench } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { useAgentFilesQuery } from '@/queries'
import { useSettingsParams, useSettingsNavigate } from '@/contexts/SettingsContext'

type Tab = 'all' | 'normal' | 'coding'

export function AgentsListPage() {
  const { data, isLoading, isError } = useAgentFilesQuery()
  const { name: selected } = useSettingsParams() as { name?: string }
  const navigate = useSettingsNavigate()
  const [modeDialogOpen, setModeDialogOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('all')

  const agents = data?.agents ?? []
  const normalAgents = agents.filter((a) => !a.name.startsWith('coding/'))
  const codingAgents = agents.filter((a) => a.name.startsWith('coding/'))

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
        active: selected === a.name,
        title: a.name.replace(/^coding\//, ''),
        badge: isLead ? 'lead' : undefined,
        description: a.description || a.model || 'No description',
        invalidReason: !a.valid ? (a.error ?? 'Invalid configuration') : undefined,
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

    if (tab === 'normal') {
      return normalAgents.sort(byLeadFirst).map(mapAgent)
    }
    if (tab === 'coding') {
      return codingAgents.sort(byLeadFirst).map(mapAgent)
    }

    const normal = normalAgents.sort(byLeadFirst)
    const coding = codingAgents.sort(byLeadFirst)
    return [
      ...(normal.length > 0
        ? [{ key: 'group-normal', kind: 'group' as const, title: 'Normal' }, ...normal.map(mapAgent)]
        : []),
      ...(coding.length > 0
        ? [{ key: 'group-coding', kind: 'group' as const, title: 'Coding' }, ...coding.map(mapAgent)]
        : []),
    ]
  })()

  return (
    <>
    <SettingsListView
      title="Agents"
      description="Markdown files with YAML frontmatter. Normal and Coding agents are separate teams."
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
        <div className="flex gap-1 rounded-lg border border-(--color-border) bg-(--bg-key) p-0.5">
          {(['all', 'normal', 'coding'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                tab === t
                  ? 'bg-(--bg-card) text-(--color-text) shadow-sm'
                  : 'text-(--color-text-muted) hover:text-(--color-text)'
              }`}
            >
              {t === 'all' ? 'All' : t === 'normal' ? `Normal (${normalAgents.length})` : `Coding (${codingAgents.length})`}
            </button>
          ))}
        </div>
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
        <div className="grid gap-2 sm:grid-cols-2">
          <Button onClick={() => { setModeDialogOpen(false); navigate('agents/new', { search: { mode: 'normal' } }) }}>
            Normal
          </Button>
          <Button onClick={() => { setModeDialogOpen(false); navigate('agents/new', { search: { mode: 'coding' } }) }}>
            Coding
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
