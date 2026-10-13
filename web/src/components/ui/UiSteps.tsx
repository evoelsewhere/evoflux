import { AlertCircle, CheckCircle2, Circle, Loader2 } from 'lucide-react'
import type { UiStepsBlock, UiStep } from './ui-block-types'

/** Word shown next to each step so the list reads like a guided sequence. */
const STATUS_WORD: Record<NonNullable<UiStep['status']>, string> = {
  done: 'Done',
  active: 'Now',
  pending: 'Next',
  error: 'Blocked',
}

function stepIcon(status?: UiStep['status']) {
  switch (status) {
    case 'done':
      return <CheckCircle2 size={16} className="text-(--color-success)" aria-hidden />
    case 'active':
      return <Loader2 size={16} className="animate-spin text-(--color-accent)" aria-hidden />
    case 'error':
      return <AlertCircle size={16} className="text-(--color-error)" aria-hidden />
    default:
      return <Circle size={16} className="text-(--color-text-muted)" aria-hidden />
  }
}

export function UiSteps({ block }: { block: UiStepsBlock }) {
  return (
    <div>
      {block.description && (
        <p className="mb-2 text-xs text-(--color-text-muted)">{block.description}</p>
      )}
      <ol className="space-y-2" aria-label="Steps">
        {block.steps.map((step, i) => (
          <li key={`${step.title}-${i}`} className="flex items-start gap-2">
            <span className="mt-0.5">{stepIcon(step.status)}</span>
            <span className="min-w-0">
              <span className="flex items-baseline gap-1.5">
                <span
                  className={
                    step.status === 'active'
                      ? 'block text-sm font-semibold'
                      : 'block text-sm'
                  }
                >
                  {step.title}
                </span>
                <span className="text-[11px] text-(--color-text-muted)">
                  {step.status ? STATUS_WORD[step.status] : STATUS_WORD.pending}
                </span>
              </span>
              {step.detail && (
                <span className="block text-xs text-(--color-text-muted)">{step.detail}</span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
