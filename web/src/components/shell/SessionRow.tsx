/**
 * SessionRow — the unified session list row shared by the mode sidebars.
 *
 * Every density is one line; the full date (and a scheduled task's name) is
 * the row's tooltip:
 *   - "comfortable" (work Sidebar touch drawer): animated title + sched
 *     badge + running spinner at a 40px touch height.
 *   - "dense" (docked work Sidebar): the same at the nav rows' 32px.
 *   - "compact" (CodingSidebar): title + a short right-aligned date, with a
 *     leading dot only while running (`px-2 py-1 text-xs rounded-md`).
 *
 * Shared behavior: hover-reveal pencil (rename) and trash (delete) action
 * buttons, inline pending-delete Cancel/Delete confirmation, `sched` badge
 * support, double-click to rename, desktop context-menu trigger, and mobile
 * long-press trigger (via
 * LongPressButton).
 */

import { AnimatePresence, motion } from 'framer-motion'
import { Globe2, Loader2, MessageCirclePlus, Pencil, Trash2 } from 'lucide-react'
import { LongPressButton } from '@/components/ui/long-press-button'
import { formatRelativeDate, formatShortDate } from '@/utils/format'
import { useMotionPreset, fadeRise, staggerDelay } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { SessionResponse } from '@/api/types'

