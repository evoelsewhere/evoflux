/**
 * BlockRenderer — shared ContentBlock → React dispatch used by the main chat
 * transcript (`AgentView`) and the Side Chat panel.
 *
 *   - type:'user'     → user bubble (mention-highlighted, attachments, revert)
 *   - type:'thinking' → collapsible thinking block
 *   - type:'tool'     → tool call card (+ MCP app result)
 *   - type:'text'     → markdown prose
 *   - type:'compaction' / 'provider_status' / 'widget' → their dedicated views
 *
 * Extracted from `AgentView.tsx` so side surfaces render streamed content
 * identically to the main chat instead of re-implementing a subset.
 */

import { memo, useState } from 'react'
import { ChevronDown, ChevronUp, Copy, Check, Undo2, Terminal, Quote } from 'lucide-react'
import { LazyMarkdownBlock } from '@/utils/LazyMarkdownBlock'
import { Thinking } from './Thinking'
import { ToolCall } from './ToolCall'
import { MCPAppResult } from './MCPAppResult'
import { WidgetRenderer } from './WidgetRenderer'
import { InboxBubble } from './InboxBubble'
import { HandoffCard } from './HandoffCard'
import { CompactionDivider } from './CompactionDivider'
import { ImageAttachment } from './ImageAttachment'
import { FileCard } from './FileCard'
import { extractSleepPrefix, formatTime } from '@/utils/format'
import { findCommittedMentions } from './InputBar.mentions'
import { resolveApiUrl } from '@/api/client'
import type { ContentBlock, MessageAttachment } from '@/api/types'

const USER_COLLAPSE_LINES = 10
const USER_COLLAPSE_CHARS = 700

function shortModelName(modelId: string | null | undefined): string | null {
  if (!modelId) return null
  return modelId.split(':').at(-1)?.split('/').at(-1) || modelId
}

/**
 * Render user prose with ``@mention`` tokens syntax-highlighted.
 *
 * Matches the InputBar's overlay convention so a message looks the same
 * after send as it did while composing:
 *   - folders (token ends in ``/``)      → ``--accent-orange-text``
 *   - files (everything else, default)   → ``--accent-blue-text``
 *
 * The slash heuristic is what the picker inserts; using it (rather than
 * resolving against ``fileRefs``) keeps highlighting stable for old
 * messages whose referenced paths may since have been renamed/removed.
 * ``findCommittedMentions`` without refs falls back to syntax-only range
 * detection — same code path the overlay relies on.
 */
function renderMentionSegments(content: string): React.ReactNode[] {
  const ranges = findCommittedMentions(content, null)
  if (ranges.length === 0) return [content]
  const out: React.ReactNode[] = []
  let cursor = 0
  for (const r of ranges) {
    if (r.start > cursor) out.push(content.slice(cursor, r.start))
    const token = content.slice(r.start, r.end)
    const isFolder = token.endsWith('/')
    out.push(
      <span
        key={r.start}
        data-mention-kind={isFolder ? 'directory' : 'file'}
        className={
          isFolder ? 'text-(--accent-orange-text)' : 'text-(--accent-blue-text)'
        }
      >
        {token}
      </span>,
    )
    cursor = r.end
  }
  if (cursor < content.length) out.push(content.slice(cursor))
  return out
}

function splitLeadingQuote(content: string): { quote: string; message: string } | null {
  const lines = content.split('\n')
  const quoteLines: string[] = []
  let index = 0

  while (index < lines.length && (lines[index] === '>' || lines[index].startsWith('> '))) {
    quoteLines.push(lines[index] === '>' ? '' : lines[index].slice(2))
    index += 1
  }

  if (quoteLines.length === 0 || lines[index] !== '') return null
  const message = lines.slice(index + 1).join('\n').trimStart()
  if (!message) return null
  return { quote: quoteLines.join('\n'), message }
}

