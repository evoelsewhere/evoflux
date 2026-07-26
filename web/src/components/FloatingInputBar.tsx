import { forwardRef, useRef, useImperativeHandle } from 'react'
import { InputBar, type FileRef, type InputBarHandle, type SlashCommand, type SnippetCommand } from './InputBar'
import { RevertNotice } from './RevertNotice'
import { useIsMobile } from '@/hooks/use-mobile'
import { useVisualKeyboardInset } from '@/hooks/use-visual-keyboard-inset'
import type { AgentCapabilities, TodoItem } from '@/api/types'

interface FloatingInputBarProps {
  boundsRef: React.RefObject<HTMLElement | null>
  onSubmit: (message: string, files?: File[]) => boolean | void | Promise<boolean | void>
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
  agentMode?: 'coding' | 'aim' | null
  todos?: TodoItem[]
  todosOpen?: boolean
  onTodosOpenChange?: (open: boolean) => void
  sessionId?: string | null
  onWiki?: () => void
  wikiActive?: boolean
  onActivity?: () => void
  activityActive?: boolean
  webBridgeEnabled?: boolean
  onWebBridgeEnabledChange?: (enabled: boolean) => void
  permissionMode?: import('@/api/types').PermissionMode
  onPermissionModeChange?: (mode: import('@/api/types').PermissionMode) => void
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
  function FloatingInputBar({ boundsRef: _, revertedCount, revertedMessages, onRedo, ...inputBarProps }, ref) {
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

    // ── Mobile: sticky bottom sheet with keyboard-inset awareness ────────
    if (isMobile) {
      return (
        <div
          className="pointer-events-auto shrink-0 border-t border-(--color-border) bg-(--bg-page) pb-safe transition-[padding-bottom] duration-(--motion-fast)"
          style={keyboardInset > 0 ? { paddingBottom: `calc(${keyboardInset}px + 0.5rem)` } : undefined}
        >
          <RevertNotice count={revertedCount ?? 0} messages={revertedMessages ?? []} onRedo={onRedo} />
          <InputBar ref={innerRef} floating filesBelow={false} {...inputBarProps} />
        </div>
      )
    }

    // ── Desktop: InputBar owns the card — we just provide flex context ───
    return (
      <div className="pointer-events-auto shrink-0">
        {(revertedCount ?? 0) > 0 && (
          <div className="mx-auto max-w-3xl px-4 pb-1">
            <RevertNotice count={revertedCount ?? 0} messages={revertedMessages ?? []} onRedo={onRedo} />
          </div>
        )}
        <InputBar ref={innerRef} {...inputBarProps} />
      </div>
    )
  },
)
