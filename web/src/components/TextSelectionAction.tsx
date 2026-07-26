/**
 * TextSelectionAction — floating action toolbar for transcript selections.
 *
 * Follows the same `window.getSelection()` approach used in PlanReviewPanel
 * but renders via a portal so it sits above all other UI without affecting
 * transcript layout.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'

interface Position {
  top: number
  left: number
  placement: 'above' | 'below'
}

interface TextSelectionActionProps {
  /** Ref to the scrollable container whose text should be monitored. */
  containerRef: React.RefObject<HTMLDivElement | null>
  /** Quote the selection into the primary composer. */
  onAddToChat: (selectedText: string) => void
  /** Prepare a primary-chat request to explain the selection in more detail. */
  onMoreDetails: (selectedText: string) => void
  /** Open a side-chat thread grounded in the selection. */
  onSendToSideChat: (selectedText: string) => void
  /** When true the listener is active and the toolbar can appear. */
  enabled?: boolean
}

/**
 * Floating toolbar that tracks the current text selection inside
 * `containerRef` and exposes primary-chat and side-chat actions.
 *
 * The button is absolutely positioned near the end of the selection and
 * disappears as soon as the selection collapses or the user clicks
 * elsewhere.
 */
export function TextSelectionAction({
  containerRef,
  onAddToChat,
  onMoreDetails,
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
      // A new selection outside the transcript invalidates any action left
      // over from the previous in-transcript selection.
      dismiss()
      return
    }

    const text = sel.toString().trim()
    if (!text) {
      dismiss()
      return
    }

    const rect = sel.getRangeAt(0).getBoundingClientRect()
    const toolbarWidth = Math.min(430, window.innerWidth - 16)
    const placement = rect.top >= 56 ? 'above' : 'below'
    setPosition({
      top: placement === 'above' ? rect.top - 8 : rect.bottom + 8,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - toolbarWidth - 8)),
      placement,
    })
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

  const runAction = (action: (text: string) => void) => {
    action(selectedText)
    // Give the parent a tick to react before we clear the browser selection.
    requestAnimationFrame(() => {
      window.getSelection()?.removeAllRanges()
      dismiss()
    })
  }

  return createPortal(
    <div
      role="toolbar"
      aria-label="Text selection actions"
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        transform: position.placement === 'above' ? 'translateY(-100%)' : undefined,
      }}
      className="pointer-events-auto z-(--z-toast) flex max-w-[calc(100vw-1rem)] divide-x divide-(--color-border) overflow-x-auto rounded-lg border border-(--color-border) bg-(--bg-page)/95 shadow-xl backdrop-blur-xl animate-in fade-in-0 zoom-in-95"
    >
      {([
        ['Add to chat', onAddToChat],
        ['More details', onMoreDetails],
        ['Ask in side chat', onSendToSideChat],
      ] as const).map(([label, action]) => (
        <button
          key={label}
          type="button"
          onMouseDown={(event) => {
            event.preventDefault()
            event.stopPropagation()
          }}
          onClick={() => runAction(action)}
          className={cn(
            'min-h-10 shrink-0 whitespace-nowrap px-3 text-sm font-medium text-(--color-text-2) outline-none transition-colors',
            'hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:bg-(--bg-key) focus-visible:text-(--color-text)',
          )}
        >
          {label}
        </button>
      ))}
    </div>,
    document.body,
  )
}
