import { forwardRef, useRef, useImperativeHandle } from 'react'
import { InputBar, type FileRef, type InputBarHandle, type SlashCommand, type SnippetCommand } from './InputBar'
import { RevertNotice } from './RevertNotice'
import { useIsMobile } from '@/hooks/use-mobile'
import { useVisualKeyboardInset } from '@/hooks/use-visual-keyboard-inset'
import type { AgentCapabilities } from '@/api/types'

interface FloatingInputBarProps {
  boundsRef: React.RefObject<HTMLElement | null>
  onSubmit: (message: string, files?: File[]) => void
  onStop?: () => void
  onSlashCommand?: (id: string) => void
  onSnippetCommand?: (id: string) => Promise<string | null> | string | null
  slashCommands?: SlashCommand[]
  snippetCommands?: SnippetCommand[]
  fileRefs?: FileRef[]
  onFileRefsNeeded?: () => void
  isStreaming?: boolean
  disabled?: boolean
  placeholder?: string
  autoFocus?: boolean
  capabilities?: AgentCapabilities
  revertedCount?: number
  revertedMessages?: Array<{ role: string; content: string }>
  onRedo?: () => void
  historyPrompts?: string[]
  sessionModel?: string | null
  defaultModel?: string | null
  sessionThinkingLevel?: string | null
  sessionFastMode?: boolean
  onSessionModelSettingsChange?: (model: string | null, thinkingLevel: string | null, fastMode: boolean) => void
  agentNames?: string[]
  agentWorkspace?: string | null
}

/**
 * Input bar — rendered as a flex-none item at the bottom of the parent
 * `<main>` flex column. No absolute/fixed positioning; the parent layout
 * constrains it to the chat area (excludes sidebar).
 *
 * Mobile: adds `safe-area-inset-bottom` clearance and lifts above the
 * soft keyboard via `visualViewport` inset.
 */
export const FloatingInputBar = forwardRef<InputBarHandle, FloatingInputBarProps>(
  function FloatingInputBar({ boundsRef: _, ...inputProps }, ref) {
    const isMobile = useIsMobile()
    const keyboardInset = useVisualKeyboardInset()
    const innerRef = useRef<InputBarHandle | null>(null)

    useImperativeHandle(ref, () => ({
      focus: () => innerRef.current?.focus(),
      setValue: (text: string) => innerRef.current?.setValue(text),
      appendValue: (text: string) => innerRef.current?.appendValue(text),
      insertText: (text: string) => innerRef.current?.insertText(text),
      setFiles: (files: File[]) => innerRef.current?.setFiles(files),
    }), [])

    // ── Mobile: soft keyboard aware ──────────────────────────────────────
    if (isMobile) {
      return (
        <div
          className="pointer-events-auto shrink-0 rounded-t-2xl border border-b-0 border-(--color-border) bg-(--color-surface) px-3 pb-safe pt-2 shadow-[0_-4px_16px_rgba(0,0,0,0.06)] transition-[padding-bottom] duration-150"
          style={keyboardInset > 0 ? { paddingBottom: `calc(${keyboardInset}px + 0.5rem)` } : undefined}
        >
          <RevertNotice count={inputProps.revertedCount ?? 0} messages={inputProps.revertedMessages ?? []} onRedo={inputProps.onRedo} />
          <InputBar ref={innerRef} floating filesBelow={false} {...inputProps} />
        </div>
      )
    }

    // ── Desktop: centered bottom bar matching chat content width ─────────
    return (
      <div className="pointer-events-auto shrink-0 px-4 pb-4 pt-2">
        <div className="mx-auto max-w-3xl rounded-2xl border border-(--color-border) bg-(--color-surface) px-4 pb-3 pt-2 shadow-[0_-4px_16px_rgba(0,0,0,0.06)]">
          <RevertNotice count={inputProps.revertedCount ?? 0} messages={inputProps.revertedMessages ?? []} onRedo={inputProps.onRedo} />
          <InputBar ref={innerRef} floating {...inputProps} />
        </div>
      </div>
    )
  },
)
