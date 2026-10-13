import { AlertCircle, CheckCircle2, Circle, Loader2 } from 'lucide-react'
import type { UiStepsBlock, UiStep } from './ui-block-types'

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
    <ol className="space-y-2" aria-label="Steps">
      {block.steps.map((step, i) => (
        <li key={`${step.title}-${i}`} className="flex items-start gap-2">
          <span className="mt-0.5">{stepIcon(step.status)}</span>
          <span className="min-w-0">
            <span className="block text-sm">{step.title}</span>
            {step.detail && (
              <span className="block text-xs text-(--color-text-muted)">{step.detail}</span>
            )}
          </span>
        </li>
      ))}
    </ol>
  )
}
