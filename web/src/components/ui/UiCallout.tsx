import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import type { UiCalloutBlock } from './ui-block-types'

const TONES = {
  info: {
    icon: Info,
    cls: 'border-(--color-info) bg-(--color-info-subtle) text-(--color-info)',
  },
  success: {
    icon: CheckCircle2,
    cls: 'border-(--color-success) bg-(--color-success-subtle) text-(--color-success)',
  },
  warning: {
    icon: AlertTriangle,
    cls: 'border-(--color-warning) bg-(--color-warning-subtle) text-(--color-warning)',
  },
  error: {
    icon: XCircle,
    cls: 'border-(--color-error) bg-(--color-error-subtle) text-(--color-error)',
  },
} as const

export function UiCallout({ block }: { block: UiCalloutBlock }) {
  const tone = TONES[block.tone ?? 'info']
  const Icon = tone.icon
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 ${tone.cls}`} role="note">
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0">
        {block.title && <p className="text-sm font-medium">{block.title}</p>}
        <p className="text-sm whitespace-pre-wrap">{block.body}</p>
      </div>
    </div>
  )
}
