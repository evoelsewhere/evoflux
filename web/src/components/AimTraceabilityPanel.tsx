import { useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  FileCheck2,
  FileText,
  FlaskConical,
  Link2,
  Map,
  Search,
  Waypoints,
} from 'lucide-react'
import { getAimTraceability } from '@/api/client'
import { setAimKbOpenPath } from '@/lib/aimHandoff'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { AimTraceabilityUnit, CodingProject } from '@/api/types'

export function AimTraceabilityPanel({ project }: { project: CodingProject }) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [phase, setPhase] = useState('all')
  const [gapsOnly, setGapsOnly] = useState(false)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const traceabilityQuery = useQuery({
    queryKey: ['projects', 'detail', project.id, 'aim-traceability'],
    queryFn: () => getAimTraceability(project.id),
    refetchInterval: 10_000,
  })
  const units = useMemo(() => traceabilityQuery.data?.units ?? [], [traceabilityQuery.data])
  const phases = useMemo(
    () => [...new Set(units.map((unit) => unit.phase))].sort(),
    [units],
  )
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return units.filter(
      (unit) =>
        (phase === 'all' || unit.phase === phase) &&
        (!gapsOnly || unit.gaps.length > 0) &&
        (!query ||
          unit.unit.toLowerCase().includes(query) ||
          unit.rules.some((rule) => `${rule.id} ${rule.title}`.toLowerCase().includes(query)) ||
          unit.target_paths.some((path) => path.toLowerCase().includes(query))),
    )
  }, [gapsOnly, phase, search, units])
  const selected = units.find((unit) => unit.unit === selectedKey) ?? null

  const openKb = (path: string | null) => {
    if (!path) return
    setAimKbOpenPath(path)
    navigate({
      to: '/aim/$projectId/$feature',
      params: { projectId: project.id, feature: 'kb' },
    })
  }
  const openRun = (runId: string | null) => {
    if (!runId) return
    navigate({
      to: '/aim/$projectId/runs/$runId',
      params: { projectId: project.id, runId },
    })
  }

  if (traceabilityQuery.isLoading) return <TraceabilitySkeleton />
  if (traceabilityQuery.isError) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-xs text-(--color-error)">
        Traceability data could not be loaded.
      </div>
    )
  }

  const summary = traceabilityQuery.data?.summary
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-(--color-border)">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-accent)">
              <Waypoints size={15} aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-sm font-semibold text-(--color-text)">Traceability</h1>
              <p className="text-[10px] text-(--color-text-subtle)">
                Unit → rule → mapping → evidence coverage
              </p>
            </div>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 md:w-auto">
            <div className="relative min-w-48 flex-1 md:w-64 md:flex-none">
              <Search size={12} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-(--color-text-subtle)" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search units, rules, target paths…"
                className="h-8 pl-8 text-xs"
                aria-label="Search traceability"
              />
            </div>
            <Select value={phase} onValueChange={(value) => setPhase(value ?? 'all')}>
              <SelectTrigger size="sm" className="w-32" aria-label="Filter traceability by phase">
                <SelectValue>{phase === 'all' ? 'All phases' : phase}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All phases</SelectItem>
                {phases.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
              </SelectContent>
            </Select>
            <button
              type="button"
              onClick={() => setGapsOnly((value) => !value)}
              aria-pressed={gapsOnly}
              className={cn(
                'h-8 rounded-md border px-2.5 text-[11px] font-medium transition-colors',
                gapsOnly
                  ? 'border-(--color-warning)/40 bg-(--color-warning-subtle)/25 text-(--color-warning)'
                  : 'border-(--color-border) text-(--color-text-muted) hover:bg-(--bg-key)',
              )}
            >
              Gaps only
            </button>
          </div>
        </div>
        {summary && (
          <div className="grid grid-cols-2 divide-x divide-y divide-(--color-border) border-t border-(--color-border) sm:grid-cols-4 sm:divide-y-0 lg:grid-cols-8">
            <TraceMetric label="Units" value={summary.total_units} />
            <TraceMetric label="Rules reviewed" value={summary.reviewed_units} />
            <TraceMetric label="Mapped" value={summary.mapped_units} />
            <TraceMetric label="With evidence" value={summary.evidenced_units} />
            <TraceMetric label="Rules" value={summary.total_rules} />
            <TraceMetric label="Confirmed" value={summary.confirmed_rules} />
            <TraceMetric label="Links" value={summary.explicit_links} />
            <TraceMetric label="Gaps" value={summary.total_gaps} tone={summary.total_gaps ? 'warn' : 'ok'} />
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1">
        <section className={cn('min-h-0 min-w-0 flex-1 overflow-y-auto', selected && 'hidden lg:block')}>
          <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1fr)_repeat(4,2.5rem)_2rem] items-center border-b border-(--color-border) bg-(--bg-page)/95 px-3 py-2 text-[9px] font-medium uppercase text-(--color-text-subtle) backdrop-blur-sm">
            <span>{filtered.length} units</span>
            <span className="text-center" title="Documentation">Doc</span>
            <span className="text-center" title="Business-rule review">Rules</span>
            <span className="text-center" title="Target mapping">Map</span>
            <span className="text-center" title="Passing compare evidence">Test</span>
            <span />
          </div>
          {filtered.length === 0 ? (
            <p className="px-4 py-10 text-center text-xs text-(--color-text-subtle)">No units match these filters.</p>
          ) : filtered.map((unit) => (
            <TraceabilityRow
              key={unit.unit}
              unit={unit}
              selected={unit.unit === selectedKey}
              onClick={() => setSelectedKey(unit.unit)}
            />
          ))}
        </section>

        <aside className={cn('min-h-0 min-w-0 flex-1 overflow-y-auto border-l border-(--color-border) bg-(--bg-subtle)/25 lg:max-w-[46%]', !selected && 'hidden lg:block')}>
          {selected ? (
            <TraceabilityDetail
              unit={selected}
              onBack={() => setSelectedKey(null)}
              onOpenKb={openKb}
              onOpenRun={openRun}
            />
          ) : (
            <div className="flex h-full items-center justify-center px-6 text-center">
              <div>
                <Waypoints size={22} className="mx-auto text-(--color-text-subtle)" />
                <p className="mt-2 text-xs text-(--color-text-muted)">Select a unit to inspect its evidence chain.</p>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

function TraceMetric({ label, value, tone }: { label: string; value: number; tone?: 'ok' | 'warn' }) {
  return (
    <div className="px-3 py-2">
      <p className="text-[9px] uppercase text-(--color-text-subtle)">{label}</p>
      <p className={cn('mt-0.5 font-mono text-sm font-semibold text-(--color-text)', tone === 'ok' && 'text-(--color-success)', tone === 'warn' && 'text-(--color-warning)')}>{value}</p>
    </div>
  )
}

function CoverageState({ ok, neutral = false }: { ok: boolean; neutral?: boolean }) {
  return neutral ? (
    <span className="mx-auto block h-1.5 w-1.5 rounded-full bg-(--color-border-strong)" />
  ) : ok ? (
    <CircleCheck size={13} className="mx-auto text-(--color-success)" aria-label="Covered" />
  ) : (
    <CircleAlert size={13} className="mx-auto text-(--color-warning)" aria-label="Missing" />
  )
}

function TraceabilityRow({ unit, selected, onClick }: { unit: AimTraceabilityUnit; selected: boolean; onClick: () => void }) {
  const phaseRank = ['inventory', 'understood', 'designed', 'converted', 'equivalent', 'cutover'].indexOf(unit.phase)
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('grid w-full grid-cols-[minmax(0,1fr)_repeat(4,2.5rem)_2rem] items-center border-b border-(--color-border) px-3 py-2.5 text-left transition-colors hover:bg-(--bg-key)/55', selected && 'bg-(--bg-key)')}
    >
      <span className="min-w-0">
        <span className="block truncate font-mono text-xs font-medium text-(--color-text)">{unit.unit}</span>
        <span className="mt-0.5 flex items-center gap-1.5 text-[9px] text-(--color-text-subtle)">
          {unit.phase}{unit.wave !== null ? ` · wave ${unit.wave}` : ''}
          {unit.gaps.length > 0 && <span className="text-(--color-warning)">· {unit.gaps.length} gap{unit.gaps.length === 1 ? '' : 's'}</span>}
        </span>
      </span>
      <CoverageState ok={Boolean(unit.doc_path)} />
      <CoverageState ok={unit.rules_reviewed} neutral={phaseRank < 1} />
      <CoverageState ok={Boolean(unit.mapping_path)} neutral={phaseRank < 2} />
      <CoverageState ok={Boolean(unit.passing_run_id)} neutral={phaseRank < 4} />
      <ChevronRight size={13} className="justify-self-end text-(--color-text-subtle)" />
    </button>
  )
}

function TraceabilityDetail({ unit, onBack, onOpenKb, onOpenRun }: { unit: AimTraceabilityUnit; onBack: () => void; onOpenKb: (path: string | null) => void; onOpenRun: (runId: string | null) => void }) {
  return (
    <div className="p-4">
      <button type="button" onClick={onBack} className="mb-3 inline-flex items-center gap-1 text-xs text-(--color-text-muted) hover:text-(--color-text) lg:hidden">
        <ArrowLeft size={13} /> Back
      </button>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-mono text-sm font-semibold text-(--color-text)">{unit.unit}</h2>
          <p className="mt-1 text-[10px] text-(--color-text-subtle)">{unit.kind} · {unit.phase}{unit.wave !== null ? ` · wave ${unit.wave}` : ''}</p>
        </div>
        <span className={cn('rounded border px-2 py-1 text-[10px] font-medium', unit.gaps.length ? 'border-(--color-warning)/35 bg-(--color-warning-subtle)/25 text-(--color-warning)' : 'border-(--color-success)/30 bg-(--color-success-subtle)/25 text-(--color-success)')}>
          {unit.gaps.length ? `${unit.gaps.length} gaps` : 'Covered'}
        </span>
      </div>

      {unit.gaps.length > 0 && (
        <DetailSection title="Coverage gaps" Icon={CircleAlert} tone="warning">
          <ul className="space-y-1.5 text-xs text-(--color-text-2)">
            {unit.gaps.map((gap) => <li key={gap} className="rounded bg-(--color-warning-subtle)/20 px-2.5 py-2">{gap}</li>)}
          </ul>
        </DetailSection>
      )}

      <DetailSection title="Artifacts" Icon={FileCheck2}>
        <div className="grid gap-1.5 sm:grid-cols-2">
          <ArtifactButton label="Unit documentation" path={unit.doc_path} Icon={FileText} onOpen={onOpenKb} />
          <ArtifactButton label="Target mapping" path={unit.mapping_path} Icon={Map} onOpen={onOpenKb} />
          <ArtifactButton label="Compare evidence" path={unit.passing_run_id ? `run:${unit.passing_run_id}` : null} Icon={FlaskConical} onOpen={() => onOpenRun(unit.passing_run_id)} />
          <div className="rounded-md border border-(--color-border) px-2.5 py-2">
            <p className="text-[9px] uppercase text-(--color-text-subtle)">Recorded runs</p>
            <p className="mt-1 font-mono text-xs text-(--color-text)">{unit.run_count}{unit.latest_verdict ? ` · ${unit.latest_verdict}` : ''}</p>
          </div>
        </div>
      </DetailSection>

      <DetailSection title={`Business rules · ${unit.rules.length}`} Icon={FileText}>
        {unit.rules.length === 0 ? <p className="text-xs text-(--color-text-subtle)">No rule documents linked to this unit.</p> : (
          <div className="space-y-1.5">
            {unit.rules.map((rule) => (
              <button key={rule.id} type="button" onClick={() => onOpenKb(rule.path)} className="flex w-full items-start justify-between gap-2 rounded-md border border-(--color-border) px-2.5 py-2 text-left hover:bg-(--bg-key)">
                <span className="min-w-0"><span className="block font-mono text-[10px] text-(--color-text)">{rule.id}</span><span className="mt-0.5 block truncate text-[10px] text-(--color-text-muted)">{rule.title}</span></span>
                <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[8px] uppercase', rule.status === 'confirmed' ? 'bg-(--color-success-subtle)/25 text-(--color-success)' : 'bg-(--color-warning-subtle)/25 text-(--color-warning)')}>{rule.status}</span>
              </button>
            ))}
          </div>
        )}
      </DetailSection>

      <DetailSection title="Dependencies" Icon={Waypoints}>
        {unit.depends_on.length === 0 ? <p className="text-xs text-(--color-text-subtle)">No dependencies declared.</p> : <div className="flex flex-wrap gap-1">{unit.depends_on.map((item) => <span key={item} className="rounded bg-(--bg-key) px-1.5 py-1 font-mono text-[9px] text-(--color-text-muted)">{item}</span>)}</div>}
      </DetailSection>

      {(unit.links.length > 0 || unit.target_paths.length > 0) && (
        <DetailSection title="Explicit links" Icon={Link2}>
          <div className="space-y-1.5">
            {unit.links.map((link) => <div key={link.id} className="rounded-md border border-(--color-border) px-2.5 py-2"><p className="text-[9px] font-medium uppercase text-(--color-text-subtle)">{link.kind}</p><p className="mt-1 break-all font-mono text-[9px] text-(--color-text-muted)">{link.from_ref} → {link.to_ref}</p>{link.note && <p className="mt-1 text-[10px] text-(--color-text-2)">{link.note}</p>}</div>)}
            {unit.target_paths.map((path) => <div key={path} className="rounded bg-(--bg-key) px-2 py-1.5 font-mono text-[9px] text-(--color-text-muted)">target:{path}</div>)}
          </div>
        </DetailSection>
      )}
    </div>
  )
}

function ArtifactButton({ label, path, Icon, onOpen }: { label: string; path: string | null; Icon: typeof FileText; onOpen: (path: string | null) => void }) {
  return (
    <button type="button" disabled={!path} onClick={() => onOpen(path)} className="flex min-w-0 items-center gap-2 rounded-md border border-(--color-border) px-2.5 py-2 text-left transition-colors hover:bg-(--bg-key) disabled:cursor-default disabled:opacity-45">
      <Icon size={13} className={path ? 'text-(--color-success)' : 'text-(--color-text-subtle)'} />
      <span className="min-w-0"><span className="block text-[10px] font-medium text-(--color-text-2)">{label}</span><span className="block truncate font-mono text-[8px] text-(--color-text-subtle)">{path ?? 'missing'}</span></span>
    </button>
  )
}

function DetailSection({ title, Icon, tone, children }: { title: string; Icon: typeof FileText; tone?: 'warning'; children: React.ReactNode }) {
  return (
    <section className="mt-5 border-t border-(--color-border) pt-3">
      <h3 className={cn('mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-(--color-text-subtle)', tone === 'warning' && 'text-(--color-warning)')}><Icon size={11} />{title}</h3>
      {children}
    </section>
  )
}

function TraceabilitySkeleton() {
  return (
    <div className="h-full p-4" aria-label="Loading traceability">
      <div className="flex items-center justify-between gap-3"><Skeleton className="h-8 w-40" /><Skeleton className="h-8 w-72" /></div>
      <div className="mt-4 grid grid-cols-4 gap-2 lg:grid-cols-8">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-12" />)}</div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">{Array.from({ length: 10 }, (_, index) => <Skeleton key={index} className="h-14" />)}</div>
    </div>
  )
}