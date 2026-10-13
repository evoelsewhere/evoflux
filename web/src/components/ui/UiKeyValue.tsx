import type { UiKeyValueBlock } from './ui-block-types'

export function UiKeyValue({ block }: { block: UiKeyValueBlock }) {
  return (
    <dl className="divide-y divide-(--color-border) rounded-md border border-(--color-border)">
      {block.pairs.map((pair, i) =>
        Object.entries(pair).map(([label, value]) => (
          <div
            key={`${label}-${i}`}
            className="flex items-baseline justify-between gap-3 px-3 py-1.5"
          >
            <dt className="shrink-0 text-xs text-(--color-text-muted)">{label}</dt>
            <dd className="min-w-0 truncate text-right text-sm tabular-nums">{value}</dd>
          </div>
        )),
      )}
    </dl>
  )
}
