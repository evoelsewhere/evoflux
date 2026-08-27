import { useMemo, useState } from 'react'
import { AlertTriangle, Clock3, GitBranch, Loader2 } from 'lucide-react'

import type { EasdRunTrace, EasdTraceNode, EasdTraceNodeKind } from '@/api/types'
import { Button } from '@/components/ui/button'
import { SelectControl } from '@/components/ui/select'
import { cn } from '@/lib/utils'

const KIND_LABELS: Record<EasdTraceNodeKind, string> = {
  run: 'Run',
  specification: 'Specification',
  plan: 'Plan',
  criterion: 'Criteria',
  mission_contract: 'Mission contracts',
  mission_attempt: 'Attempts',
  evidence: 'Evidence',
  deviation: 'Deviations',
  convergence: 'Done',
}

const KIND_ORDER: EasdTraceNodeKind[] = [
  'run',
  'specification',
  'criterion',
  'plan',
  'mission_contract',
  'mission_attempt',
  'evidence',
  'deviation',
  'convergence',
]

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'boolean' || typeof value === 'number') return String(value)
  return JSON.stringify(value)
}

function statusTone(status: string | null): string {
  if (status === 'passed' || status === 'accepted' || status === 'completed' || status === 'converged') {
    return 'text-(--color-success)'
  }
  if (status === 'failed' || status === 'blocked' || status === 'open') {
    return 'text-(--color-error)'
  }
  return 'text-(--color-accent)'
}

