/**
 * TierBadge — visual label for a team member's task-access tier.
 *
 * Maps the four backend tiers to distinct colours so it's immediately
 * clear from the pane header how much tool power a member currently has:
 *
 *   trivial    – neutral muted   (read-only; no writes/shell/exec)
 *   simple     – blue info       (standard coding tools; no browser)
 *   multi_step – accent/purple   (full tool suite)
 *   complex    – amber/orange    (full tool suite, heavyweight tasks)
 */
import type { TodoTier } from '@/api/types'

const TIER_LABEL: Record<TodoTier, string> = {
  trivial: 'trivial',
  simple: 'simple',
  multi_step: 'multi-step',
  complex: 'complex',
}

const TIER_CLASS: Record<TodoTier, string> = {
  trivial: 'text-(--color-text-subtle) bg-(--bg-key)',
  simple:  'text-(--color-info) bg-(--color-info)/10',
  multi_step: 'text-(--color-accent) bg-(--color-accent)/10',
  complex: 'text-(--accent-orange-text) bg-(--accent-orange)/10',
}

interface TierBadgeProps {
  tier: TodoTier
  /** Extra Tailwind classes */
  className?: string
}

export function TierBadge({ tier, className = '' }: TierBadgeProps) {
  return (
    <span
      className={`shrink-0 rounded px-1 py-0.5 font-mono text-xs font-medium leading-none ${TIER_CLASS[tier]} ${className}`}
      title={`Tool access tier: ${TIER_LABEL[tier]}`}
      aria-label={`Tier: ${TIER_LABEL[tier]}`}
    >
      {TIER_LABEL[tier]}
    </span>
  )
}

