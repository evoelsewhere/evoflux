import { useMemo } from 'react'
import {
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
import { ScrollArea } from '@/components/ui/scroll-area'
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
    className: 'bg-(--color-accent)/10 text-(--color-accent)',
  },
  preview: {
    label: 'Preview',
    icon: Server,
    className: 'bg-(--color-success)/10 text-(--color-success)',
  },
  terminal: {
    label: 'Terminal',
    icon: SquareTerminal,
    className: 'bg-(--bg-key) text-(--color-text-2)',
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
    <article className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3 shadow-sm">
      <div className="flex items-start gap-2.5">
        <span className={cn(
          'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg',
          meta.className,
        )}>
          <Icon size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <h3 className="truncate text-xs font-semibold text-(--color-text)">
              {process.label}
            </h3>
            <span className="shrink-0 rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-(--color-text-muted)">
              {meta.label}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 break-all font-mono text-[10px] leading-4 text-(--color-text-muted)">
            {process.command}
          </p>
        </div>
        <Button
          type="button"
          variant="destructive"
          size="icon-sm"
          disabled={!process.killable || stopping}
          onClick={onStop}
          title={process.killable ? 'Stop process' : 'External reused process cannot be stopped'}
          aria-label={`Stop ${process.label}`}
        >
          {stopping ? <Loader2 className="animate-spin" /> : <CircleStop />}
        </Button>
      </div>
      <dl className="mt-2.5 grid grid-cols-[auto_1fr_auto_1fr] gap-x-2 gap-y-1 border-t border-(--color-border)/60 pt-2 text-[10px]">
        <dt className="text-(--color-text-subtle)">PID</dt>
        <dd className="font-mono text-(--color-text-muted)">{process.pid ?? 'external'}</dd>
        <dt className="text-(--color-text-subtle)">Running</dt>
        <dd className="font-mono text-(--color-text-muted)">{formatDuration(process.elapsed_seconds)}</dd>
      </dl>
      {process.metadata.url && (
        <a
          href={process.metadata.url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 flex min-w-0 items-center gap-1 truncate text-[10px] text-(--accent-blue-text) hover:underline"
        >
          <ExternalLink size={10} className="shrink-0" />
          <span className="truncate">{process.metadata.url}</span>
        </a>
      )}
      {process.cwd && (
        <p className="mt-1 truncate font-mono text-[9px] text-(--color-text-subtle)" title={process.cwd}>
          {process.cwd}
        </p>
      )}
    </article>
  )
}

export function ProcessPanel({
  active,
  currentSessionId,
}: {
  active: boolean
  currentSessionId: string | null
}) {
  const query = useProcessesQuery(active)
  const terminate = useTerminateProcessMutation()
  const groups = useMemo(() => {
    const grouped = new Map<string, ManagedProcess[]>()
    for (const process of query.data?.processes ?? []) {
      const key = process.session_id ?? '__workspace__'
      grouped.set(key, [...(grouped.get(key) ?? []), process])
    }
    return [...grouped.entries()].sort(([left], [right]) => {
      if (left === currentSessionId) return -1
      if (right === currentSessionId) return 1
      return left.localeCompare(right)
    })
  }, [currentSessionId, query.data?.processes])

  return (
    <div className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-(--color-border) px-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-(--color-text)">Running processes</p>
          <p className="text-[10px] text-(--color-text-subtle)">
            {query.data?.processes.length ?? 0} active across all sessions
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
          aria-label="Refresh processes"
          title="Refresh processes"
        >
          <RefreshCw className={cn(query.isFetching && 'animate-spin')} />
        </Button>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        {query.isPending ? (
          <div className="flex h-48 items-center justify-center text-(--color-text-muted)">
            <Loader2 size={18} className="animate-spin" />
          </div>
        ) : query.isError ? (
          <div className="mx-3 mt-3 rounded-lg border border-(--color-error)/25 bg-(--color-error-subtle) p-3 text-xs text-(--color-error)">
            Could not load running processes.
          </div>
        ) : groups.length === 0 ? (
          <div className="flex h-56 flex-col items-center justify-center gap-2 px-6 text-center">
            <CircleStop size={22} className="text-(--color-text-subtle)" />
            <p className="text-xs font-medium text-(--color-text-muted)">No processes are running</p>
            <p className="text-[10px] leading-4 text-(--color-text-subtle)">
              Commands, previews, and terminal sessions will appear here automatically.
            </p>
          </div>
        ) : (
          <div className="space-y-5 p-3">
            {groups.map(([sessionId, processes]) => {
              const first = processes[0]
              const current = sessionId === currentSessionId
              return (
                <section key={sessionId}>
                  <div className="mb-2 flex min-w-0 items-center gap-2 px-0.5">
                    <span className={cn(
                      'size-1.5 shrink-0 rounded-full',
                      current ? 'bg-(--color-accent)' : 'bg-(--color-text-subtle)',
                    )} />
                    <h2 className="truncate text-[11px] font-semibold text-(--color-text-2)">
                      {first?.session_title ?? (sessionId === '__workspace__' ? 'Workspace / external' : 'Untitled session')}
                    </h2>
                    {current && (
                      <span className="shrink-0 rounded-full bg-(--color-accent)/10 px-1.5 py-0.5 text-[9px] font-medium text-(--color-accent)">
                        Current
                      </span>
                    )}
                    <span className="ml-auto shrink-0 font-mono text-[9px] text-(--color-text-subtle)">
                      {sessionId === '__workspace__' ? 'no session' : sessionId.slice(0, 8)}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {processes.map((process) => (
                      <ProcessRow
                        key={process.id}
                        process={process}
                        stopping={terminate.isPending && terminate.variables === process.id}
                        onStop={() => terminate.mutate(process.id)}
                      />
                    ))}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
