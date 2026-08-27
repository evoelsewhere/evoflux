import { Route } from 'lucide-react'

import { EasdTechnicalText } from '@/components/easd/EasdTechnicalText'
import { parseEasdChatMessage } from '@/utils/easd-chat-message'

export function EasdChatMessage({ content }: { content: string }) {
  const parsed = parseEasdChatMessage(content)
  if (!parsed) return null
  return (
    <div data-easd-chat-message className="min-w-0">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 rounded-full bg-(--color-accent)/10 px-2 py-1 text-[10px] font-semibold text-(--color-accent)">
          <Route size={11} aria-hidden="true" /> EASD · {parsed.phase}
        </span>
        <code className="font-mono text-[10px] text-(--color-text-subtle)">{parsed.directive}</code>
      </div>
      <p className="min-w-0 break-words whitespace-pre-wrap text-(--color-text-2) [overflow-wrap:anywhere]">
        <EasdTechnicalText text={parsed.body} />
      </p>
    </div>
  )
}
