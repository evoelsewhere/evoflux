/**
 * SessionScheduleIndicator — single schedule icon with badge count.
 *
 * Renders a calendar-clock icon with a badge showing the number of
 * scheduled tasks for the current session. Clicking opens a popover
 * with the full task list and action buttons.
 */

import { useCallback } from 'react'
import { CalendarClock, Pause, Play, RotateCcw, Trash2, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from '@/components/ui/popover'
import {
  useSessionScheduledTasksQuery,
  usePauseScheduledTaskMutation,
  useResumeScheduledTaskMutation,
  useTriggerScheduledTaskMutation,
  useDeleteScheduledTaskMutation,
} from '@/queries/useSchedulerQuery'
import type { ScheduledTaskResponse } from '@/api/types'
import { formatRelativeDate } from '@/utils/format'

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatScheduleLabel(
  task: Pick<ScheduledTaskResponse, 'schedule_type' | 'at_datetime' | 'every_seconds' | 'cron_expression'>,
): string {
  if (task.schedule_type === 'at' && task.at_datetime) {
    return `at ${new Date(task.at_datetime).toLocaleString()}`
  }
  if (task.schedule_type === 'every' && task.every_seconds) {
    const mins = Math.floor(task.every_seconds / 60)
    const secs = task.every_seconds % 60
    if (mins > 0 && secs === 0) return `every ${mins}m`
    if (mins === 0) return `every ${secs}s`
    return `every ${mins}m ${secs}s`
  }
  if (task.schedule_type === 'cron' && task.cron_expression) {
    return `cron: ${task.cron_expression}`
  }
  return 'unknown'
}

// ── Component ────────────────────────────────────────────────────────────────

export interface SessionScheduleIndicatorProps {
  sessionId: string | null
  onOpenScheduler?: () => void
}

export function SessionScheduleIndicator({
  sessionId,
  onOpenScheduler,
}: SessionScheduleIndicatorProps) {
  const tasksQuery = useSessionScheduledTasksQuery(sessionId)
  const pauseMutation = usePauseScheduledTaskMutation()
  const resumeMutation = useResumeScheduledTaskMutation()
  const triggerMutation = useTriggerScheduledTaskMutation()
  const deleteMutation = useDeleteScheduledTaskMutation()

  // Tasks are already filtered server-side by session_id
  const sessionTasks = tasksQuery.data?.tasks ?? []

  const handlePause = useCallback((id: string) => pauseMutation.mutate(id), [pauseMutation])
  const handleResume = useCallback((id: string) => resumeMutation.mutate(id), [resumeMutation])
  const handleTrigger = useCallback((id: string) => triggerMutation.mutate(id), [triggerMutation])
  const handleDelete = useCallback((id: string) => deleteMutation.mutate(id), [deleteMutation])

  // Don't render if no session or no tasks
  if (!sessionId || sessionTasks.length === 0) return null

  return (
    <Popover>
      {/* ── Icon trigger with badge ── */}
      <PopoverTrigger
        className={cn(
          'relative inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors',
          'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
        )}
        title={`${sessionTasks.length} scheduled task${sessionTasks.length !== 1 ? 's' : ''}`}
        aria-label={`${sessionTasks.length} scheduled tasks`}
      >
        <CalendarClock size={14} />
        {/* Badge */}
        <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-(--color-accent) px-1 text-[9px] font-bold leading-none text-white">
          {sessionTasks.length}
        </span>
      </PopoverTrigger>

      {/* ── Popover dropdown ── */}
      <PopoverContent align="start" side="bottom" sideOffset={6} className="w-[300px] p-0">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Clock size={12} className="text-(--color-text-subtle)" />
            <span className="text-xs font-medium text-(--color-text)">Scheduled Tasks</span>
          </div>
          <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[9px] font-medium text-(--color-text-subtle)">
            {sessionTasks.length}
          </span>
        </div>

        {/* Task list */}
        <div className="max-h-64 overflow-y-auto">
          {sessionTasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              onPause={handlePause}
              onResume={handleResume}
              onTrigger={handleTrigger}
              onDelete={handleDelete}
            />
          ))}
        </div>

        {/* Footer */}
        {onOpenScheduler && (
          <div className="border-t border-(--color-border) px-3 py-2">
            <button
              type="button"
              onClick={onOpenScheduler}
              className="text-[11px] text-(--color-accent) hover:underline"
            >
              View all in Scheduler →
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

// ── Task Row ─────────────────────────────────────────────────────────────────

function TaskRow({
  task,
  onPause,
  onResume,
  onTrigger,
  onDelete,
}: {
  task: ScheduledTaskResponse
  onPause: (id: string) => void
  onResume: (id: string) => void
  onTrigger: (id: string) => void
  onDelete: (id: string) => void
}) {
  const enabled = task.enabled

  return (
    <div className="group flex items-start gap-2 border-b border-(--color-border)/50 px-3 py-2 last:border-b-0 hover:bg-(--bg-key)/50">
      {/* Status dot */}
      <span
        className={cn(
          'mt-1 h-2 w-2 shrink-0 rounded-full',
          enabled ? 'bg-green-400' : 'bg-amber-400',
        )}
      />

      {/* Info */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[11px] font-medium text-(--color-text)">{task.name}</p>
        <p className="text-[10px] text-(--color-text-subtle)">{formatScheduleLabel(task)}</p>
        {task.last_run_at && (
          <p className="text-[9px] text-(--color-text-subtle)">Last: {formatRelativeDate(task.last_run_at)}</p>
        )}
      </div>

      {/* Actions */}
      <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
        {enabled ? (
          <button type="button" onClick={() => onPause(task.id)} className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-page) hover:text-(--color-text)" title="Pause" aria-label="Pause">
            <Pause size={11} />
          </button>
        ) : (
          <button type="button" onClick={() => onResume(task.id)} className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-page) hover:text-(--color-text)" title="Resume" aria-label="Resume">
            <Play size={11} />
          </button>
        )}
        <button type="button" onClick={() => onTrigger(task.id)} className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-page) hover:text-(--color-text)" title="Trigger now" aria-label="Trigger">
          <RotateCcw size={11} />
        </button>
        <button type="button" onClick={() => onDelete(task.id)} className="rounded p-1 text-(--color-text-muted) hover:bg-red-500/10 hover:text-red-400" title="Delete" aria-label="Delete">
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  )
}
