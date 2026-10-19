import { useState } from 'react'
import type { UiChecklistBlock } from './ui-block-types'

/**
 * Interactive checklist (Intelligent UI showcase) — per-item tick state
 * stays local to the viewer (it is never sent back to the agent) and the
 * header shows a live "N of M done" counter with a thin progress bar.
 */
export function UiChecklist({ block }: { block: UiChecklistBlock }) {
  const [checked, setChecked] = useState<boolean[]>(() =>
    block.items.map((item) => item.checked ?? false),
  )
  const done = checked.filter(Boolean).length
  const total = block.items.length

  const toggle = (index: number) => {
    setChecked((prev) => prev.map((value, i) => (i === index ? !value : value)))
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
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-xs tabular-nums text-(--color-text-muted)" aria-live="polite">
          {done} of {total} done
        </p>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label="Checklist progress"
        className="mt-1 h-1 w-full overflow-hidden rounded-full bg-(--bg-key)"
      >
        <div
          className="h-1 rounded-full bg-(--color-accent) transition-[width] duration-300 motion-reduce:transition-none"
          style={{ width: `${total === 0 ? 0 : (done / total) * 100}%` }}
        />
      </div>
      <ul className="mt-2 space-y-1.5">
        {block.items.map((item, i) => (
          <li key={`${item.label}-${i}`} className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={checked[i]}
              onChange={() => toggle(i)}
              aria-label={item.label}
              className="mt-0.5 size-4 shrink-0 cursor-pointer accent-(--color-accent)"
            />
            <span className="min-w-0">
              <span
                className={`block text-sm whitespace-pre-wrap ${
                  checked[i]
                    ? 'text-(--color-text-muted) line-through'
                    : 'text-(--color-text)'
                }`}
              >
                {item.label}
              </span>
              {item.detail && (
                <span
                  className={`block text-xs ${
                    checked[i]
                      ? 'text-(--color-text-muted) line-through'
                      : 'text-(--color-text-muted)'
                  }`}
                >
                  {item.detail}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
