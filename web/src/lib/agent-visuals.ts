import {
  Bot,
  BrainCircuit,
  Braces,
  Code2,
  Compass,
  DraftingCompass,
  Hammer,
  Scale,
  Sparkles,
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

export type AgentVisualKind =
  | 'EvoFlux'
  | 'executor'
  | 'explorer'
  | 'consultant'
  | 'debate'
  | 'coder'
  | 'architect'
  | 'custom'

export interface AgentIdentityVisual {
  label: string
  icon: LucideIcon
  accent: string
  soft: string
  border: string
}

export const AGENT_IDENTITY_VISUALS: Record<AgentVisualKind, AgentIdentityVisual> = {
  EvoFlux: {
    label: 'EvoFlux',
    icon: Sparkles,
    accent: 'text-(--color-marker-mint)',
    soft: 'bg-(--color-tint-mint)',
    border: 'border-(--color-marker-mint)/30',
  },
  executor: {
    label: 'Executor',
    icon: Hammer,
    accent: 'text-(--color-marker-orange)',
    soft: 'bg-(--color-tint-orange)',
    border: 'border-(--color-marker-orange)/30',
  },
  explorer: {
    label: 'Explorer',
    icon: Compass,
    accent: 'text-(--color-marker-blue)',
    soft: 'bg-(--color-info-subtle)',
    border: 'border-(--color-marker-blue)/30',
  },
  consultant: {
    label: 'Consultant',
    icon: BrainCircuit,
    accent: 'text-(--color-marker-yellow)',
    soft: 'bg-(--color-warning-subtle)',
    border: 'border-(--color-marker-yellow)/30',
  },
  debate: {
    label: 'Debate',
    icon: Scale,
    accent: 'text-(--color-marker-pink)',
    soft: 'bg-(--accent-pink-soft)',
    border: 'border-(--color-marker-pink)/30',
  },
  coder: {
    label: 'Coder',
    icon: Code2,
    accent: 'text-(--color-violet)',
    soft: 'bg-(--color-tint-violet)',
    border: 'border-(--color-violet)/30',
  },
  architect: {
    label: 'Architect',
    icon: DraftingCompass,
    accent: 'text-(--color-marker-blue)',
    soft: 'bg-(--accent-blue-soft)',
    border: 'border-(--color-marker-blue)/30',
  },
  custom: {
    label: 'Agent',
    icon: Bot,
    accent: 'text-(--color-text-muted)',
    soft: 'bg-(--bg-key)',
    border: 'border-(--color-border-strong)',
  },
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

/** Resolve settings paths and live handles (e.g. coder#2) to one visual role. */
export function agentVisualKind(name: string, role?: 'lead' | 'member'): AgentVisualKind {
  if (role === 'lead') return 'EvoFlux'
  const basename = agentDisplayName(name)
    .replace(/#\d+$/, '')
    .trim()
    .toLowerCase()
  if (basename === 'lead' || basename === 'evoflux') return 'EvoFlux'
  if (basename in AGENT_IDENTITY_VISUALS && basename !== 'custom') {
    return basename as Exclude<AgentVisualKind, 'EvoFlux' | 'custom'>
  }
  return 'custom'
}

export function isBuiltInAgentName(name: string, role: string): boolean {
  const team = agentTeamFromName(name)
  const basename = agentDisplayName(name).toLowerCase()
  if (role === 'lead') return basename === 'evoflux'
  if (team === 'coding') return CODING_BUILT_INS.has(basename)
  return WORK_BUILT_INS.has(basename)
}
