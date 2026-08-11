import { useEffect, useRef, useState, type RefObject } from 'react'
import { useUIStore } from '@/stores/useUIStore'
import { shouldUseSidebarOverlay } from './auto-layout'

interface AdaptiveSidebarOverlayOptions {
  mainColumnRef: RefObject<HTMLDivElement | null>
  workbenchOpen: boolean
  isMobile: boolean
  macOverlay?: boolean
}

/**
 * Move desktop navigation out of flex layout when the Workbench crowds the
 * conversation. This is transient responsive state; it deliberately never
 * mutates the user's persisted collapsed/expanded preference.
 */
export function useAdaptiveSidebarOverlay({
  mainColumnRef,
  workbenchOpen,
  isMobile,
  macOverlay = false,
}: AdaptiveSidebarOverlayOptions): boolean {
  const sidebarCollapsed = useUIStore((state) => state.sidebarCollapsed)
  const sidebarWidth = useUIStore((state) => state.sidebarWidth)
  const setRootSidebarOverlay = useUIStore((state) => state.setSidebarOverlay)
  const [sidebarOverlay, setSidebarOverlay] = useState(false)
  const sidebarOverlayRef = useRef(false)

  const active = workbenchOpen && !isMobile

  useEffect(() => {
    if (!active) {
      setRootSidebarOverlay(false)
      return
    }

    const mainColumn = mainColumnRef.current
    if (!mainColumn) return

    const update = (mainWidth: number) => {
      const nextOverlay = shouldUseSidebarOverlay({
        workbenchOpen: true,
        isMobile: false,
        sidebarMode: sidebarOverlayRef.current ? 'overlay' : 'docked',
        sidebarCollapsed,
        mainWidth,
        sidebarWidth,
        macOverlay,
      })
      sidebarOverlayRef.current = nextOverlay
      setSidebarOverlay(nextOverlay)
      setRootSidebarOverlay(nextOverlay)
    }
    const updateFromLayout = () => update(mainColumn.getBoundingClientRect().width)

    const initialFrame = window.requestAnimationFrame(updateFromLayout)
    window.addEventListener('resize', updateFromLayout)

    if (typeof ResizeObserver === 'undefined') {
      return () => {
        window.cancelAnimationFrame(initialFrame)
        window.removeEventListener('resize', updateFromLayout)
      }
    }

    const observer = new ResizeObserver(([entry]) => {
      update(entry?.contentRect.width ?? mainColumn.clientWidth)
    })
    observer.observe(mainColumn)
    return () => {
      window.cancelAnimationFrame(initialFrame)
      window.removeEventListener('resize', updateFromLayout)
      observer.disconnect()
    }
  }, [
    active,
    macOverlay,
    mainColumnRef,
    sidebarCollapsed,
    sidebarWidth,
    setRootSidebarOverlay,
  ])

  useEffect(() => () => {
    useUIStore.getState().setSidebarOverlay(false)
  }, [])

  return active && sidebarOverlay
}
