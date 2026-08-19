import { useMemo, useState } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  Ban,
  CheckCircle2,
  Info,
  Loader2,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Sparkles,
} from 'lucide-react'

import { createChangeSet } from '@/api/client'
import type { CodingProblem, ProblemSeverity, ProblemSource } from '@/api/types'
import { useProblemDecisionMutation, useProblemsQuery } from '@/queries'
import { useChangeSetStore } from '@/stores/useChangeSetStore'
import { useToastStore } from '@/stores/useToastStore'
import { cn } from '@/lib/utils'

const SOURCE_LABELS: Record<ProblemSource, string> = {
  lsp: 'LSP',
  static: 'Static',
  build: 'Build',
  test: 'Test',
  ai_review: 'AI review',
  security: 'Security',
  plugin: 'Plugin',
}

function SeverityIcon({ severity }: { severity: ProblemSeverity }) {
  if (severity === 'error') return <AlertCircle size={14} className="text-(--color-error)" />
  if (severity === 'warning') return <AlertTriangle size={14} className="text-(--color-warning)" />
  if (severity === 'hint') return <Sparkles size={14} className="text-(--color-accent)" />
  return <Info size={14} className="text-(--color-info)" />
}

function problemPrompt(problem: CodingProblem, verb: string): string {
  const location = problem.path
    ? `${problem.path}${problem.line ? `#L${problem.line}` : ''}`
    : problem.scope
  return `${verb} this ${problem.source} problem at \`${location}\`:\n\n${problem.message}`
}

export function ProblemsPanel({
  workspace,
  active,
  onOpenFile,
  onSendToAgent,
}: {
  workspace: string
  active: boolean
  onOpenFile?: (path: string) => void
  onSendToAgent?: (prompt: string) => void
}) {
  const [source, setSource] = useState<ProblemSource | 'all'>('all')
  const query = useProblemsQuery(workspace, active)
  const decision = useProblemDecisionMutation(workspace)
  const setChangeSet = useChangeSetStore((state) => state.setActive)
  const pushToast = useToastStore((state) => state.push)
  const rows = useMemo(
    () => (query.data?.problems ?? []).filter((problem) => source === 'all' || problem.source === source),
    [query.data?.problems, source],
  )

  const stageFix = async (problem: CodingProblem) => {
    if (!problem.fix) return
    try {
      const fix = problem.fix as {
        workspace_edit?: Record<string, unknown>
        files?: Array<{ path: string; proposed_content: string; base_hash?: string; document_version?: number }>
      }
      const changeSet = await createChangeSet(workspace, {
        origin: problem.source === 'ai_review' ? 'review' : 'lsp',
        title: problem.title ?? `Fix ${problem.code ?? problem.source} problem`,
        description: problem.message,
        workspace_edit: fix.workspace_edit,
        files: fix.files,
      })
      setChangeSet(changeSet)
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not stage fix',
        description: error instanceof Error ? error.message : undefined,
      })
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-3 py-2.5">
        <AlertCircle size={15} className="text-(--color-accent)" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-(--color-text)">Problems</p>
          <p className="text-[11px] text-(--color-text-muted)">
            {query.data?.counts.error ?? 0} errors · {query.data?.counts.warning ?? 0} warnings
          </p>
        </div>
        <button
          type="button"
          onClick={() => { void query.refetch() }}
          disabled={query.isFetching}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Refresh problems"
        >
          <RefreshCw size={13} className={cn(query.isFetching && 'animate-spin')} />
        </button>
      </header>
      <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-(--color-border) px-3 py-2">
        {(['all', ...Object.keys(SOURCE_LABELS)] as Array<ProblemSource | 'all'>).map((item) => (
          <button
            type="button"
            key={item}
            onClick={() => setSource(item)}
            className={cn(
              'shrink-0 rounded-md px-2 py-1 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key)',
              source === item && 'bg-(--bg-key) font-medium text-(--color-text)',
            )}
          >
            {item === 'all' ? 'All' : SOURCE_LABELS[item]}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {query.isLoading ? (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-(--color-text-muted)">
            <Loader2 size={14} className="animate-spin" /> Loading problems…
          </div>
        ) : query.isError ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
            <AlertTriangle size={22} className="text-(--color-error)" />
            <p className="text-sm text-(--color-text)">Could not load Problems</p>
            <p className="text-xs text-(--color-text-muted)">
              {query.error instanceof Error ? query.error.message : 'The repository problem state is unavailable.'}
            </p>
            <button
              type="button"
              onClick={() => { void query.refetch() }}
              className="mt-1 rounded-md bg-(--bg-key) px-2.5 py-1.5 text-xs text-(--color-text-2) hover:bg-(--color-border)"
            >
              Retry
            </button>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
            <CheckCircle2 size={22} className="text-(--color-success)" />
            <p className="text-sm text-(--color-text)">No open problems</p>
            <p className="text-xs text-(--color-text-muted)">A clean panel does not replace behavioral verification.</p>
          </div>
        ) : (
          <ul className="divide-y divide-(--color-border-subtle)">
            {rows.map((problem) => (
              <li key={problem.id} className="group px-3 py-2.5 hover:bg-(--bg-key)/45">
                <div className="flex items-start gap-2">
                  <span className="mt-0.5"><SeverityIcon severity={problem.severity} /></span>
                  <button
                    type="button"
                    disabled={!problem.path}
                    onClick={() => problem.path && onOpenFile?.(problem.path)}
                    className="min-w-0 flex-1 text-left disabled:cursor-default"
                  >
                    <span className="block text-xs leading-5 text-(--color-text)">{problem.title ?? problem.message}</span>
                    {problem.title && <span className="mt-0.5 block text-[11px] leading-4 text-(--color-text-muted)">{problem.message}</span>}
                    <span className="mt-1 block truncate font-mono text-[10px] text-(--color-text-subtle)">
                      {problem.path ?? problem.scope}{problem.line ? `:${problem.line}:${problem.column ?? 1}` : ''}
                      {' · '}{SOURCE_LABELS[problem.source]}{problem.code ? ` · ${problem.code}` : ''}
                    </span>
                  </button>
                </div>
                <div className="mt-2 flex flex-wrap items-center justify-end gap-1 opacity-70 transition-opacity group-hover:opacity-100">
                  {problem.fix && (
                    <button type="button" onClick={() => { void stageFix(problem) }} className="rounded-md px-2 py-1 text-[10px] text-(--color-accent) hover:bg-(--bg-key)">Fix</button>
                  )}
                  {onSendToAgent && (
                    <>
                      <button type="button" onClick={() => onSendToAgent(problemPrompt(problem, 'Add to the implementation plan and address'))} className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)"><MessageSquarePlus size={10} /> Add to plan</button>
                      <button type="button" onClick={() => onSendToAgent(problemPrompt(problem, 'Investigate and fix'))} className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)"><Send size={10} /> Send to agent</button>
                    </>
                  )}
                  <button type="button" onClick={() => decision.mutate({ id: problem.id, action: 'dismiss' })} className="rounded-md px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)">Dismiss</button>
                  <button type="button" onClick={() => decision.mutate({ id: problem.id, action: 'suppress' })} className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)"><Ban size={10} /> Suppress</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
