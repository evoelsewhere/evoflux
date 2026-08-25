import { cn } from '@/lib/utils'

export interface SpecificationDiffField {
  label: string
  current: string
  proposed: string
}

function displayValue(value: string): string {
  return value.trim() || '(empty)'
}

function changedSpecificationFields(
  fields: SpecificationDiffField[],
): SpecificationDiffField[] {
  return fields.filter(
    (field) => displayValue(field.current) !== displayValue(field.proposed),
  )
}

export function SpecificationDiff({
  fields,
  className,
}: {
  fields: SpecificationDiffField[]
  className?: string
}) {
  const changed = changedSpecificationFields(fields)
  if (!changed.length) {
    return (
      <p className={cn('rounded-lg bg-(--bg-key)/45 p-2.5 text-[10px] text-(--color-text-subtle)', className)}>
        No field-level changes in this section.
      </p>
    )
  }

  return (
    <div className={cn('space-y-2', className)}>
      <p className="text-[10px] font-medium text-(--color-text-muted)">
        {changed.length} changed {changed.length === 1 ? 'field' : 'fields'} · exact before/after
      </p>
      {changed.map((field) => (
        <details key={field.label} className="overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-page)/55" open={changed.length <= 2}>
          <summary className="cursor-pointer px-2.5 py-2 text-[10px] font-semibold text-(--color-text-2)">
            {field.label}
          </summary>
          <div className="grid border-t border-(--color-border) @2xl/easd:grid-cols-2">
            <div className="min-w-0 border-b border-(--color-border) bg-(--color-error)/5 p-2.5 @2xl/easd:border-b-0 @2xl/easd:border-r">
              <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-(--color-error)">− Current</p>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words font-sans text-[10px] leading-4 text-(--color-text-muted)">{displayValue(field.current)}</pre>
            </div>
            <div className="min-w-0 bg-(--color-success)/5 p-2.5">
              <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-(--color-success)">+ Proposed</p>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words font-sans text-[10px] leading-4 text-(--color-text-2)">{displayValue(field.proposed)}</pre>
            </div>
          </div>
        </details>
      ))}
    </div>
  )
}
