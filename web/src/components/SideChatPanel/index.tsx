/**
 * SideChatPanel — the main UI component for the Side Chat feature.
 *
 * Presentational shell: the `useSideChat` hook is lifted into TeamChatView so
 * the side chat session (and any in-flight generation) survives closing the
 * panel. All rendering goes through the shared main-chat pipeline —
 * `SideChatTranscript` (BlockRenderer) for messages and the shared `InputBar`
 * for composing.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { SidePanel } from '@/components/shell/SidePanel'
import { InputBar } from '@/components/InputBar'
import type { InputBarHandle } from '@/components/InputBar'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { SideChatTranscript } from './SideChatTranscript'
import { AlertCircle, Info, Quote, X } from 'lucide-react'
import type { ContentBlock } from '@/api/types'

interface SideChatPanelProps {
  isOpen: boolean
  onClose: () => void
  /** When provided the input is pre-filled with a quoted version of this text. */
  initialQuote?: string | null
  /** Finalized blocks from the persisted history (from useSideChat). */
  blocks: ContentBlock[]
  /** Live blocks accumulating in the current streaming turn. */
  currentBlocks: ContentBlock[]
  isWorking: boolean
  error: string | null
  sideChatId: string | null
  onSend: (content: string) => Promise<void>
  onStop: () => void
}

export function SideChatPanel({
  isOpen,
  onClose,
  initialQuote = null,
  blocks,
  currentBlocks,
  isWorking,
  error,
  sideChatId,
  onSend,
  onStop,
}: SideChatPanelProps) {
  const inputRef = useRef<InputBarHandle>(null)
  // Selected text from the main chat, shown as a chip above the input
  // (Claude-style) instead of being dumped into the textarea. It is only
  // merged into the message content at send time. The chip is derived from
  // the `initialQuote` prop; `clearedQuote` records a dismissed/consumed
  // quote so no state-sync effect is needed.
  const [clearedQuote, setClearedQuote] = useState<string | null>(null)
  const quote = initialQuote && initialQuote !== clearedQuote ? initialQuote : null

  // Focus the input when a fresh quote arrives.
  useEffect(() => {
    if (quote && isOpen) {
      // Focus after React re-renders the textarea.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [quote, isOpen])

  const handleSend = useCallback(
    async (message: string) => {
      const content = quote
        ? `> ${quote.split('\n').join('\n> ')}\n\n${message}`
        : message
      setClearedQuote(quote)
      await onSend(content)
    },
    [quote, onSend],
  )

  if (!isOpen) return null

  return (
    <SidePanel
      storageKey={STORAGE_KEYS.panels.sideChat}
      defaultWidth={400}
      minWidth={320}
      maxWidth={600}
      title={
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-(--color-text-2)">Side Chat</span>
          <span className="rounded bg-(--color-accent-soft) px-1.5 py-0.5 text-[10px] font-medium text-(--color-accent)">
            Read-only
          </span>
        </div>
      }
      onClose={onClose}
      closeLabel="Close side chat"
      resizeLabel="Resize side chat panel"
      className="bg-(--bg-page)"
      mobileOverlay
    >
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Context indicator */}
        <div className="flex items-center gap-2 border-b border-(--color-border) bg-(--bg-key) px-3 py-2">
          <Info size={12} className="shrink-0 text-(color-text-muted)" />
          <span className="text-[11px] text-(--color-text-muted)">
            Read-only context from main session
          </span>
        </div>

        {/* Message list — shared main-chat render pipeline */}
        <SideChatTranscript
          blocks={blocks}
          currentBlocks={currentBlocks}
          isWorking={isWorking}
          sessionId={sideChatId ?? undefined}
          emptyState={
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-accent)">
                <Info size={20} />
              </div>
              <div>
                <p className="text-sm font-medium text-(--color-text)">Side Chat</p>
                <p className="mt-1 text-xs text-(--color-text-muted)">
                  Ask questions about the main session without affecting it.
                  <br />
                  The agent has read-only access to the conversation context.
                </p>
              </div>
            </div>
          }
        />

        {/* Error display */}
        {error && (
          <div className="flex items-center gap-2 border-t border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            <AlertCircle size={12} />
            <span>{error}</span>
          </div>
        )}

        {/* Input bar — shared component, same behavior as the main chat */}
        <div className="shrink-0 border-t border-(--color-border)">
          {/* Quoted selection from the main chat — compact chip, Claude-style.
           * Merged into the outgoing message at send time (see handleSend). */}
          {quote && (
            <div className="px-3 pt-2">
              <div className="flex items-start gap-2 rounded-lg border border-(--color-border) bg-(--bg-key) px-2.5 py-1.5">
                <Quote size={12} className="mt-0.5 shrink-0 text-(--color-text-muted)" />
                <p className="line-clamp-2 min-w-0 flex-1 text-xs break-words whitespace-pre-wrap text-(--color-text-muted)" title={quote}>
                  {quote}
                </p>
                <button
                  type="button"
                  onClick={() => setClearedQuote(quote)}
                  className="shrink-0 rounded-xs p-0.5 text-(--color-text-muted) transition-colors hover:text-(--color-text)"
                  aria-label="Remove quote"
                  title="Remove quote"
                >
                  <X size={12} />
                </button>
              </div>
            </div>
          )}
          <InputBar
            ref={inputRef}
            onSubmit={(message) => void handleSend(message)}
            onStop={onStop}
            isStreaming={isWorking}
            placeholder="Ask a question about the main session…"
            autoFocus
          />
        </div>
      </div>
    </SidePanel>
  )
}
