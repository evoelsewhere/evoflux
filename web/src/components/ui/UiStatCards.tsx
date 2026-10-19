import { Card, CardContent } from '@/components/ui/card'
import type { UiStatCardsBlock } from './ui-block-types'

function deltaClass(tone?: 'up' | 'down' | 'neutral'): string {
  if (tone === 'up') return 'text-(--color-success)'
  if (tone === 'down') return 'text-(--color-error)'
  return 'text-(--color-text-muted)'
}

export function UiStatCards({ block }: { block: UiStatCardsBlock }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {block.cards.map((card, i) => (
        <Card key={`${card.label}-${i}`} className="py-2">
          <CardContent className="px-3">
            <p className="truncate text-xs text-(--color-text-muted)">{card.label}</p>
            <p className="text-lg font-semibold tabular-nums">{card.value}</p>
            {card.delta != null && (
              <p className={`text-xs tabular-nums ${deltaClass(card.delta_tone)}`}>
                {card.delta}
              </p>
            )}
            {card.hint && (
              <p className="mt-0.5 truncate text-[11px] text-(--color-text-muted)">
                {card.hint}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
