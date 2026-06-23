/**
 * Tier resolution utility — mirrors the backend ``resolve_member_tier`` logic.
 *
 * Returns the *highest* tier among active (pending/in_progress) tasks assigned
 * to *agentName*, or ``null`` when none exist.
 */
import type { TodoTier } from '@/api/types'

const TIER_ORDER: Record<TodoTier, number> = {
  trivial: 0,
  simple: 1,
  multi_step: 2,
  complex: 3,
}

const VALID_TIERS = new Set<string>(['trivial', 'simple', 'multi_step', 'complex'])

export function resolveMemberTier(
  todos: Array<{ tier?: string | null; assigned_to?: string | null; claimed_by?: string | null; status?: string }>,
  agentName: string,
): TodoTier | null {
  let best: TodoTier | null = null
  let bestRank = -1

  for (const item of todos) {
    const assigned = item.assigned_to ?? item.claimed_by
    if (assigned !== agentName) continue
    const status = item.status ?? ''
    if (status === 'completed' || status === 'cancelled') continue
    const tier = (item.tier && VALID_TIERS.has(item.tier) ? item.tier : 'simple') as TodoTier
    const rank = TIER_ORDER[tier]
    if (rank > bestRank) {
      bestRank = rank
      best = tier
    }
  }

  return best
}
