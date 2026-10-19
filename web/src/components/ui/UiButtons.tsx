import { Button } from '@/components/ui/button'
import type { UiButtonsBlock } from './ui-block-types'

export function UiButtons({
  block,
  onSendPrompt,
}: {
  block: UiButtonsBlock
  onSendPrompt: (prompt: string) => void
}) {
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {block.buttons.map((button, i) => (
          <Button
            key={`${button.label}-${i}`}
            size="sm"
            variant={button.style === 'secondary' ? 'outline' : 'default'}
            aria-label={`${button.label} — sends this message to the agent`}
            onClick={() => onSendPrompt(button.prompt)}
          >
            {button.label}
          </Button>
        ))}
      </div>
      {block.hint && (
        <p className="mt-1.5 text-xs text-(--color-text-muted)">{block.hint}</p>
      )}
    </div>
  )
}
