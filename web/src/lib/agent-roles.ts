/**
 * Canonical agent roles in EvoFlux.
 *
 * These names are special-cased in the UI: they get an `AgentChip` with a
 * role-specific dot color (mint / orange / blue / muted). Any other agent
 * name falls back to a generic chip.
 */

export type AgentRole = 'EvoFlux' | 'executor' | 'consultant' | 'explorer'

export const AGENT_ROLES: readonly AgentRole[] = [
  'EvoFlux',
  'executor',
  'consultant',
  'explorer',
] as const

/** True when a free-form agent name matches a canonical role. */
export function isAgentRole(name: string): name is AgentRole {
  return (AGENT_ROLES as readonly string[]).includes(name)
}

/**
 * Map a free-form agent name onto a chip role. Unknown / custom agents
 * fall back to the muted explorer palette while keeping their real label.
 */
export function resolveAgentRole(name: string): AgentRole {
  if (isAgentRole(name)) return name
  const lower = name.toLowerCase()
  if (lower === 'lead' || lower === 'evoflux') return 'EvoFlux'
  return 'explorer'
}
