/**
 * BackgroundTaskNotice — a background command telling the agent how it went.
 *
 * `shell(background=true)` tasks announce their own exit (and any
 * `notify_on` match) to the session's lead through the team mailbox; the UI
 * shows that notice as a compact status card instead of an agent message.
 * The full text the model received sits behind a disclosure.
 */

import { useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronUp, Radio, Terminal, XCircle } from 'lucide-react'

import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

export interface BackgroundTaskExtra {
  task_event?: unknown
  process_id?: unknown
  command?: unknown
  status?: unknown
  exit_code?: unknown
  duration_ms?: unknown
  matched_line?: unknown
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

export function BackgroundTaskNotice({
  content,
  extra,
  compact = false,
}: {
  content: string
  extra: BackgroundTaskExtra
  compact?: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)

  const event = extra.task_event === 'matched' ? 'matched' : 'exited'
  const status = typeof extra.status === 'string' ? extra.status : 'succeeded'
  const exitCode = typeof extra.exit_code === 'number' ? extra.exit_code : null
  const command = typeof extra.command === 'string' ? extra.command : ''
  const matched = typeof extra.matched_line === 'string' ? extra.matched_line : ''
  const duration = typeof extra.duration_ms === 'number' ? formatDuration(extra.duration_ms) : null

  const failed = event === 'exited' && status !== 'succeeded'
  const title = event === 'matched'
    ? t('Background task output matched')
    : status === 'timed_out'
      ? t('Background task timed out')
      : failed
        ? t('Background task failed (exit code {0})', [exitCode ?? '?'])
        : t('Background task finished')
  const Icon = event === 'matched' ? Radio : failed ? XCircle : CheckCircle2

  return (
    <div className="mb-4 flex justify-start">
      <div
        className={cn(
          'w-full rounded-lg border border-(--color-border) bg-(--color-surface) shadow-sm',
          compact ? 'max-w-[88%] px-3 py-2 text-xs' : 'max-w-[78%] px-4 py-3 text-sm',
        )}
      >
        <div className="flex items-center gap-2">
          <Icon
            size={15}
            className={cn(
              'shrink-0',
              failed ? 'text-(--color-error)' : event === 'matched'
                ? 'text-(--accent-purple)'
                : 'text-(--color-success)',
            )}
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1 truncate font-medium text-(--color-text)">{title}</span>
          {duration && (
            <span className="shrink-0 tabular-nums text-(--color-text-subtle)">{duration}</span>
          )}
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label={t('Output')}
            title={t('Output')}
            className="flex size-5 shrink-0 items-center justify-center rounded text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
        {command && (
          <p className="mt-1 flex min-w-0 items-center gap-1.5 font-mono text-[11px] text-(--color-text-muted)">
            <Terminal size={11} className="shrink-0" aria-hidden="true" />
            <span className="truncate" title={command}>{command}</span>
          </p>
        )}
        {event === 'matched' && matched && (
          <p className="mt-1 truncate font-mono text-[11px] text-(--color-text-2)" title={matched}>
            {matched}
          </p>
        )}
        {open && (
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-(--bg-key) p-2 font-mono text-[11px] leading-4 text-(--color-text-2)">
            {content}
          </pre>
        )}
      </div>
    </div>
  )
}
