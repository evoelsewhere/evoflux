/**
 * SideChatPanel — the main UI component for the Side Chat feature.
 *
 * Presentational shell: the `useSideChat` hook is lifted into TeamChatView so
 * the side chat session (and any in-flight generation) survives closing the
 * panel. All rendering goes through the shared main-chat pipeline —
 * `SideChatTranscript` (BlockRenderer) for messages and the shared `InputBar`
 * for composing.
 */
import { useCallback, useEffect, useRef } from 'react'
import { SidePanel } from '@/components/shell/SidePanel'
import { InputBar } from '@/components/InputBar'
import type { InputBarHandle } from '@/components/InputBar'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { SideChatTranscript } from './SideChatTranscript'
import { AlertCircle, ArrowUpRight, LockKeyhole, MessageCircleQuestion, Quote, X } from 'lucide-react'
import type { ContentBlock } from '@/api/types'
import type { SideChatSendResult } from './useSideChat'

const STARTER_PROMPTS = [
  'Summarize the key decisions',
  'Explain the latest response',
  'Spot unanswered questions',
] as const

interface SideChatPanelProps {
  isOpen: boolean
  onClose: () => void
  /** Selected main-chat text shown as context above the composer. */
  initialQuote?: string | null
  onQuoteConsumed: () => void
  /** Finalized blocks from the persisted history (from useSideChat). */
  blocks: ContentBlock[]
  /** Live blocks accumulating in the current streaming turn. */
  currentBlocks: ContentBlock[]
  isWorking: boolean
  error: string | null
  sideChatId: string | null
  onSend: (content: string) => Promise<SideChatSendResult>
  onStop: () => void
  embedded?: boolean
}

export function SideChatPanel({
  isOpen,
  onClose,
  initialQuote = null,
  onQuoteConsumed,
  blocks,
  currentBlocks,
  isWorking,
  error,
  sideChatId,
  onSend,
  onStop,
  embedded = false,
}: SideChatPanelProps) {
  const inputRef = useRef<InputBarHandle>(null)
  const quote = initialQuote

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
      const result = await onSend(content)
      if (result === 'sent') {
        if (quote) onQuoteConsumed()
      } else if (result === 'failed') {
        // InputBar clears immediately after invoking onSubmit; restore the
        // draft when the asynchronous request was not accepted. Append so a
        // slow failure cannot overwrite text entered while the request ran.
        inputRef.current?.appendValue(message)
        inputRef.current?.focus()
      }
    },
    [quote, onSend, onQuoteConsumed],
  )

  const handleStarterPrompt = useCallback((prompt: string) => {
    inputRef.current?.setValue(prompt)
    inputRef.current?.focus()
  }, [])

  if (!isOpen) return null

  return (
    <SidePanel
      storageKey={STORAGE_KEYS.panels.sideChat}
      defaultWidth={400}
      minWidth={320}
      maxWidth={600}
      title={
        <div className="flex items-center gap-2">
          <MessageCircleQuestion size={14} className="text-(--color-text-muted)" aria-hidden="true" />
          <span className="text-xs font-semibold text-(--color-text-2)">Side Chat</span>
        </div>
      }
      headerActions={
        <span
          className="flex items-center gap-1 rounded-md bg-(--bg-key) px-1.5 py-0.5 text-[10px] font-medium text-(--color-text-muted)"
          title="Uses read-only context from the main session"
        >
          <LockKeyhole size={10} aria-hidden="true" />
          Read-only
        </span>
      }
      onClose={onClose}
      closeLabel="Close side chat"
      resizeLabel="Resize side chat panel"
      ariaLabel="Side chat panel"
      className="bg-(--bg-page)"
      mobileOverlay
      fillParent={embedded}
    >
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Message list — shared main-chat render pipeline */}
        <SideChatTranscript
          blocks={blocks}
          currentBlocks={currentBlocks}
          isWorking={isWorking}
          sessionId={sideChatId ?? undefined}
          emptyState={
            <div className="flex h-full items-center justify-center px-2 py-8">
              <div className="w-full max-w-xs">
                <div className="mb-5 flex items-center gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-2)">
                    <MessageCircleQuestion size={17} aria-hidden="true" />
                  </div>
                  <p className="text-sm font-medium text-(--color-text)">
                    Ask about this conversation
                  </p>
                </div>
                <div className="border-y border-(--color-border)">
                  {STARTER_PROMPTS.map((prompt, index) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => handleStarterPrompt(prompt)}
                      className={`group flex w-full items-center gap-3 py-2.5 text-left text-xs text-(--color-text-muted) transition-colors hover:text-(--color-text) ${
                        index > 0 ? 'border-t border-(--color-border)' : ''
                      }`}
                      aria-label={`Use prompt: ${prompt}`}
                    >
                      <span className="min-w-0 flex-1">{prompt}</span>
                      <ArrowUpRight
                        size={13}
                        className="shrink-0 opacity-50 transition-opacity group-hover:opacity-100"
                        aria-hidden="true"
                      />
                    </button>
                  ))}
                </div>
              </div>
            </div>
          }
        />

        {/* Error display */}
        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 border-t border-(--color-error)/30 bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error)"
          >
            <AlertCircle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0 break-words">{error}</span>
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
                  onClick={onQuoteConsumed}
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
            attachmentsEnabled={false}
            placeholder="Ask a question about the main session…"
            autoFocus
          />
        </div>
      </div>
    </SidePanel>
  )
}
