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
    <div className="flex flex-wrap gap-2">
      {block.buttons.map((button, i) => (
        <Button
          key={`${button.label}-${i}`}
          size="sm"
          variant={button.style === 'secondary' ? 'outline' : 'default'}
          onClick={() => onSendPrompt(button.prompt)}
        >
          {button.label}
        </Button>
      ))}
    </div>
  )
}
