/**
 * TerminalRunningBar — the "Running" drawer at the foot of every Terminal tab.
 *
 * Lists what the process manager is keeping alive — agent commands, preview
 * servers and terminal sessions, across every session — so a stray dev server
 * can be stopped from the place its output would have appeared. The tab's own
 * PTY is left out: closing the tab already ends it.
 */
import { useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronUp,
  CircleStop,
  ExternalLink,
  Loader2,
  RefreshCw,
  Server,
  SquareTerminal,
  Terminal,
} from 'lucide-react'
import type { ManagedProcess, ManagedProcessKind } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  useProcessesQuery,
  useTerminateProcessMutation,
} from '@/queries/useProcessesQuery'

const KIND_META: Record<ManagedProcessKind, {
  label: string
  icon: typeof Terminal
  className: string
}> = {
  command: {
    label: 'Command',
    icon: Terminal,
    className: 'text-(--color-accent)',
  },
  preview: {
    label: 'Preview',
    icon: Server,
    className: 'text-(--color-success)',
  },
  terminal: {
    label: 'Terminal',
    icon: SquareTerminal,
    className: 'text-(--color-text-muted)',
  },
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds % 60)
  if (minutes < 60) return `${minutes}m ${rest}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

function ProcessRow({
  process,
  stopping,
  onStop,
}: {
  process: ManagedProcess
  stopping: boolean
  onStop: () => void
}) {
  const meta = KIND_META[process.kind]
  const Icon = meta.icon
  return (
    <li className="flex min-w-0 items-center gap-2 px-3 py-1.5 hover:bg-(--bg-key)/60">
      <Icon size={13} className={cn('shrink-0', meta.className)} aria-label={meta.label} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-[11px] font-medium text-(--color-text)">
            {process.label}
          </span>
          <span className="shrink-0 font-mono text-[10px] text-(--color-text-subtle)">
            {formatDuration(process.elapsed_seconds)}
            {process.pid != null ? ` · ${process.pid}` : ' · external'}
          </span>
        </div>
        <p
          className="truncate font-mono text-[10px] text-(--color-text-muted)"
          title={process.cwd ? `${process.command}\n${process.cwd}` : process.command}
        >
          {process.command}
        </p>
      </div>
      {process.metadata.url && (
        <a
          href={process.metadata.url}
          target="_blank"
          rel="noreferrer"
          title={process.metadata.url}
          aria-label={`Open ${process.metadata.url}`}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-(--accent-blue-text) hover:bg-(--bg-key)"
        >
          <ExternalLink size={12} />
        </a>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        disabled={!process.killable || stopping}
        onClick={onStop}
        title={process.killable ? 'Stop process' : 'External reused process cannot be stopped'}
        aria-label={`Stop ${process.label}`}
        className="text-(--color-error) hover:text-(--color-error)"
      >
        {stopping ? <Loader2 className="animate-spin" /> : <CircleStop />}
      </Button>
    </li>
  )
}

export function TerminalRunningBar({
  active,
  sessionId,
  terminalId,
}: {
  active: boolean
  sessionId: string | null
  terminalId: string
}) {
  const [open, setOpen] = useState(false)
  // Every Terminal tab shares one cache entry, and only a visible tab polls.
  const query = useProcessesQuery(active)
  const terminate = useTerminateProcessMutation()

  const groups = useMemo(() => {
    const grouped = new Map<string, ManagedProcess[]>()
    for (const process of query.data?.processes ?? []) {
      const ownTab = process.kind === 'terminal'
        && process.session_id === sessionId
        && process.metadata.terminal_id === terminalId
      if (ownTab) continue
      const key = process.session_id ?? '__workspace__'
      grouped.set(key, [...(grouped.get(key) ?? []), process])
    }
    return [...grouped.entries()].sort(([left], [right]) => {
      if (left === sessionId) return -1
      if (right === sessionId) return 1
      return left.localeCompare(right)
    })
  }, [query.data?.processes, sessionId, terminalId])
  const count = groups.reduce((total, [, processes]) => total + processes.length, 0)

  return (
    <section className="shrink-0 border-t border-(--color-border) bg-(--bg-page)">
      <div className="flex h-8 items-center gap-1 pr-1.5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="flex h-full min-w-0 flex-1 items-center gap-1.5 px-3 text-[11px] font-medium text-(--color-text-2) hover:text-(--color-text)"
        >
          {open ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
          <span>Running</span>
          <span className={cn(
            'rounded-full px-1.5 font-mono text-[10px]',
            count > 0
              ? 'bg-(--color-accent)/10 text-(--color-accent)'
              : 'bg-(--bg-key) text-(--color-text-subtle)',
          )}>
            {query.isPending ? '…' : count}
          </span>
        </button>
        {open && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            aria-label="Refresh running processes"
            title="Refresh running processes"
          >
            <RefreshCw className={cn(query.isFetching && 'animate-spin')} />
          </Button>
        )}
      </div>
      {open && (
        <div className="max-h-56 overflow-y-auto border-t border-(--color-border)/60 pb-1">
          {query.isPending ? (
            <div className="flex h-16 items-center justify-center text-(--color-text-muted)">
              <Loader2 size={16} className="animate-spin" />
            </div>
          ) : query.isError ? (
            <p className="px-3 py-3 text-[11px] text-(--color-error)">
              Could not load running processes.
            </p>
          ) : count === 0 ? (
            <p className="px-3 py-3 text-[11px] text-(--color-text-subtle)">
              Nothing else is running. Agent commands, previews, and other terminals appear here.
            </p>
          ) : (
            groups.map(([groupId, processes]) => {
              const current = groupId === sessionId
              const title = current
                ? 'This session'
                : processes[0]?.session_title
                  ?? (groupId === '__workspace__' ? 'Workspace / external' : 'Untitled session')
              return (
                <div key={groupId}>
                  <h3 className="flex items-center gap-1.5 px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">
                    <span className={cn(
                      'size-1.5 rounded-full',
                      current ? 'bg-(--color-accent)' : 'bg-(--color-text-subtle)',
                    )} />
                    <span className="truncate">{title}</span>
                  </h3>
                  <ul>
                    {processes.map((process) => (
                      <ProcessRow
                        key={process.id}
                        process={process}
                        stopping={terminate.isPending && terminate.variables === process.id}
                        onStop={() => terminate.mutate(process.id)}
                      />
                    ))}
                  </ul>
                </div>
              )
            })
          )}
        </div>
      )}
    </section>
  )
}
