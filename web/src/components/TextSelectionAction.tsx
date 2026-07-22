/**
 * TextSelectionAction — floating button that appears when the user selects
 * text inside a constrained container. Clicking the button fires
 * `onSendToSideChat` with the selected text and clears the selection.
 *
 * Follows the same `window.getSelection()` approach used in
 * PlanReviewPanel (lines 157-174) but renders via a portal so it sits
 * above all other UI without interfering with the container's layout.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MessageSquarePlus } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Position {
  top: number
  left: number
}

interface TextSelectionActionProps {
  /** Ref to the scrollable container whose text should be monitored. */
  containerRef: React.RefObject<HTMLDivElement | null>
  /** Called with the selected text when the user clicks the action button. */
  onSendToSideChat: (selectedText: string) => void
  /** When true the listener is active and the button can appear. */
  enabled?: boolean
}

/**
 * Floating popover that tracks the current text selection inside
 * `containerRef` and renders a tiny "Send to side chat" action button.
 *
 * The button is absolutely positioned near the end of the selection and
 * disappears as soon as the selection collapses or the user clicks
 * elsewhere.
 */
export function TextSelectionAction({
  containerRef,
  onSendToSideChat,
  enabled = true,
}: TextSelectionActionProps) {
  const [position, setPosition] = useState<Position | null>(null)
  const [selectedText, setSelectedText] = useState('')
  const activeRef = useRef(false)

  const dismiss = useCallback(() => {
    activeRef.current = false
    setPosition(null)
    setSelectedText('')
  }, [])

  const captureSelection = useCallback(() => {
    if (!enabled) {
      dismiss()
      return
    }

    const sel = window.getSelection()
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
      dismiss()
      return
    }

    const container = containerRef.current
    if (
      !container ||
      !container.contains(sel.anchorNode) ||
      !container.contains(sel.focusNode)
    ) {
      // Selection is outside our container — ignore.
      return
    }

    const text = sel.toString().trim()
    if (!text) {
      dismiss()
      return
    }

    const rect = sel.getRangeAt(0).getBoundingClientRect()
    setPosition({ top: rect.bottom + 6, left: rect.left })
    setSelectedText(text)
    activeRef.current = true
  }, [containerRef, dismiss, enabled])

  // Global selection listener — fires on every selection change and also on
  // mouse / key up so we catch edge cases where selectionchange doesn't fire.
  useEffect(() => {
    document.addEventListener('selectionchange', captureSelection)
    document.addEventListener('mouseup', captureSelection)
    document.addEventListener('keyup', captureSelection)
    return () => {
      document.removeEventListener('selectionchange', captureSelection)
      document.removeEventListener('mouseup', captureSelection)
      document.removeEventListener('keyup', captureSelection)
    }
  }, [captureSelection])

  // Dismiss on click outside or scroll inside the container.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const handleScroll = () => {
      if (activeRef.current) dismiss()
    }
    container.addEventListener('scroll', handleScroll, { passive: true })
    return () => container.removeEventListener('scroll', handleScroll)
  }, [containerRef, dismiss])

  if (!position || !selectedText) return null

  const handleSend = () => {
    onSendToSideChat(selectedText)
    // Give the parent a tick to react before we clear the browser selection.
    requestAnimationFrame(() => {
      window.getSelection()?.removeAllRanges()
      dismiss()
    })
  }

  return createPortal(
    <div
      style={{ position: 'fixed', top: position.top, left: position.left }}
      className="pointer-events-auto z-(--z-toast) animate-in fade-in-0 zoom-in-95"
    >
      <button
        type="button"
        onMouseDown={(e) => {
          // Prevent the mousedown from collapsing the selection.
          e.preventDefault()
          e.stopPropagation()
        }}
        onClick={handleSend}
        className={cn(
          'flex items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-page) px-2 py-1 text-xs font-medium shadow-md',
          'text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
        )}
        title="Send to side chat"
      >
        <MessageSquarePlus size={14} aria-hidden="true" />
        <span className="hidden sm:inline">Send to side chat</span>
      </button>
    </div>,
    document.body,
  )
}
