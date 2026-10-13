import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SelectControl } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { UiFormBlock } from './ui-block-types'

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
    (f) =>
      (f.kind === 'text' || f.kind === 'textarea' || f.kind === undefined) &&
      !String(values[f.name] ?? '').trim(),
  )

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
      {block.fields.map((field) => {
        const value = values[field.name]
        return (
          <label key={field.name} className="block space-y-1">
            <span className="text-xs font-medium text-(--color-text-muted)">
              {field.label}
            </span>
            {field.kind === 'textarea' ? (
              <Textarea
                value={typeof value === 'string' ? value : ''}
                placeholder={field.placeholder ?? undefined}
                onChange={(e) => setValue(field.name, e.target.value)}
              />
            ) : field.kind === 'select' ? (
              <SelectControl
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
                type="checkbox"
                checked={value === true || value === 'on'}
                onChange={(e) => setValue(field.name, e.target.checked)}
              />
            ) : (
              <Input
                value={typeof value === 'string' ? value : ''}
                placeholder={field.placeholder ?? undefined}
                onChange={(e) => setValue(field.name, e.target.value)}
              />
            )}
          </label>
        )
      })}
      <Button type="submit" size="sm" disabled={missingRequired}>
        {block.submit_label || 'Send'}
      </Button>
    </form>
  )
}
