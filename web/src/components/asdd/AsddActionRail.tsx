import type { ReactNode } from 'react'
import { AlertTriangle, Check, PauseCircle } from 'lucide-react'

import type { AsddActionRail as AsddActionRailContract, AsddStatus } from '@/api/types'
import { cn } from '@/lib/utils'
import { ASDD_PHASES, designApplies, phaseOf } from './vocabulary'

const PHASE_MESSAGES: Record<AsddStatus, string> = {
  drafting: 'No proposal has been written yet.',
  proposed: 'Read the proposal and approve it before specification starts.',
  specifying: 'An agent is writing the capability deltas. Product files stay read-only.',
  specified: 'Read the deltas and approve them before planning starts.',
  designing: 'This risk tier needs a design document before tasks are written.',
  designed: 'Read the design and approve it before tasks are written.',
  tasking: 'An agent is turning the approved deltas into a task checklist.',
  tasked: 'Approve the tasks; approval is what authorizes product-file changes.',
  implementing: 'Tasks are being executed against the approved requirements.',
  verifying: 'Requirements are being checked and evidence recorded. Nothing is fixed here.',
  ready: 'Archiving folds the deltas into the capability specs. Only a new change undoes it.',
  archived: 'The deltas are part of the capability specs; the folder is in the archive.',
}

/**
 * What the rail says while autopilot is carrying the change.
 *
 * The default messages all describe a change waiting on the reader, which is
 * exactly wrong once nothing is waiting on them.
 */
const AUTOPILOT_MESSAGES: Partial<Record<AsddStatus, string>> = {
  proposed: 'Autopilot read the proposal and is carrying it to specification.',
  specified: 'Autopilot read the deltas and is carrying them to planning.',
  designed: 'Autopilot read the design and is carrying it to planning.',
  tasked: 'Autopilot approved the tasks and is starting implementation.',
  implementing: 'Autopilot is working the tasks and will verify when they are done.',
  verifying: 'Autopilot is recording evidence and will mark the change ready.',
  ready: 'Autopilot stops here. Archiving is yours at every risk tier.',
}

interface AsddActionRailProps {
  /** Plain strings: `status` is hand-editable and may be one this build has
   *  never seen. The rail reports that rather than refusing to render. */
  status: string
  risk: string
  rail?: AsddActionRailContract | null
  actions: ReactNode
}

/**
 * The lifecycle strip and the buttons that move a change along it.
 *
 * The strip has two shapes on purpose. Seven labelled steps need roughly 380px
 * before the labels stop truncating, and the panel is regularly docked narrower
 * than that — where the full strip degraded into seven circles under seven
 * clipped words. Below that width it collapses to the same information stated
 * once: which step, of how many, and its name.
 */
