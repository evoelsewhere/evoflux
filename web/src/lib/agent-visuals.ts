import {
  Braces,
  Hammer,
  type LucideIcon,
} from 'lucide-react'

export type AgentTeam = 'work' | 'coding'

export interface AgentTeamVisual {
  label: string
  description: string
  icon: LucideIcon
  accent: string
  soft: string
  border: string
}

export const AGENT_TEAM_VISUALS: Record<AgentTeam, AgentTeamVisual> = {
  work: {
    label: 'Work',
    description: 'General-purpose research and execution',
    icon: Hammer,
    accent: 'text-(--color-marker-orange)',
    soft: 'bg-(--color-tint-orange)',
    border: 'border-(--color-marker-orange)/25',
  },
  coding: {
    label: 'Coding',
    description: 'Architecture, implementation, and review',
    icon: Braces,
    accent: 'text-(--color-marker-blue)',
    soft: 'bg-(--accent-blue-soft)',
    border: 'border-(--color-marker-blue)/25',
  },
}

const WORK_BUILT_INS = new Set(['executor', 'explorer', 'consultant', 'debate'])
const CODING_BUILT_INS = new Set(['coder', 'explorer', 'debate', 'architect'])

export function agentTeamFromName(name: string): AgentTeam {
  if (name.startsWith('coding/')) return 'coding'
  return 'work'
}

export function agentDisplayName(name: string): string {
  return name.replace(/^coding\//, '')
}

export function isBuiltInAgentName(name: string, role: string): boolean {
  const team = agentTeamFromName(name)
  const basename = agentDisplayName(name).toLowerCase()
  if (role === 'lead') return basename === 'evoflux'
  if (team === 'coding') return CODING_BUILT_INS.has(basename)
  return WORK_BUILT_INS.has(basename)
}
