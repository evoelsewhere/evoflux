/**
 * SessionRow — the unified session list row shared by the mode sidebars.
 *
 * Two densities, both lifted verbatim from their original sidebars:
 *   - "comfortable" (forge Sidebar): two-line row — animated title +
 *     sched badge + running spinner, relative date underneath
 *     (`px-2.5 py-2 rounded-lg`).
 *   - "compact" (CodingSidebar): single-line row — running dot + title +
 *     right-aligned date (`px-2 py-1 text-xs rounded-md`).
 *
 * Shared behavior: hover-reveal pencil (rename) and trash (delete) action
 * buttons, inline pending-delete Cancel/Delete confirmation, `sched` badge
 * support, a Globe badge for `webbridge`-tagged sessions, double-click to
 * rename, desktop context-menu trigger, and mobile long-press trigger (via
 * LongPressButton).
 */

import { AnimatePresence, motion } from 'framer-motion'
import { Globe, Loader2, Pencil, Trash2 } from 'lucide-react'
import { LongPressButton } from '@/components/ui/long-press-button'
import { formatRelativeDate } from '@/utils/format'
import { cn } from '@/lib/utils'
import type { SessionResponse } from '@/api/types'

export interface SessionRowProps {
  session: SessionResponse
  isActive: boolean
  density?: 'comfortable' | 'compact'
  onSelect: (session: SessionResponse) => void
  onDelete: (session: SessionResponse) => void
  pendingDelete: boolean
  onCancelDelete: () => void
  onConfirmDelete: () => void
  onEdit: (session: SessionResponse) => void
  mobileLongPressActions?: boolean
  onLongPress?: (session: SessionResponse) => void
  onContextActions?: (
    session: SessionResponse,
    event: React.MouseEvent,
  ) => void
}

/**
 * Single session row. Background stays flat on hover; instead the row
 * brightens its text from ``--color-text-2`` to ``--color-text`` as the
 * hover affordance. Active rows keep the solid ``--bg-key`` background.
 */
export function SessionRow({
  session,
  isActive,
  density = 'comfortable',
  onSelect,
  onDelete,
  pendingDelete,
  onCancelDelete,
  onConfirmDelete,
  onEdit,
  mobileLongPressActions = false,
  onLongPress,
  onContextActions,
}: SessionRowProps) {
  const compact = density === 'compact'
  const isScheduled = Boolean(session.scheduled_task_name)
  const isRunning = session.running === true
  const isWebBridge = session.tags?.includes('webbridge') ?? false

  const webBridgeBadge = isWebBridge ? (
    <span
      className="shrink-0 text-(--color-text-muted)"
      aria-label="WebBridge session"
      title="WebBridge session"
    >
      <Globe size={11} aria-hidden="true" />
    </span>
  ) : null

  return (
    <div className="group relative">
      <LongPressButton
        enabled={mobileLongPressActions}
        onLongPress={() => onLongPress?.(session)}
        type="button"
        onClick={() => onSelect(session)}
        onDoubleClick={(e) => {
          e.stopPropagation()
          onEdit(session)
        }}
        onContextMenu={(e) => {
          if (mobileLongPressActions) return
          e.preventDefault()
          onContextActions?.(session, e)
        }}
        className={
          compact
            ? `w-full rounded-md px-2 py-1 text-left text-xs transition-colors ${
                isActive
                  ? 'bg-(--bg-key) text-(--color-text)'
                  : 'text-(--color-text-2) hover:bg-(--bg-key)/50 hover:text-(--color-text)'
              }`
            : `flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors ${
                isActive
                  ? 'bg-(--bg-key) text-(--color-text)'
                  : 'text-(--color-text-2) hover:bg-(--bg-key)/50 hover:text-(--color-text)'
              }`
        }
      >
        {compact ? (
          <div className="flex min-w-0 items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${isRunning ? 'bg-(--color-accent)' : 'bg-(--color-border)'}`}
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1 truncate font-medium">
              {session.title || 'Untitled'}
            </span>
            {webBridgeBadge}
            {isScheduled && (
              <span className="shrink-0 rounded-xs px-1 py-px text-[10px] leading-tight bg-(--bg-key) text-(--color-text-subtle)">
                sched
              </span>
            )}
            <span className="shrink-0 text-[10px] text-(--color-text-subtle)">
              {formatRelativeDate(session.created_at)}
            </span>
          </div>
        ) : (
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <AnimatePresence mode="wait" initial={false}>
                <motion.p
                  key={session.title ?? 'untitled'}
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 6 }}
                  transition={{ duration: 0.18, ease: 'easeOut' }}
                  className={`min-w-0 truncate text-xs transition-colors ${
                    isActive
                      ? 'font-medium text-(--color-text)'
                      : 'text-(--color-text-2) group-hover:font-medium group-hover:text-(--color-text)'
                  }`}
                >
                  {session.title || 'Untitled'}
                </motion.p>
              </AnimatePresence>
              {webBridgeBadge}
              {isScheduled && (
                <span className="shrink-0 rounded-xs px-1 py-px text-xs leading-tight bg-(--bg-key) text-(--color-text-subtle)">
                  sched
                </span>
              )}
              {isRunning && (
                <span
                  className="shrink-0 text-(--color-accent)"
                  aria-label="Session running"
                >
                  <Loader2
                    size={11}
                    className="animate-spin"
                    aria-hidden="true"
                  />
                </span>
              )}
            </div>
            {isScheduled && (
              <p className="mt-0.5 truncate text-xs text-(--color-text-subtle) transition-colors group-hover:text-(--color-text-muted)">
                {session.scheduled_task_name}
              </p>
            )}
            <p className="mt-0.5 truncate text-xs text-(--color-text-subtle) transition-colors group-hover:text-(--color-text-muted)">
              {formatRelativeDate(session.created_at)}
            </p>
          </div>
        )}
      </LongPressButton>

      {!pendingDelete && (
        <>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onEdit(session)
            }}
            className={cn(
              'absolute top-1/2 flex -translate-y-1/2 items-center justify-center rounded-xs p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--bg-key) hover:text-(--color-text) group-hover:opacity-100 pointer-coarse:opacity-100',
              compact ? 'right-6' : 'right-7',
            )}
            aria-label={`Edit session ${session.title || 'Untitled'}`}
          >
            <Pencil size={compact ? 11 : 12} />
          </button>

          {/* Delete on hover */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onDelete(session)
            }}
            className={cn(
              'absolute top-1/2 flex -translate-y-1/2 items-center justify-center rounded-xs p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--color-error-subtle) hover:text-(--color-error) group-hover:opacity-100 pointer-coarse:opacity-100',
              compact ? 'right-1' : 'right-1.5',
            )}
            aria-label={`Delete session ${session.title || 'Untitled'}`}
          >
            <Trash2 size={compact ? 11 : 12} />
          </button>
        </>
      )}

      {pendingDelete && (
        <div
          className={cn(
            'absolute inset-y-0 z-(--z-panel) flex items-center gap-1',
            compact ? 'right-1' : 'right-1.5',
          )}
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onCancelDelete()
            }}
            className="rounded-xs border border-(--color-border) bg-(--bg-card) px-2 py-1 text-xs text-(--color-text) hover:bg-(--bg-key)"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onConfirmDelete()
            }}
            className="rounded-xs bg-(--color-error) px-2 py-1 text-xs text-(--color-text-on-accent) hover:bg-(--color-error)/90"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  )
}
