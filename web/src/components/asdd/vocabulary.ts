/**
 * The words and colours the Agent Spec-Driven panel uses for a change's state.
 *
 * One module because the panel, the board and the action rail all name the same
 * twelve statuses, and when each kept its own list they drifted: a card read
 * `tasking` while the rail above it called that phase "Plan" and the board
 * column called it "Plan" too. A reader should not have to learn that those are
 * the same thing.
 */
import type { AsddRisk, AsddStatus } from '@/api/types'

/** The seven phases of the cycle, in order. Index is a step number. */
export const ASDD_PHASES = [
  'Propose',
  'Specify',
  'Design',
  'Plan',
  'Implement',
  'Verify',
  'Archive',
] as const

/**
 * Which phase a status sits in.
 *
 * The drafting and approval halves of a phase share an index, because what a
 * reader wants from the rail is which phase the change is in, not whether an
 * agent has finished writing inside it.
 */
export const PHASE_OF: Record<AsddStatus, number> = {
  drafting: 0,
  proposed: 0,
  specifying: 1,
  specified: 1,
  designing: 2,
  designed: 2,
  tasking: 3,
  tasked: 3,
  implementing: 4,
  verifying: 5,
  ready: 6,
  archived: 6,
}

export const STATUS_LABELS: Record<AsddStatus, string> = {
  drafting: 'Drafting',
  proposed: 'Proposed',
  specifying: 'Specifying',
  specified: 'Specified',
  designing: 'Designing',
  designed: 'Designed',
  tasking: 'Planning',
  tasked: 'Planned',
  implementing: 'Implementing',
  verifying: 'Verifying',
  ready: 'Ready',
  archived: 'Archived',
}

/**
 * The statuses where nothing moves until a person acts.
 *
 * This is the one question the panel exists to answer at a glance — is this
 * change waiting on me, or is an agent still working it — so it is a declared
 * set rather than something inferred from the status string. The previous
 * spelling tested `status.endsWith('ed')`, which happened to be right for all
 * twelve and would have been silently wrong for the thirteenth.
 */
export const AWAITING_PERSON: ReadonlySet<AsddStatus> = new Set<AsddStatus>([
  'proposed',
  'specified',
  'designed',
  'tasked',
  'ready',
])

export function isAwaitingPerson(status: string): boolean {
  return AWAITING_PERSON.has(status as AsddStatus)
}

/**
 * The label for a status, including one this build has never heard of.
 *
 * `status` is hand-editable, so the panel has to render whatever the file says
 * — a typo, or a value from a newer build. Showing it verbatim is what lets the
 * rail's `unknown_status` problem make sense to the reader; an empty badge
 * beside "not one of: …" would not.
 */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status as AsddStatus] ?? status
}

export function phaseOf(status: string): number {
  return PHASE_OF[status as AsddStatus] ?? 0
}

export function statusTone(status: string): string {
  if (status === 'archived') return 'bg-(--color-success-subtle) text-(--color-success)'
  if (isAwaitingPerson(status as AsddStatus)) {
    return 'bg-(--color-accent)/12 text-(--color-accent)'
  }
  if (!(status in STATUS_LABELS)) {
    return 'bg-(--color-danger)/12 text-(--color-danger)'
  }
  return 'bg-(--bg-key)/70 text-(--color-text-2)'
}

export const RISK_LABELS: Record<AsddRisk, string> = {
  trivial: 'Trivial',
  standard: 'Standard',
  cross_layer: 'Cross-layer',
  critical: 'Critical',
}

export const RISK_HINTS: Record<AsddRisk, string> = {
  trivial: 'A contained change with no boundary to cross.',
  standard: 'The default. One boundary, ordinary review.',
  cross_layer:
    'Multiple layers or repositories. Requires a design and an independent review.',
  critical:
    'Security, migration, persistence or public compatibility. Requires a design and an independent review.',
}

export function riskLabel(risk: string): string {
  return RISK_LABELS[risk as AsddRisk] ?? risk
}

export function riskTone(risk: string): string {
  if (risk === 'critical') return 'text-(--color-danger)'
  if (risk === 'cross_layer') return 'text-(--color-warning)'
  return 'text-(--color-text-subtle)'
}

/**
 * Whether the design phase applies to this change.
 *
 * A low-risk change may still choose to write a design, so a change sitting in
 * `designing` counts even when its tier would not have required one. Reading it
 * the other way round would label the step "skipped" for a change that is in it.
 */
export function designApplies(risk: string, status: string): boolean {
  return (
    risk === 'cross_layer'
    || risk === 'critical'
    || status === 'designing'
    || status === 'designed'
  )
}

export function relativeTime(value: string | null): string {
  if (!value) return ''
  const stamp = Date.parse(value)
  if (Number.isNaN(stamp)) return ''
  const seconds = Math.round((Date.now() - stamp) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86_400)}d ago`
}

export function errorText(error: unknown): string | null {
  if (!error) return null
  return error instanceof Error ? error.message : String(error)
}
