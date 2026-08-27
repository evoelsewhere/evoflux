import type { ReactNode } from 'react'
import { AlertTriangle, Check } from 'lucide-react'

import type { EasdActionRail as EasdActionRailContract, EasdDeliveryMode, EasdRun } from '@/api/types'
import { cn } from '@/lib/utils'

const PHASE_MESSAGES: Partial<Record<EasdRun['status'], string>> = {
  intent: 'Intent is ready; no specification exists yet.',
  authoring: 'The lead is drafting the specification. Product files remain read-only.',
  draft: 'Review and approve the persisted specification before planning.',
  accepted: 'The specification and its driven flow are accepted; start the persisted next action.',
  planning: 'The lead is compiling the accepted specification into a typed plan.',
  plan_review: 'Review and approve the persisted plan before implementation.',
  planned: 'The accepted specification and plan are ready for implementation.',
  active: 'Implementation is active; Review remains a separate user-controlled phase.',
  reviewing: 'Review is active and read-only; passing review evidence unlocks Verify.',
  verifying: 'Final verification is active; only the server Converge gate can decide Done.',
}

const STEP_INDEX: Record<EasdRun['status'], number> = {
  intent: 0,
  authoring: 1,
  draft: 1,
  accepted: 2,
  planning: 2,
  plan_review: 2,
  planned: 2,
  active: 3,
  reviewing: 4,
  verifying: 5,
  converged: 6,
  failed: -1,
  cancelled: -1,
}

interface EasdActionRailProps {
  status: EasdRun['status']
  deliveryMode: EasdDeliveryMode
  rail?: EasdActionRailContract | null
  actions: ReactNode
}

export function EasdActionRail({ status, deliveryMode, rail, actions }: EasdActionRailProps) {
  const activeIndex = STEP_INDEX[status]
  const primary = rail?.actions.find((action) => action.id === rail.primary_action)
  const blockers = primary?.blockers ?? []
  const steps = [
    { label: 'Intent' },
    { label: 'Spec' },
    { label: deliveryMode === 'direct' ? 'Plan skipped' : 'Plan' },
    { label: 'Implement' },
    { label: 'Review' },
    { label: 'Verify' },
    { label: 'Done' },
  ]

  return (
    <div className="border-t border-(--color-border) px-3 py-2.5 @xl/easd:px-4">
      <ol aria-label="EASD lifecycle" className="grid grid-cols-7 gap-1">
        {steps.map((step, index) => {
          const skipped = deliveryMode === 'direct' && index === 2
          const complete = activeIndex > index || status === 'converged'
          const active = activeIndex === index && !skipped
          return (
            <li key={step.label} className="min-w-0 text-center">
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
                'mt-1 block truncate text-[8px] leading-3',
                active ? 'font-semibold text-(--color-accent)' : 'text-(--color-text-subtle)',
              )}>{step.label}</span>
            </li>
          )
        })}
      </ol>

      <div className="mt-2.5 flex flex-col gap-2 @2xl/easd:flex-row @2xl/easd:items-center @2xl/easd:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] leading-4 text-(--color-text-subtle)">
            {PHASE_MESSAGES[status] ?? `This Run is ${status}.`}
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
            {blockers.slice(0, 3).map((blocker, index) => (
              <li key={`${blocker.code}-${blocker.mission_id ?? blocker.criterion_id ?? index}`}>
                {blocker.message}
              </li>
            ))}
            {blockers.length > 3 && <li>+{blockers.length - 3} more blockers</li>}
          </ul>
        </div>
      )}
    </div>
  )
}
