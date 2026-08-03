/**
 * TextSelectionAction — floating action toolbar for transcript selections.
 *
 * Follows the same `window.getSelection()` approach used in PlanReviewPanel
 * but renders via a portal so it sits above all other UI without affecting
 * transcript layout.
 *
 * The toolbar only appears once the selection is *stable*: no mouse button
 * is held and the selected text has not changed for a short settle window.
 * This keeps it from popping up mid-drag, stealing the pointer, or
 * jittering along with every `selectionchange` event.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'

/** How long the selection text must stay unchanged before showing. */
const SETTLE_MS = 180

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
  // True while any mouse button is held — suppresses the toolbar mid-drag.
  const mouseDownRef = useRef(false)
  // Settle timer: the toolbar shows only after the selection has been
  // unchanged (and the mouse released) for SETTLE_MS.
  const settleTimerRef = useRef<number | null>(null)
  // Latest selection-derived facts, refreshed on every captureSelection so
  // the settle timer can re-validate before showing (avoids acting on a
  // selection that changed or collapsed while the timer was pending).
  const pendingTextRef = useRef('')
  const pendingRectRef = useRef<{ top: number; bottom: number; left: number } | null>(null)
  // Always-current enabled flag so stable callbacks can read it without
  // being recreated (which would re-register the listeners).
  const enabledRef = useRef(enabled)
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  const clearSettle = useCallback(() => {
    if (settleTimerRef.current !== null) {
      window.clearTimeout(settleTimerRef.current)
      settleTimerRef.current = null
    }
  }, [])

  const dismiss = useCallback(() => {
    activeRef.current = false
    pendingTextRef.current = ''
    clearSettle()
    setPosition(null)
    setSelectedText('')
  }, [clearSettle])

  const showPending = useCallback(() => {
    const text = pendingTextRef.current
    const rect = pendingRectRef.current
    if (!text || !rect) return
    const toolbarWidth = Math.min(430, window.innerWidth - 16)
    const placement = rect.top >= 56 ? 'above' : 'below'
    setPosition({
      top: placement === 'above' ? rect.top - 8 : rect.bottom + 8,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - toolbarWidth - 8)),
      placement,
    })
    setSelectedText(text)
    activeRef.current = true
  }, [])

  const scheduleSettle = useCallback(() => {
    clearSettle()
    settleTimerRef.current = window.setTimeout(() => {
      settleTimerRef.current = null
      if (!mouseDownRef.current) showPending()
    }, SETTLE_MS)
  }, [clearSettle, showPending])

  const captureSelection = useCallback(() => {
    if (!enabledRef.current) {
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

    // Snapshot the anchor rect now — the selection may be gone by the time
    // the settle timer fires, and getBoundingClientRect on a dead selection
    // returns zeros.
    const rect = sel.getRangeAt(0).getBoundingClientRect()
    pendingRectRef.current = { top: rect.top, bottom: rect.bottom, left: rect.left }

    // Mid-drag: hide any visible toolbar and just remember the latest facts —
    // the mouseup handler will schedule the settle window.
    if (mouseDownRef.current) {
      if (activeRef.current) dismiss()
      pendingTextRef.current = text
      return
    }

    // Selection changed: hide a toolbar showing stale text and (re)start
    // the settle window. Same text with no toolbar and no pending timer
    // rearms the window so the toolbar is never dropped silently.
    if (text !== pendingTextRef.current) {
      pendingTextRef.current = text
      if (activeRef.current) dismiss()
      scheduleSettle()
    } else if (!activeRef.current && settleTimerRef.current === null) {
      scheduleSettle()
    }
  }, [containerRef, dismiss, scheduleSettle])

  // Global selection listener — fires on every selection change and also on
  // mouse / key up so we catch edge cases where selectionchange doesn't fire.
  // Mouse button state is tracked separately so the toolbar stays hidden
  // while the user is still dragging the selection.
  useEffect(() => {
    const handleMouseDown = (event: MouseEvent) => {
      if (event.button === 0) {
        const target = event.target
        if (
          target instanceof Element
          && target.closest('[data-text-selection-toolbar]')
        ) {
          return
        }
        mouseDownRef.current = true
        // Starting a new drag hides a toolbar from a previous selection.
        if (activeRef.current) dismiss()
      }
    }
    const handleMouseUp = (event: MouseEvent) => {
      if (event.button === 0) {
        mouseDownRef.current = false
        // Evaluate now that the drag is over — captureSelection starts the
        // settle window if there is a live selection.
        captureSelection()
      }
    }
    // If the window loses focus mid-drag (Cmd-Tab, clicking another app),
    // the matching mouseup may never arrive — reset so the toolbar isn't
    // suppressed forever.
    const handleBlur = () => {
      mouseDownRef.current = false
    }
    document.addEventListener('mousedown', handleMouseDown, true)
    document.addEventListener('mouseup', handleMouseUp, true)
    document.addEventListener('selectionchange', captureSelection)
    document.addEventListener('keyup', captureSelection)
    window.addEventListener('blur', handleBlur)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown, true)
      document.removeEventListener('mouseup', handleMouseUp, true)
      document.removeEventListener('selectionchange', captureSelection)
      document.removeEventListener('keyup', captureSelection)
      window.removeEventListener('blur', handleBlur)
      clearSettle()
    }
  }, [captureSelection, dismiss, clearSettle])

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
      data-text-selection-toolbar
      role="toolbar"
      aria-label="Text selection actions"
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        transform: position.placement === 'above' ? 'translateY(-100%)' : undefined,
      }}
      className="pointer-events-auto z-(--z-toast) flex max-w-[calc(100vw-1rem)] divide-x divide-(--color-border) overflow-x-auto rounded-md border border-(--color-border) bg-(--bg-page)/95 shadow-lg backdrop-blur-xl animate-in fade-in-0 zoom-in-95"
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
            'inline-flex min-h-8 shrink-0 items-center justify-center whitespace-nowrap px-2.5 py-1 text-xs font-medium leading-4 text-(--color-text-2) outline-none transition-colors',
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
