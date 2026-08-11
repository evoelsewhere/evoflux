import { useEffect, type RefObject } from 'react'
import { useUIStore } from '@/stores/useUIStore'
import { shouldAutoCollapseSidebar } from './auto-layout'

interface AutoCollapseSidebarOptions {
  mainColumnRef: RefObject<HTMLDivElement | null>
  workbenchOpen: boolean
  isMobile: boolean
}

/** Collapse the desktop sidebar when the Workbench crowds the conversation. */
export function useAutoCollapseSidebar({
  mainColumnRef,
  workbenchOpen,
  isMobile,
}: AutoCollapseSidebarOptions): void {
  const setSidebarCollapsed = useUIStore((state) => state.setSidebarCollapsed)

  useEffect(() => {
    if (!workbenchOpen || isMobile || typeof ResizeObserver === 'undefined') return
    const mainColumn = mainColumnRef.current
    if (!mainColumn) return

    const observer = new ResizeObserver(([entry]) => {
      const sidebarCollapsed = useUIStore.getState().sidebarCollapsed
      const mainWidth = entry?.contentRect.width ?? mainColumn.clientWidth
      if (shouldAutoCollapseSidebar({
        workbenchOpen: true,
        isMobile: false,
        sidebarCollapsed,
        mainWidth,
      })) {
        setSidebarCollapsed(true)
      }
    })
    observer.observe(mainColumn)
    return () => observer.disconnect()
  }, [isMobile, mainColumnRef, setSidebarCollapsed, workbenchOpen])
}
