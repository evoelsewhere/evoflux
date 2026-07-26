import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

interface ResizableWidthOptions {
  storageKey: string
  defaultWidth: number
  minWidth: number
  maxWidth: number
  edge: 'left' | 'right'
  disabled?: boolean
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function useResizableWidth({
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth,
  edge,
  disabled = false,
}: ResizableWidthOptions) {
  const [width, setWidth] = useState(() => {
    if (typeof window === 'undefined') return defaultWidth
    const stored = window.localStorage.getItem(storageKey)
    const parsed = stored ? Number(stored) : Number.NaN
    return Number.isFinite(parsed) ? clamp(parsed, minWidth, maxWidth) : defaultWidth
  })
  const [isResizing, setIsResizing] = useState(false)
  const clampedWidth = clamp(width, minWidth, maxWidth)
  // Always-current live width — updated during drag without triggering renders.
  const liveWidthRef = useRef(clampedWidth)
  liveWidthRef.current = clampedWidth

  useEffect(() => {
    if (disabled) return
    window.localStorage.setItem(storageKey, String(clampedWidth))
  }, [clampedWidth, disabled, storageKey])

  const resetWidth = useCallback(() => setWidth(defaultWidth), [defaultWidth])

  const startResize = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (disabled || event.pointerType === 'touch') return
    event.preventDefault()
    event.stopPropagation()

    // The resize handle is a direct child of the resizable panel element.
    // Direct DOM style writes bypass React/framer-motion entirely — zero lag.
    const panelEl = event.currentTarget.parentElement as HTMLElement | null
    const startX = event.clientX
    const startWidth = liveWidthRef.current

    setIsResizing(true)

    const handleMove = (e: PointerEvent) => {
      const delta = edge === 'right' ? e.clientX - startX : startX - e.clientX
      const newWidth = clamp(startWidth + delta, minWidth, maxWidth)
      liveWidthRef.current = newWidth
      // Direct DOM write — no React re-render during drag.
      if (panelEl) panelEl.style.width = `${newWidth}px`
    }

    const handleUp = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      window.removeEventListener('pointercancel', handleUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      setIsResizing(false)
      // Sync final width to React state once (localStorage + one re-render).
      setWidth(liveWidthRef.current)
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp, { once: true })
    window.addEventListener('pointercancel', handleUp, { once: true })
  }, [disabled, edge, maxWidth, minWidth])

  return { width: clampedWidth, startResize, resetWidth, isResizing }
}
