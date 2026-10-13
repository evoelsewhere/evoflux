import { useMemo, useState } from 'react'
import type { UiCalculatorBlock, UiCalculatorInput } from './ui-block-types'
import { evaluateFormula } from './safe-formula'

/**
 * Live calculator (Intelligent UI showcase) — number inputs with − / +
 * steppers whose outputs recompute on every keystroke via the hand-rolled
 * safe arithmetic parser (`safe-formula.ts`, no eval/Function). An invalid
 * formula surfaces as an inline error on that output row.
 */
export function UiCalculator({ block }: { block: UiCalculatorBlock }) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(block.inputs.map((input) => [input.name, String(input.value)])),
  )

  const numbers = useMemo(() => {
    const out: Record<string, number> = {}
    for (const input of block.inputs) {
      const parsed = Number(values[input.name])
      out[input.name] = Number.isFinite(parsed) ? parsed : Number.NaN
    }
    return out
  }, [block.inputs, values])

  const clamp = (input: UiCalculatorInput, value: number): number => {
    let next = value
    if (input.min != null && next < input.min) next = input.min
    if (input.max != null && next > input.max) next = input.max
    return next
  }

  const step = (input: UiCalculatorInput, direction: 1 | -1) => {
    const current = Number(values[input.name]) || 0
    const increment = (input.step ?? 1) * direction
    const next = clamp(input, current + increment)
    // Avoid float drift like 0.30000000000000004 when stepping by 0.1.
    setValues((prev) => ({ ...prev, [input.name]: String(Number(next.toFixed(10))) }))
  }

  return (
    <div className="rounded-md border border-(--color-border) bg-(--bg-card) p-3">
      {block.title && (
        <p className="text-sm font-medium text-(--color-text)">{block.title}</p>
      )}
      {block.description && (
        <p className="mt-0.5 text-xs whitespace-pre-wrap text-(--color-text-muted)">
          {block.description}
        </p>
      )}
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {block.inputs.map((input) => (
          <div key={input.name} className="flex flex-col gap-1 text-xs">
            <span className="text-(--color-text-muted)">
              {input.label}
              {input.unit && <span className="ml-1">({input.unit})</span>}
            </span>
            <span className="flex items-center gap-1">
              <button
                type="button"
                aria-label={`Decrease ${input.label}`}
                onClick={() => step(input, -1)}
                className="inline-flex size-7 shrink-0 items-center justify-center rounded-sm border border-(--color-border) text-(--color-text-muted) transition-colors hover:bg-(--bg-key)"
              >
                −
              </button>
              <input
                type="number"
                inputMode="decimal"
                aria-label={`${input.label}${input.unit ? ` (${input.unit})` : ''}`}
                value={values[input.name]}
                min={input.min ?? undefined}
                max={input.max ?? undefined}
                step={input.step ?? undefined}
                onChange={(event) => {
                  const raw = event.target.value
                  setValues((prev) => ({ ...prev, [input.name]: raw }))
                }}
                onBlur={(event) => {
                  const parsed = Number(event.target.value)
                  if (event.target.value === '' || !Number.isFinite(parsed)) {
                    setValues((prev) => ({ ...prev, [input.name]: String(input.value) }))
                  } else {
                    setValues((prev) => ({
                      ...prev,
                      [input.name]: String(clamp(input, parsed)),
                    }))
                  }
                }}
                className="h-7 w-full min-w-0 rounded-sm border border-(--color-border) bg-(--bg-page) px-2 text-sm tabular-nums text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
              />
              <button
                type="button"
                aria-label={`Increase ${input.label}`}
                onClick={() => step(input, 1)}
                className="inline-flex size-7 shrink-0 items-center justify-center rounded-sm border border-(--color-border) text-(--color-text-muted) transition-colors hover:bg-(--bg-key)"
              >
                +
              </button>
            </span>
          </div>
        ))}
      </div>
      <dl className="mt-3 space-y-1.5 border-t border-(--color-border) pt-2">
        {block.outputs.map((output) => {
          const result = evaluateFormula(output.formula, numbers)
          const formatted =
            result.ok && result.value !== undefined
              ? result.value.toFixed(output.decimals ?? 2)
              : null
          return (
            <div
              key={`${output.label}-${output.formula}`}
              className="flex items-baseline justify-between gap-2"
            >
              <dt className="text-xs text-(--color-text-muted)">{output.label}</dt>
              {formatted !== null ? (
                <dd className="text-sm font-medium tabular-nums text-(--color-text)">
                  {formatted}
                  {output.unit && (
                    <span className="ml-1 text-xs font-normal text-(--color-text-muted)">
                      {output.unit}
                    </span>
                  )}
                </dd>
              ) : (
                <dd role="alert" className="text-xs text-(--color-error)">
                  {result.error}
                </dd>
              )}
            </div>
          )
        })}
      </dl>
    </div>
  )
}
