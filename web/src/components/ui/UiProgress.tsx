import type { UiProgressBlock } from './ui-block-types'

export function UiProgress({ block, live }: { block: UiProgressBlock; live?: boolean }) {
  const pct = Math.max(0, Math.min(100, Math.round((block.value / block.max) * 100)))
  return (
    <div
      className="space-y-1"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={block.max}
      aria-valuenow={block.value}
      aria-label={block.label}
      aria-live={live ? 'polite' : undefined}
    >
      <div className="flex items-baseline justify-between text-xs">
        <span className="truncate text-(--color-text-muted)">{block.label}</span>
        <span className="tabular-nums">
          {block.value}/{block.max}
          {block.unit ? ` ${block.unit}` : ''}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-(--color-border)">
        <div
          className="h-full rounded-full bg-(--color-accent) transition-[width] duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
