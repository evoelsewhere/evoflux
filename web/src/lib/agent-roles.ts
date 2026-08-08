/**
 * Canonical agent roles in EvoFlux.
 *
 * These names are special-cased in the UI: each gets a role-specific emblem
 * and palette. Any other agent name falls back to the custom-agent emblem.
 */

import { agentVisualKind, type AgentVisualKind } from '@/lib/agent-visuals'

export type AgentRole = AgentVisualKind

export const AGENT_ROLES: readonly AgentRole[] = [
  'EvoFlux',
  'executor',
  'consultant',
  'explorer',
  'debate',
  'coder',
  'architect',
  'custom',
] as const

/** True when a free-form agent name is itself a visual-role key. */
export function isAgentRole(name: string): name is AgentRole {
  return (AGENT_ROLES as readonly string[]).includes(name)
}

/**
 * Map settings paths and live handles onto a chip role. Unknown agents keep
 * their real label and use the neutral custom-agent palette.
 */
export function resolveAgentRole(name: string): AgentRole {
  return agentVisualKind(name)
}