export function AsddActionRail({ status, risk, rail, actions }: AsddActionRailProps) {
  const activeIndex = phaseOf(status)
  const phase = status as AsddStatus
  const primary = rail?.actions.find((action) => action.id === rail.primary_action)
  const blockers = primary?.blockers ?? []
  const problems = rail?.problems ?? []
  const designRequired = designApplies(risk, status)
  const autopilot = rail?.autopilot ?? false
  const hold = rail?.hold ?? null
  const done = status === 'archived'
  const reached = done ? ASDD_PHASES.length : activeIndex
  const percent = Math.round((reached / (ASDD_PHASES.length - 1)) * 100)

  return (
    <div className="border-t border-(--color-border) px-3 py-2.5 @xl/asdd:px-4">
      <div className="@md/asdd:hidden">
        <div className="flex items-baseline justify-between gap-2">
          <p className="truncate text-[11px] font-semibold text-(--color-text)">
            {done ? 'Archived' : ASDD_PHASES[activeIndex]}
          </p>
          <p className="shrink-0 text-[10px] text-(--color-text-subtle)">
            Step {Math.min(activeIndex + 1, ASDD_PHASES.length)} of {ASDD_PHASES.length}
          </p>
        </div>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-(--bg-key)">
          <div
            className={cn(
              'h-full rounded-full transition-[width]',
              done ? 'bg-(--color-success)' : 'bg-(--color-accent)',
            )}
            style={{ width: `${Math.max(percent, 4)}%` }}
          />
        </div>
      </div>

      <ol
        aria-label="ASDD lifecycle"
        className="hidden grid-cols-7 gap-1 @md/asdd:grid"
      >
        {ASDD_PHASES.map((phase, index) => {
          const skipped = !designRequired && index === 2
          const complete = activeIndex > index || done
          const active = activeIndex === index && !skipped && !done
          return (
            <li key={phase} className="min-w-0 text-center">
              <div className={cn(
                'mx-auto flex h-5 w-5 items-center justify-center rounded-full border text-[9px] font-semibold',
                complete && 'border-(--color-success) bg-(--color-success-subtle) text-(--color-success)',
                active && 'border-(--color-accent) bg-(--color-accent)/10 text-(--color-accent)',
                skipped && 'border-dashed border-(--color-border-strong) text-(--color-text-subtle)',
                !complete && !active && !skipped && 'border-(--color-border) text-(--color-text-subtle)',
              )}>
                {complete ? <Check size={10} /> : skipped ? '—' : index + 1}
              </div>
              <span className={cn(
                'mt-1 block truncate text-[9px] leading-3',
                active ? 'font-semibold text-(--color-accent)' : 'text-(--color-text-subtle)',
              )}>
                {skipped ? 'Skipped' : phase}
              </span>
            </li>
          )
        })}
      </ol>

      {hold && (
        // The agent stopped on purpose. Nothing else on the rail matters until
        // the reader has seen why, so it goes above the buttons rather than
        // under them with the other advisories.
        <div
          role="alert"
          className="mt-2.5 rounded-lg border border-(--color-accent)/40 bg-(--color-accent)/8 px-2.5 py-2"
        >
          <p className="flex items-center gap-1.5 text-[10px] font-semibold text-(--color-accent)">
            <PauseCircle size={11} />
            Autopilot stopped for you
            {hold.gate ? ` at the ${hold.gate} gate` : ''}
          </p>
          {hold.reason && (
            <p className="mt-1 text-[10px] leading-4 text-(--color-text-2)">{hold.reason}</p>
          )}
        </div>
      )}

      <div className="mt-2.5 flex flex-col gap-2 @2xl/asdd:flex-row @2xl/asdd:items-center @2xl/asdd:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] leading-4 text-(--color-text-subtle)">
            {(autopilot && !hold ? AUTOPILOT_MESSAGES[phase] : undefined)
              ?? PHASE_MESSAGES[phase]
              // A hand-edited status the build does not know. The rail's
              // `unknown_status` problem below says what is wrong with it.
              ?? `\`status: ${status}\` is not a phase this build knows.`}
          </p>
          {primary && (
            <p className="mt-0.5 text-[10px] font-medium text-(--color-text-2)">
              Next: {primary.label}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">{actions}</div>
      </div>

      {blockers.length > 0 && (
        <div role="alert" className="mt-2 rounded-lg border border-(--color-warning)/35 bg-(--color-warning)/8 px-2.5 py-2">
          <p className="flex items-center gap-1.5 text-[10px] font-semibold text-(--color-warning)">
            <AlertTriangle size={11} /> {primary?.label} is blocked
          </p>
          <ul className="mt-1 space-y-0.5 text-[10px] leading-4 text-(--color-text-muted)">
            {blockers.slice(0, 4).map((blocker, index) => (
              <li key={`${blocker.code}-${index}`}>{blocker.message}</li>
            ))}
            {blockers.length > 4 && <li>+{blockers.length - 4} more</li>}
          </ul>
        </div>
      )}

      {problems.length > 0 && (
        // The declared status disagrees with the folder. Neither side is
        // corrected automatically — the files are the source of truth, so the
        // user decides which one is wrong.
        <div role="alert" className="mt-2 rounded-lg border border-(--color-danger)/35 bg-(--color-danger)/8 px-2.5 py-2">
          <p className="flex items-center gap-1.5 text-[10px] font-semibold text-(--color-danger)">
            <AlertTriangle size={11} /> proposal.md disagrees with the change folder
          </p>
          <ul className="mt-1 space-y-0.5 text-[10px] leading-4 text-(--color-text-muted)">
            {problems.map((problem, index) => (
              <li key={`${problem.code}-${index}`}>{problem.message}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
