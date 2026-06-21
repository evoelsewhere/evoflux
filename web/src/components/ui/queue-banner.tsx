/**
 * QueueBanner — aggregate "messages waiting" header for the pending queue.
 *
 * Pencil component `agDAu` (QueueBanner):
 *   [● QUEUE · 2 messages awaiting                ⌄]
 *
 * - Mono, 11px, weight 600, letter-spacing 0.6
 * - Orange marker dot (--color-marker-orange)
 * - --color-surface fill, --color-border outline, soft drop shadow
 * - Optional expand chevron rotates when expanded
 * - radius-md
 *
 * Used as a header above the per-message PendingMessageQueue list. The
 * banner summarises *count*; the list summarises *content*.
 */

import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface QueueBannerProps {
  count: number
  expanded?: boolean
  onToggle?: () => void
  className?: string
  /** Override the noun ("messages") if needed. */
  noun?: string
}

export function QueueBanner({
  count,
  expanded = true,
  onToggle,
  className,
  noun = 'messages',
}: QueueBannerProps) {
  if (count <= 0) return null

  const Icon = expanded ? ChevronUp : ChevronDown
  const labelNoun = count === 1 ? noun.replace(/s$/, '') : noun
  const interactive = Boolean(onToggle)

  const content = (
    <>
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-marker-orange)"
        aria-hidden="true"
      />
      <span className="font-mono text-[11px] font-semibold tracking-wider text-(--color-text)">
        QUEUE · {count} {labelNoun} awaiting
      </span>
      <span className="ml-auto" aria-hidden="true">
        {interactive && (
          <Icon
            size={14}
            className="text-(--color-text-2) transition-transform"
          />
        )}
      </span>
    </>
  )

  const baseClasses =
    'flex w-full items-center gap-2 rounded-md border border-(--color-border) bg-(--color-surface) px-4 py-2.5 shadow-(--shadow-depth)'

  if (interactive) {
    return (
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-label={`${count} ${labelNoun} awaiting (click to ${expanded ? 'collapse' : 'expand'})`}
        className={cn(
          baseClasses,
          'transition-colors hover:bg-(--bg-key)',
          className,
        )}
      >
        {content}
      </button>
    )
  }

  return (
    <div className={cn(baseClasses, className)} role="status" aria-live="polite">
      {content}
    </div>
  )
}