function UserBubble({ content, timestamp, attachments, onRevert, modelId, shell, renderLeadingQuoteAsContext }: { content: string; timestamp?: Date; attachments?: MessageAttachment[]; onRevert?: () => void; modelId?: string | null; shell?: boolean; renderLeadingQuoteAsContext?: boolean }) {
  const [showTime, setShowTime] = useState(false)
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const modelName = shortModelName(modelId)
  const quotedContext = renderLeadingQuoteAsContext ? splitLeadingQuote(content) : null
  const messageContent = quotedContext?.message ?? content

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }

  const lines = messageContent.split('\n')
  const needsCollapse = lines.length > USER_COLLAPSE_LINES || messageContent.length > USER_COLLAPSE_CHARS
  const visibleContent = needsCollapse && !expanded
    ? lines.length > USER_COLLAPSE_LINES
      ? lines.slice(0, USER_COLLAPSE_LINES).join('\n')
      : `${messageContent.slice(0, USER_COLLAPSE_CHARS).trimEnd()}...`
    : messageContent

  return (
    <div
      className="group mb-4 flex justify-end"
      onMouseEnter={() => setShowTime(true)}
      onMouseLeave={() => setShowTime(false)}
    >
      <div className="flex max-w-full flex-col items-end gap-2 md:max-w-[78%]">
         {/* Attachments */}
         {attachments && attachments.length > 0 && (
           <div className="flex flex-wrap justify-end gap-2">
             {attachments.map((att: MessageAttachment, idx: number) => {
               const isImage = att.category === 'image'

               if (isImage) {
                 return (
                   <ImageAttachment
                     key={idx}
                     src={resolveApiUrl(att.url) || ''}
                     alt={att.original_name || `Attachment ${idx + 1}`}
                   />
                 )
               }

               return (
                 <FileCard
                   key={idx}
                   name={att.original_name || att.filename || `File ${idx + 1}`}
                   mediaType={att.media_type}
                   url={resolveApiUrl(att.url)}
                   clickable={!!att.url}
                 />
               )
             })}
           </div>
         )}

          <div className={`relative min-w-0 max-w-full overflow-hidden rounded-2xl border px-4 py-3 text-sm leading-relaxed text-(--color-text) ${shell ? 'border-(--accent-blue)/30 bg-(--bg-key)' : 'border-(--color-border-subtle) bg-(--bg-key)'}`}>
           {/* Expand / collapse button — top-right inside bubble */}
           {needsCollapse && (
             <button
               onClick={() => setExpanded((v) => !v)}
               aria-expanded={expanded}
               title={expanded ? 'Collapse' : 'Expand'}
               className="absolute top-1.5 right-1.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-2) transition-all duration-150 hover:text-(--color-text) active:scale-90"
             >
               {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
             </button>
           )}
           {shell && (
             <div className="mb-1.5 flex items-center gap-1 font-mono text-xs text-(--color-text-muted)">
               <Terminal size={12} aria-hidden="true" />
               <span>Shell</span>
             </div>
           )}
           {quotedContext && (
             <div className="mb-2.5 border-b border-(--color-border) pb-2.5">
               <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-(--color-text-muted)">
                 <Quote size={11} aria-hidden="true" />
                 <span>Selected from main chat</span>
               </div>
               <p
                 className="line-clamp-3 min-w-0 text-xs leading-relaxed break-words whitespace-pre-wrap text-(--color-text-2) [overflow-wrap:anywhere]"
                 title={quotedContext.quote}
               >
                 {renderMentionSegments(quotedContext.quote)}
               </p>
             </div>
           )}
           <p className={`min-w-0 break-words whitespace-pre-wrap [overflow-wrap:anywhere] ${shell ? 'font-mono' : ''}`}>{renderMentionSegments(visibleContent)}</p>
           {/* Gradient fade at bottom when collapsed */}
           {needsCollapse && !expanded && (
             <div
                className="pointer-events-none absolute inset-x-0 bottom-0 backdrop-blur-[1px]"
               style={{
                 height: '2.4rem',
                 background: 'linear-gradient(to bottom, transparent 0%, var(--color-surface) 90%)',
               }}
             />
           )}
         </div>

         {/* Copy button + timestamp row */}
          {(timestamp || modelName) && (
            <div className={`flex items-center gap-1.5 transition-opacity duration-150 ${showTime ? 'opacity-100' : 'opacity-0'}`}>
              {modelName && (
                <span className="mr-1 font-mono text-xs text-(--color-text-subtle)" title={modelId ?? undefined}>
                  {modelName}
                </span>
              )}
               {onRevert && (
                <button
                  onClick={onRevert}
                  className="rounded-xs p-0.5 text-(--color-text-muted) transition-colors hover:text-(--color-text-2)"
                  aria-label="Revert latest message"
                  title="Revert latest message"
                >
                  <Undo2 size={11} />
                </button>
              )}
              <button
                onClick={handleCopy}
                className="rounded-xs p-0.5 text-(--color-text-muted) transition-colors hover:text-(--color-text-2)"
               aria-label="Copy message"
               title="Copy"
             >
               {copied ? (
                 <Check size={11} className="text-(--color-success)" />
               ) : (
                 <Copy size={11} />
               )}
             </button>
              {timestamp && (
                <span
                  className="text-xs text-(--color-text-subtle)"
                  aria-hidden={!showTime}
                  title={formatTime(timestamp)}
                >
                  {formatTime(timestamp)}
                </span>
              )}
            </div>
          )}
      </div>
    </div>
  )
}


export interface BlockRendererProps {
  block: ContentBlock
  isStreaming: boolean
  sessionId?: string
  onRevert?: () => void
  latestMCPAppBlockIds?: Set<string>
  renderLeadingQuoteAsContext?: boolean
}