function NodeInspector({ node, trace }: { node: EasdTraceNode; trace: EasdRunTrace }) {
  const incoming = trace.edges.filter((edge) => edge.target === node.id)
  const outgoing = trace.edges.filter((edge) => edge.source === node.id)
  return (
    <aside aria-label="Trace entity inspector" className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
      <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">{KIND_LABELS[node.kind]}</p>
      <h3 className="mt-1 text-xs font-semibold text-(--color-text)">{node.label}</h3>
      {node.status && <p className={cn('mt-1 text-[10px] font-medium', statusTone(node.status))}>{node.status}</p>}
      <dl className="mt-3 space-y-2">
        {Object.entries(node.data).map(([key, value]) => (
          <div key={key}>
            <dt className="text-[9px] uppercase tracking-wide text-(--color-text-subtle)">{key.replaceAll('_', ' ')}</dt>
            <dd className="mt-0.5 break-all text-[10px] leading-4 text-(--color-text-2)">{displayValue(value)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 border-t border-(--color-border) pt-2 text-[9px] text-(--color-text-subtle)">
        {incoming.length} incoming · {outgoing.length} outgoing relations
      </p>
    </aside>
  )
}

export function EasdTraceWorkspace({
  trace,
  loading,
  error,
  onRetry,
}: {
  trace?: EasdRunTrace
  loading: boolean
  error: unknown
  onRetry: () => void
}) {
  const [criterionId, setCriterionId] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const criterionOptions = useMemo(() => {
    const values = new Map<string, string>()
    for (const node of trace?.nodes ?? []) {
      if (node.kind === 'criterion' && node.entity_id) values.set(node.entity_id, node.label)
    }
    return [...values].map(([value, label]) => ({ value, label }))
  }, [trace])
  const visibleNodeIds = useMemo(() => {
    if (!trace || !criterionId) return null
    const ids = new Set<string>()
    for (const node of trace.nodes) {
      if (node.kind === 'criterion' && node.entity_id === criterionId) ids.add(node.id)
    }
    for (const edge of trace.edges) {
      if (edge.criterion_ids.includes(criterionId)) {
        ids.add(edge.source)
        ids.add(edge.target)
      }
    }
    let expanded = true
    while (expanded) {
      expanded = false
      for (const edge of trace.edges) {
        if (!['contains', 'compiled_to', 'executes', 'produced'].includes(edge.kind)) continue
        if (edge.kind === 'contains' && ids.has(edge.target) && !ids.has(edge.source)) {
          ids.add(edge.source)
          expanded = true
        } else if (edge.kind !== 'contains' && (ids.has(edge.source) || ids.has(edge.target))) {
          const size = ids.size
          ids.add(edge.source)
          ids.add(edge.target)
          expanded = ids.size !== size
        }
      }
    }
    return ids
  }, [criterionId, trace])
  const visibleNodes = (trace?.nodes ?? []).filter((node) => !visibleNodeIds || visibleNodeIds.has(node.id))
  const visibleEdges = (trace?.edges ?? []).filter((edge) => (
    (!visibleNodeIds || (visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)))
  ))
  const selectedNode = trace?.nodes.find((node) => node.id === selectedNodeId && visibleNodes.some((visible) => visible.id === node.id))
    ?? visibleNodes.find((node) => node.kind === 'criterion' && node.entity_id === criterionId)
    ?? visibleNodes[0]
    ?? null

  if (loading) return <div className="flex min-h-64 items-center justify-center"><Loader2 className="animate-spin text-(--color-accent)" /></div>
  if (!trace || error) {
    return (
      <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-(--color-error)/30 p-6 text-center">
        <AlertTriangle className="text-(--color-error)" />
        <p className="text-xs text-(--color-error)">{error instanceof Error ? error.message : 'Trace data is unavailable.'}</p>
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>Retry trace</Button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
        <div className="flex flex-col gap-2 @2xl/easd:flex-row @2xl/easd:items-center @2xl/easd:justify-between">
          <div>
            <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">Traceability workspace</p>
            <p className="mt-1 text-xs text-(--color-text-2)">{trace.nodes.length} entities · {trace.edges.length} relations · {trace.events.length} events</p>
          </div>
          <SelectControl
            value={criterionId}
            onValueChange={(value) => { setCriterionId(value); setSelectedNodeId(null) }}
            ariaLabel="Filter trace by acceptance criterion"
            className="text-xs @2xl/easd:w-48"
            options={[{ value: '', label: 'All acceptance criteria' }, ...criterionOptions]}
          />
        </div>
        <p className="mt-2 text-[9px] text-(--color-text-subtle)">Repository generation {trace.store_generation ?? 'local'} · projection v{trace.version}</p>
      </section>

      {trace.diagnostics.map((diagnostic) => (
        <p key={`${diagnostic.code}-${diagnostic.message}`} role="alert" className="rounded-lg border border-(--color-warning)/35 bg-(--color-warning)/8 p-2.5 text-[10px] text-(--color-warning)">{diagnostic.message}</p>
      ))}
      {trace.gaps.length > 0 && (
        <section className="rounded-xl border border-(--color-warning)/35 bg-(--color-warning)/8 p-3">
          <h2 className="text-[10px] font-semibold text-(--color-warning)">Current trace gaps</h2>
          <ul className="mt-1 space-y-1 text-[10px] text-(--color-text-2)">{trace.gaps.map((gap, index) => <li key={`${gap.action_id}-${gap.code}-${index}`}>{gap.message}</li>)}</ul>
        </section>
      )}

      <div className="grid gap-3 @4xl/easd:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)_minmax(12rem,0.8fr)]">
        <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
          <h2 className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-(--color-text-muted)"><Clock3 size={12} /> Activity</h2>
          <ol className="mt-3 space-y-0">
            {trace.events.map((event) => {
              const related = !visibleNodeIds || event.entity_refs.some((ref) => visibleNodeIds.has(ref))
              return (
                <li key={event.id} className={cn('relative border-l border-(--color-border) pb-3 pl-3 last:pb-0', !related && 'opacity-35')}>
                  <span className="absolute -left-1 top-0.5 size-2 rounded-full bg-(--color-accent)" />
                  <p className="text-[10px] font-medium text-(--color-text-2)">{event.event.replaceAll('_', ' ')}</p>
                  <p className="mt-0.5 text-[9px] text-(--color-text-subtle)">#{event.sequence} · {event.actor ?? 'system'}{event.from_status || event.to_status ? ` · ${event.from_status ?? 'new'} → ${event.to_status ?? 'unchanged'}` : ''}</p>
                  {event.created_at && <p className="mt-0.5 text-[9px] text-(--color-text-subtle)">{new Date(event.created_at).toLocaleString()}</p>}
                </li>
              )
            })}
            {trace.events.length === 0 && <li className="text-[10px] text-(--color-text-subtle)">No repository events are available.</li>}
          </ol>
        </section>

        <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
          <div className="flex items-center justify-between gap-2"><h2 className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-(--color-text-muted)"><GitBranch size={12} /> Relationships</h2><span className="text-[9px] text-(--color-text-subtle)">{visibleEdges.length} visible</span></div>
          <div className="mt-3 space-y-3">
            {KIND_ORDER.map((kind) => {
              const rows = visibleNodes.filter((node) => node.kind === kind)
              if (rows.length === 0) return null
              return (
                <div key={kind}>
                  <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">{KIND_LABELS[kind]}</p>
                  <div className="grid gap-1.5 @2xl/easd:grid-cols-2">
                    {rows.map((node) => (
                      <button key={node.id} type="button" onClick={() => setSelectedNodeId(node.id)} className={cn('min-w-0 rounded-lg border bg-(--bg-page) p-2 text-left transition-colors hover:border-(--color-border-strong)', selectedNode?.id === node.id ? 'border-(--color-accent)' : 'border-(--color-border)')}>
                        <p className="truncate text-[10px] font-medium text-(--color-text-2)">{node.label}</p>
                        <p className={cn('mt-0.5 truncate text-[9px]', statusTone(node.status))}>{node.status ?? node.kind}</p>
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        {selectedNode && <NodeInspector node={selectedNode} trace={{ ...trace, edges: visibleEdges }} />}
      </div>
    </div>
  )
}
