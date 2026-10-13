import { useId, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SelectControl } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { UiFormBlock, UiFormField } from './ui-block-types'

/**
 * Free-text fields (text / textarea / default kind) are required; choice
 * widgets (select / checkbox) are optional (spec §5.4).
 */
function isFreeTextField(field: UiFormField): boolean {
  return field.kind === undefined || field.kind === 'text' || field.kind === 'textarea'
}

/**
 * Composes the send prompt from FILLED fields only (spec §5.4):
 * `${title ?? 'Form response'}` then `- label: value` per answered field.
 */
function composeFormPrompt(
  block: UiFormBlock,
  values: Record<string, string | boolean>,
): string {
  const lines: string[] = []
  for (const field of block.fields) {
    const raw = values[field.name]
    if (field.kind === 'checkbox') {
      if (raw === true || raw === 'on') lines.push(`- ${field.label}: yes`)
      continue
    }
    const value = typeof raw === 'string' ? raw.trim() : ''
    if (value) lines.push(`- ${field.label}: ${value}`)
  }
  return `${block.title || 'Form response'}:\n${lines.join('\n')}`
}

export function UiForm({
  block,
  onSendPrompt,
}: {
  block: UiFormBlock
  onSendPrompt: (prompt: string) => void
}) {
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(
      block.fields.map((f) => [f.name, f.default ?? (f.kind === 'checkbox' ? false : '')]),
    ),
  )

  // The model has no per-field `required` flag: free-text answers (text /
  // textarea) gate submit, while choice widgets (select / checkbox) are
  // optional — the composed prompt only includes FILLED fields (§5.4).
  const missingRequired = block.fields.some(
    (f) => isFreeTextField(f) && !String(values[f.name] ?? '').trim(),
  )
  const uid = useId()

  const setValue = (name: string, value: string | boolean) =>
    setValues((prev) => ({ ...prev, [name]: value }))

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (missingRequired) return
    onSendPrompt(composeFormPrompt(block, values))
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2" aria-label={block.title || 'Form'}>
      {block.title && <p className="text-sm font-medium">{block.title}</p>}
      {block.description && (
        <p className="text-xs text-(--color-text-muted)">{block.description}</p>
      )}
      {block.fields.map((field) => {
        const value = values[field.name]
        const required = isFreeTextField(field)
        const inputId = `${uid}${field.name}`
        const helperId = `${inputId}-helper`
        const describedBy = field.helper ? helperId : undefined
        return (
          <div key={field.name} className="space-y-1">
            <label
              htmlFor={inputId}
              className="block text-xs font-medium text-(--color-text-muted)"
            >
              {field.label}
              {required && (
                <span aria-hidden="true" className="text-(--color-error)">
                  {' *'}
                </span>
              )}
            </label>
            {field.helper && (
              <p id={helperId} className="text-[11px] text-(--color-text-muted)">
                {field.helper}
              </p>
            )}
            {field.kind === 'textarea' ? (
              <Textarea
                id={inputId}
                value={typeof value === 'string' ? value : ''}
                placeholder={field.placeholder ?? undefined}
                aria-required={required}
                aria-describedby={describedBy}
                onChange={(e) => setValue(field.name, e.target.value)}
              />
            ) : field.kind === 'select' ? (
              <SelectControl
                id={inputId}
                value={typeof value === 'string' && value ? value : null}
                onValueChange={(v) => setValue(field.name, v)}
                options={(field.options ?? []).map((option) => ({
                  value: option,
                  label: option,
                }))}
                placeholder={field.placeholder || 'Select…'}
                ariaLabel={field.label}
                size="sm"
              />
            ) : field.kind === 'checkbox' ? (
              <input
                id={inputId}
                type="checkbox"
                checked={value === true || value === 'on'}
                aria-describedby={describedBy}
                onChange={(e) => setValue(field.name, e.target.checked)}
              />
            ) : (
              <Input
                id={inputId}
                value={typeof value === 'string' ? value : ''}
                placeholder={field.placeholder ?? undefined}
                aria-required={required}
                aria-describedby={describedBy}
                onChange={(e) => setValue(field.name, e.target.value)}
              />
            )}
          </div>
        )
      })}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={missingRequired}>
          {block.submit_label || 'Send'}
        </Button>
        {missingRequired && (
          <p className="text-xs text-(--color-text-muted)">
            Fill in the required (*) fields to send.
          </p>
        )}
      </div>
    </form>
  )
}
