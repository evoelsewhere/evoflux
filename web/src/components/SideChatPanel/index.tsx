/**
 * SideChatPanel — the main UI component for the Side Chat feature.
 *
 * Renders a side panel with:
 *   - Header: "Side Chat" title + close button
 *   - Message list: renders messages using existing markdown renderer
 *   - Input bar at bottom: text input + send button
 *   - Visual indicator: "Read-only context from main session" badge
 *
 * Uses the existing SidePanel shell component for consistent chrome.
 */
import { useState, useRef, useCallback, useEffect } from 'react'
import { SidePanel } from '@/components/shell/SidePanel'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { useSideChat } from './useSideChat'
import { SideChatMessage } from './SideChatMessage'
import { Send, Loader2, AlertCircle, Info } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SideChatPanelProps {
  mainSessionId: string
  isOpen: boolean
  onClose: () => void
  /** When provided the input is pre-filled with a quoted version of this text. */
  initialQuote?: string | null
}

export function SideChatPanel({ mainSessionId, isOpen, onClose, initialQuote = null }: SideChatPanelProps) {
  const {
    messages,
    isWorking,
    error,
    sendMessage,
  } = useSideChat(mainSessionId)

  const [inputValue, setInputValue] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // When a quote is provided (e.g. from text selection in the main chat),
  // pre-fill the input with the quoted text and focus it.
  useEffect(() => {
    if (initialQuote) {
      setInputValue(`> ${initialQuote}\n\n`)
      // Focus after React re-renders the textarea.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [initialQuote])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages.length, isWorking])

  const handleSubmit = useCallback(async () => {
    const content = inputValue.trim()
    if (!content || isWorking) return
    setInputValue('')
    await sendMessage(content)
  }, [inputValue, isWorking, sendMessage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSubmit()
    }
  }, [handleSubmit])

  if (!isOpen) return null

  return (
    <SidePanel
      storageKey={STORAGE_KEYS.panels.activity} // Reuse existing storage key pattern
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

        {/* Message list */}
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 overflow-y-auto px-3 py-4"
        >
          {messages.length === 0 ? (
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
          ) : (
            <div className="space-y-4">
              {messages.map((msg) => (
                <SideChatMessage
                  key={msg.id}
                  role={msg.role}
                  content={msg.content}
                  blocks={msg.blocks}
                  agent={msg.agent}
                  timestamp={msg.timestamp}
                  isStreaming={isWorking && msg === messages[messages.length - 1]}
                />
              ))}
              {isWorking && messages[messages.length - 1]?.role === 'user' && (
                <div className="flex items-center gap-2 text-xs text-(--color-text-muted)">
                  <Loader2 size={12} className="animate-spin" />
                  <span>Thinking…</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Error display */}
        {error && (
          <div className="flex items-center gap-2 border-t border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            <AlertCircle size={12} />
            <span>{error}</span>
          </div>
        )}

        {/* Input bar */}
        <div className="shrink-0 border-t border-(--color-border) p-3">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about the main session…"
              rows={1}
              className={cn(
                'min-h-[36px] max-h-[120px] flex-1 resize-none rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2 text-sm text-(--color-text) placeholder:text-(--color-text-muted)',
                'focus:border-(--color-accent) focus:outline-none focus:ring-1 focus:ring-(--color-accent)',
              )}
              style={{ fieldSizing: 'content' } as React.CSSProperties}
            />
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!inputValue.trim() || isWorking}
              className={cn(
                'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors',
                inputValue.trim() && !isWorking
                  ? 'bg-(--color-accent) text-white hover:bg-(--color-accent)/90'
                  : 'bg-(--bg-key) text-(--color-text-muted)',
              )}
              aria-label="Send message"
            >
              {isWorking ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Send size={16} />
              )}
            </button>
          </div>
          <p className="mt-1.5 text-[10px] text-(--color-text-muted)">
            Press Enter to send, Shift+Enter for new line
          </p>
        </div>
      </div>
    </SidePanel>
  )
}