export const BlockRenderer = memo(function BlockRenderer({ block, isStreaming, sessionId, onRevert, latestMCPAppBlockIds, renderLeadingQuoteAsContext }: BlockRendererProps) {
  switch (block.type) {
    case 'user': {
      // Me check if this is an inbox message (from another agent, not real user)
      const fromAgent = block.extra?.from_agent as string | undefined
      if (fromAgent && fromAgent !== 'user') {
        const handoffArtifact = block.extra?._handoff_artifact as Record<string, unknown> | undefined
        if (handoffArtifact) {
          return <HandoffCard artifact={handoffArtifact as never} fromAgent={fromAgent} />
        }
        return <InboxBubble content={block.content} fromAgent={fromAgent} />
      }
      const blockModel = typeof block.extra?.model === 'string' ? block.extra.model : null
      const shell = block.extra?.kind === 'user_shell'
      return <UserBubble content={block.content} timestamp={block.timestamp} attachments={block.attachments} onRevert={onRevert} modelId={blockModel} shell={shell} renderLeadingQuoteAsContext={renderLeadingQuoteAsContext} />
    }
    case 'thinking':
      return <Thinking content={block.content} isStreaming={isStreaming} />
    case 'compaction': {
      const state = block.extra?.state === 'compacting' ? 'compacting' : 'compacted'
      const error = Boolean(block.extra?.error)
      return (
        <CompactionDivider
          state={state}
          error={error}
          summary={block.content}
          sessionId={sessionId}
        />
      )
    }
    case 'provider_status': {
      const status = block.extra?.status
      const model = block.extra?.model
      const primary = block.extra?.primary
      const fallback = block.extra?.fallback
      const attempt = block.extra?.attempt
      const maxAttempts = block.extra?.max_attempts
      const delay = block.extra?.delay_seconds
      const errorType = block.extra?.error_type
      const statusCode = block.extra?.status_code
      let message = 'Provider status updated.'
      if (status === 'fallback') {
        message = `Switching model from ${String(primary ?? 'primary')} to ${String(fallback ?? 'fallback')}.`
      } else if (status === 'retrying') {
        const delayText = typeof delay === 'number' ? ` Waiting ${delay.toFixed(1)}s.` : ''
        const errorText = errorType ? ` after ${String(errorType)}${statusCode ? ` ${String(statusCode)}` : ''}` : ''
        message = `Retrying ${String(model ?? 'model')} (${String(attempt ?? '?')}/${String(maxAttempts ?? '?')})${errorText}.${delayText}`
      } else if (status === 'exhausted') {
        const errorText = errorType ? ` after ${String(errorType)}${statusCode ? ` ${String(statusCode)}` : ''}` : ''
        message = `${String(model ?? 'Model')} exhausted retry attempts${errorText}.`
      }
      return <p className="rounded-md border border-(--color-border) bg-(--bg-muted) px-3 py-2 text-xs text-(--color-text-muted)">{message}</p>
    }
    case 'tool': {
      const mcpApp = (block.extra as { mcp_app?: unknown } | undefined)?.mcp_app
      return (
        <div>
          <ToolCall
            name={block.toolName || ''}
            args={block.toolArgs}
            done={block.toolDone}
            liveOutput={block.toolOutput}
            result={block.toolResult}
            durationMs={block.durationMs}
            startedAt={block.startedAt}
          />
          {block.toolDone && Boolean(mcpApp) && latestMCPAppBlockIds?.has(block.id) ? (
            <div className="mt-2">
              <MCPAppResult mcpApp={mcpApp as never} sessionId={sessionId} toolCallId={block.toolCallId} />
            </div>
          ) : null}
        </div>
      )
    }
    case 'widget': {
      const widgetHtml = block.widgetHtml || ''
      const isStreaming = block.isStreaming ?? false
      const title = block.title || 'Widget'
      return (
        <div className="my-2">
          <WidgetRenderer
            html={widgetHtml}
            isStreaming={isStreaming}
            title={title}
            sessionId={sessionId}
          />
        </div>
      )
    }
    case 'text': {
      // Me sleep sentinel — show any preceding content normally, then append idle pill
      const sleepPrefix = extractSleepPrefix(block.content)
      if (sleepPrefix !== null) {
        return (
          <div>
            {sleepPrefix && <LazyMarkdownBlock content={sleepPrefix} sessionId={sessionId} isStreaming={isStreaming} />}
            <p className="text-xs text-(--color-text-subtle) italic">— idle —</p>
    </div>
  )
}

      return (
        <div>
          <LazyMarkdownBlock content={block.content} sessionId={sessionId} isStreaming={isStreaming} />
        </div>
      )
    }
    default:
      return null
  }
})
