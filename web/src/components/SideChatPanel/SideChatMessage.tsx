/**
 * SideChatMessage — renders a single message in the side chat panel.
 *
 * User messages show as right-aligned bubbles.
 * Assistant messages render markdown content with tool calls.
 */
import { memo } from 'react'
import { LazyMarkdownBlock } from '@/utils/LazyMarkdownBlock'
import { ToolCall } from '../ToolCall'
import type { ContentBlock } from '@/api/types'

interface SideChatMessageProps {
  role: 'user' | 'assistant'
  content: string
  blocks: ContentBlock[]
  agent?: string | null
  timestamp?: Date
  isStreaming?: boolean
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export const SideChatMessage = memo(function SideChatMessage({
  role,
  content,
  blocks,
  agent,
  timestamp,
  isStreaming = false,
}: SideChatMessageProps) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-(--color-accent) px-3 py-2 text-sm text-white">
          <p className="whitespace-pre-wrap break-words">{content}</p>
        </div>
      </div>
    )
  }

  // Assistant message — render blocks
  return (
    <div className="flex flex-col gap-1">
      {agent && (
        <span className="text-[10px] font-medium text-(--color-text-muted)">{agent}</span>
      )}
      <div className="max-w-full overflow-hidden rounded-2xl rounded-bl-md bg-(--bg-card) px-3 py-2 text-sm text-(--color-text)">
        {blocks.length > 0
          ? blocks.map((block) => {
              switch (block.type) {
                case 'text':
                  return (
                    <div key={block.id} className="oa-prose text-sm">
                      <LazyMarkdownBlock
                        content={block.content}
                        isStreaming={isStreaming && block === blocks[blocks.length - 1]}
                      />
                    </div>
                  )
                case 'thinking':
                  return (
                    <details key={block.id} className="group mb-2">
                      <summary className="cursor-pointer text-xs text-(--color-text-muted) hover:text-(--color-text)">
                        Thinking…
                      </summary>
                      <div className="mt-1 whitespace-pre-wrap text-xs text-(--color-text-muted) italic">
                        {block.content}
                      </div>
                    </details>
                  )
                case 'tool':
                  return (
                    <ToolCall
                      key={block.id}
                      name={block.toolName || 'unknown'}
                      args={block.toolArgs}
                      done={block.toolDone}
                      result={block.toolResult}
                      liveOutput={block.toolOutput}
                      durationMs={block.durationMs}
                      startedAt={block.startedAt}
                    />
                  )
                default:
                  return null
              }
            })
          : content && (
              <div className="oa-prose text-sm">
                <LazyMarkdownBlock content={content} isStreaming={isStreaming} />
              </div>
            )}
      </div>
      {timestamp && (
        <span className="text-[10px] text-(--color-text-muted)">{formatTime(timestamp)}</span>
      )}
    </div>
  )
})
