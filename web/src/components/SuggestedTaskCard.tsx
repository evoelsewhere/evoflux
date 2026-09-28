/** SuggestedTaskCard — a parked out-of-scope suggestion the user can act on. */
import { useState } from 'react'
import {
  ChevronDown,
  GitBranch,
  Lightbulb,
  MessageSquare,
  Play,
  SquarePlus,
  X,
} from 'lucide-react'

import { dismissSuggestedTask, startSuggestedTask } from '@/api/client'
import type { SuggestedTask } from '@/api/types'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { cn } from '@/lib/utils'

/**
 * Transcript marker for a ``spawn_task`` call.
 *
 * Deliberately not actionable: the dock owns the buttons, and a second live
 * copy of them in the scrollback would go stale the moment the chip is
 * started or dismissed elsewhere.
 */
export function SuggestedTaskToolRow({ args }: { args?: string }) {
  let title = ''
  let tldr = ''
  try {
    const parsed = JSON.parse(args ?? '{}') as { title?: string; tldr?: string }
    title = typeof parsed.title === 'string' ? parsed.title : ''
    tldr = typeof parsed.tldr === 'string' ? parsed.tldr : ''
  } catch {
    // Arguments stream in progressively; an incomplete JSON payload just
    // means the title is not known yet.
  }

  return (
    <div className="my-2 flex items-start gap-2 rounded-md border border-dashed border-(--color-border-subtle) px-2.5 py-1.5">
      <Lightbulb className="mt-0.5 size-3 shrink-0 text-(--color-warning)" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[11px] font-medium text-(--color-text-muted)">
          Suggested task{title ? `: ${title}` : ''}
        </p>
        {tldr && (
          <p className="mt-0.5 line-clamp-2 text-[11px] text-(--color-text-subtle)">
            {tldr}
          </p>
        )}
      </div>
    </div>
  )
}

export interface SuggestedTaskCardProps {
  task: SuggestedTask
  className?: string
}

type StartTarget = 'current' | 'shared' | 'worktree'

export function SuggestedTaskCard({ task, className }: SuggestedTaskCardProps) {
  const [busy, setBusy] = useState<StartTarget | 'dismiss' | null>(null)
  const pushToast = useToastStore((state) => state.push)

  const removeLocally = () => {
    // The SSE event does this too, but only for clients watching this
    // session's stream. Dropping it here keeps the click responsive and
    // makes a repeat click impossible while the request is in flight.
    useTeamStore.setState({
      suggestedTasks: useTeamStore
        .getState()
        .suggestedTasks.filter((t) => t.id !== task.id),
    })
  }

  const start = async (target: StartTarget) => {
    if (busy) return
    setBusy(target)
    try {
      const result = await startSuggestedTask(task.id, {
        isolated: target === 'worktree',
        inCurrentSession: target === 'current',
      })
      removeLocally()
      const store = useTeamStore.getState()
      // Running here keeps the user where they are; the message just joins
      // this session's queue behind whatever the lead is doing now.
      if (store.sessionId !== result.session_id) {
        store.beginResolvedSession(result.session_id, {
          mode: 'coding',
          workspace: result.workspace,
        })
      }
      // Sent from here rather than server-side so the target session starts
      // through the ordinary chat path, with the same permissions, tools and
      // streaming as a message the user typed.
      await store.sendMessage(result.prompt, undefined, {
        mode: 'coding',
        workspace: result.workspace,
      })
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not start the task',
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
  }

  const dismiss = async () => {
    if (busy) return
    setBusy('dismiss')
    try {
      await dismissSuggestedTask(task.id)
      removeLocally()
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not dismiss the suggestion',
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div
      className={cn(
        'w-full overflow-hidden rounded-md border border-(--color-border-subtle) bg-(--bg-page) p-3 text-left',
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-(--color-warning)" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-(--color-text)">{task.title}</p>
          <p className="mt-0.5 text-xs text-(--color-text-muted)">{task.tldr}</p>
        </div>
        <button
          type="button"
          onClick={() => void dismiss()}
          disabled={busy !== null}
          aria-label={`Dismiss suggestion: ${task.title}`}
          className="shrink-0 rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:text-(--color-text) disabled:opacity-50"
        >
          <X className="size-3.5" />
        </button>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <div className="inline-flex items-stretch overflow-hidden rounded-xs bg-(--color-accent)/10 text-[11px] font-medium text-(--color-accent)">
          <button
            type="button"
            onClick={() => void start('shared')}
            disabled={busy !== null}
            className="inline-flex items-center gap-1 px-2 py-1 transition-colors hover:bg-(--color-accent)/20 disabled:opacity-50"
          >
            <Play className="size-3" />
            {busy === 'shared' || busy === 'current' ? 'Starting…' : 'Run'}
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger
              disabled={busy !== null}
              aria-label={`Choose where to run: ${task.title}`}
              className="inline-flex items-center border-l border-(--color-accent)/20 px-1 transition-colors hover:bg-(--color-accent)/20 disabled:opacity-50 data-popup-open:bg-(--color-accent)/20"
            >
              <ChevronDown className="size-3" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-auto min-w-44">
              <DropdownMenuItem onClick={() => void start('current')} className="text-xs">
                <MessageSquare className="size-3.5" />
                Run in current session
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => void start('shared')} className="text-xs">
                <SquarePlus className="size-3.5" />
                Run in new session
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <button
          type="button"
          onClick={() => void start('worktree')}
          disabled={busy !== null}
          className="inline-flex items-center gap-1 rounded-xs bg-(--bg-key) px-2 py-1 text-[11px] font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text) disabled:opacity-50"
        >
          <GitBranch className="size-3" />
          {busy === 'worktree' ? 'Creating…' : 'Start with worktree'}
        </button>
      </div>
    </div>
  )
}