export interface SessionRowProps {
  session: SessionResponse
  isActive: boolean
  density?: 'comfortable' | 'dense' | 'compact'
  onSelect: (session: SessionResponse) => void
  onDelete: (session: SessionResponse) => void
  pendingDelete: boolean
  onCancelDelete: () => void
  onConfirmDelete: () => void
  onEdit: (session: SessionResponse) => void
  /** When provided, shows a hover action that opens the session's side chat. */
  onOpenSideChat?: (session: SessionResponse) => void
  mobileLongPressActions?: boolean
  onLongPress?: (session: SessionResponse) => void
  onContextActions?: (
    session: SessionResponse,
    event: React.MouseEvent,
  ) => void
  /** When set, plays a fade-rise enter with stagger derived from this index. */
  enterIndex?: number
  /** Enables HTML5 drag so the row can be dropped onto a sidebar folder. */
  draggable?: boolean
  onDragStart?: (session: SessionResponse, event: React.DragEvent) => void
  onDragEnd?: (session: SessionResponse, event: React.DragEvent) => void
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
  onOpenSideChat,
  mobileLongPressActions = false,
  onLongPress,
  onContextActions,
  enterIndex,
  draggable = false,
  onDragStart,
  onDragEnd,
}: SessionRowProps) {
  const preset = useMotionPreset()
  const index = enterIndex
  const enter = index !== undefined ? fadeRise(preset, 6) : null
  const compact = density === 'compact'
  const dense = density === 'dense'
  const smallActions = compact || dense
  const isScheduled = Boolean(session.scheduled_task_name)
  const isRunning = session.running === true
  const isBrowserCreated = session.tags?.includes('webbridge_origin:browser') ?? false
  const tooltip = [
    session.title || 'Untitled',
    session.scheduled_task_name,
    formatRelativeDate(session.created_at),
  ].filter(Boolean).join(' · ')

  const row = (
    <div
      // The sidebar's rows dominate this app's layout cost: with them
      // hidden a forced layout measured 9.4ms against 28.4ms with them,
      // and the list grows without bound as sessions accumulate.
      // `content-visibility: auto` lets the browser skip layout and paint
      // for rows scrolled out of view, which took the same forced layout
      // from 26.4ms to 12.6ms. `contain: layout style` was tried first and
      // did nothing (29.7ms).
      //
      // The `auto` in `contain-intrinsic-size` is what keeps the scrollbar
      // honest: the browser remembers each row's real rendered height and
      // reuses it, so the placeholder size is only a guess for rows that
      // have never been on screen.
      className={cn(
        'group relative [content-visibility:auto]',
        compact
          ? '[contain-intrinsic-size:auto_28px]'
          : dense
            ? '[contain-intrinsic-size:auto_32px]'
            : '[contain-intrinsic-size:auto_40px]',
      )}
      draggable={draggable || undefined}
      onDragStart={draggable ? (event) => onDragStart?.(session, event) : undefined}
      onDragEnd={draggable ? (event) => onDragEnd?.(session, event) : undefined}
    >
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
        title={tooltip}
        className={cn(
          'flex w-full items-center rounded-md text-left transition-colors',
          compact
            ? 'gap-1.5 px-2 py-1 text-xs'
            : dense
              ? 'h-8 gap-1.5 px-2.5 text-xs'
              : 'min-h-10 gap-2 px-2.5 text-[13px]',
          // Weight never changes on hover — a bolder title reflowed the row
          // under the pointer. The active row is the only one set heavier.
          // Fills are tints of the text colour, not the opaque --bg-key, so
          // they stay translucent over the sidebar's glass/Mica backdrop.
          isActive
            ? 'bg-(--color-text)/7 font-medium text-(--color-text)'
            : 'text-(--color-text-2) hover:bg-(--color-text)/4 hover:text-(--color-text)',
        )}
      >
        {compact ? (
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            {/* Only a running session gets a dot; a grey one on every row
                was noise that said nothing. */}
            {isRunning && (
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-accent)"
                aria-label="Session running"
              />
            )}
            <span className="min-w-0 flex-1 truncate">
              {session.title || 'Untitled'}
            </span>
            {isScheduled && (
              <span className="shrink-0 rounded-xs px-1 py-px text-[10px] leading-tight bg-(--bg-key) text-(--color-text-subtle)">
                sched
              </span>
            )}
            {isBrowserCreated && (
              <Globe2
                size={10}
                className="shrink-0 text-(--color-text-subtle)"
                aria-label="Created from browser"
              />
            )}
            <span className="shrink-0 text-[10px] tabular-nums text-(--color-text-subtle) transition-opacity duration-(--motion-fast) group-hover:opacity-0 group-focus-within:opacity-0 pointer-coarse:opacity-0">
              {formatShortDate(session.created_at)}
            </span>
          </div>
        ) : (
          // One line: the date group header above already says when, so the
          // full stamp (and a scheduled task's name) lives in the tooltip.
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={session.title ?? 'untitled'}
                initial={{ opacity: 0, y: -6 * preset.distance }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 6 * preset.distance }}
                className="min-w-0 truncate"
              >
                {session.title || 'Untitled'}
              </motion.span>
            </AnimatePresence>
            {isScheduled && (
              <span className="shrink-0 rounded-xs bg-(--bg-key) px-1 py-px text-[10px] leading-tight font-normal text-(--color-text-subtle)">
                sched
              </span>
            )}
            {isBrowserCreated && (
              <span title="Created from browser" aria-label="Created from browser">
                <Globe2 size={dense ? 10 : 11} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
              </span>
            )}
            {isRunning && (
              <span
                className="shrink-0 text-(--color-accent)"
                aria-label="Session running"
              >
                <Loader2
                  size={dense ? 10 : 11}
                  className="animate-spin"
                  aria-hidden="true"
                />
              </span>
            )}
          </div>
        )}
      </LongPressButton>

      {!pendingDelete && (
        <>
          <div
            className={cn(
              'absolute top-1/2 z-(--z-panel) flex origin-right -translate-y-1/2 scale-95 items-center gap-0.5 rounded-md border border-(--color-border)/80 bg-(--bg-card)/95 p-0.5 opacity-0 shadow-sm backdrop-blur-sm transition-[opacity,transform] duration-(--motion-fast) group-hover:scale-100 group-hover:opacity-100 group-focus-within:scale-100 group-focus-within:opacity-100 pointer-coarse:scale-100 pointer-coarse:opacity-100',
              compact ? 'right-1' : 'right-1.5',
            )}
          >
            {onOpenSideChat && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onOpenSideChat(session)
                }}
                className="flex h-5 w-5 items-center justify-center rounded-sm text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-(--focus-ring)"
                aria-label={`Open side chat for ${session.title || 'Untitled'}`}
                title="Open side chat"
              >
                <MessageCirclePlus size={smallActions ? 11 : 12} />
              </button>
            )}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onEdit(session)
              }}
              className="flex h-5 w-5 items-center justify-center rounded-sm text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-(--focus-ring)"
              aria-label={`Edit session ${session.title || 'Untitled'}`}
            >
              <Pencil size={smallActions ? 11 : 12} />
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(session)
              }}
              className="flex h-5 w-5 items-center justify-center rounded-sm text-(--color-text-subtle) transition-colors hover:bg-(--color-error-subtle) hover:text-(--color-error) focus-visible:outline-2 focus-visible:outline-(--focus-ring)"
              aria-label={`Delete session ${session.title || 'Untitled'}`}
            >
              <Trash2 size={smallActions ? 11 : 12} />
            </button>
          </div>
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

  if (!enter || index === undefined) return row

  return (
    <motion.div
      initial={enter.initial}
      animate={enter.animate}
      transition={{ ...enter.transition, delay: staggerDelay(preset, index) }}
    >
      {row}
    </motion.div>
  )
}
