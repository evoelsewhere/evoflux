/**
 * useMobileEdgeSwipes — touch edge-swipe gestures for the mobile chat
 * shell (extracted unchanged from TeamChatView).
 *
 * Left-edge swipe (first 24px) opens the mobile sidebar drawer; right-edge
 * swipe opens the mobile chat-actions sheet. Only active on iOS/Android
 * while the respective drawer is closed. Returns the four composed touch
 * handlers TeamChatView spreads onto ``AppShell``.
 */
import { useCallback, useRef } from 'react'
import type { OS } from '@/hooks/use-platform'

interface UseMobileEdgeSwipesArgs {
  os: OS
  isMobile: boolean
  mode: 'work' | 'coding' | 'aim'
  mobileSidebarOpen: boolean
  showMobileActions: boolean
  setMobileSidebarOpen: (open: boolean) => void
  setShowMobileActions: (open: boolean) => void
  /** Close the coding workbench + file viewer (coding mode only). */
  closeCodingPanels: () => void
}

export function useMobileEdgeSwipes({
  os,
  isMobile,
  mode,
  mobileSidebarOpen,
  showMobileActions,
  setMobileSidebarOpen,
  setShowMobileActions,
  closeCodingPanels,
}: UseMobileEdgeSwipesArgs) {
  const mobileSidebarSwipeStartRef = useRef<{ x: number; y: number } | null>(null)
  const mobileActionsSwipeStartRef = useRef<{ x: number; y: number } | null>(null)

  const handleMobileSidebarSwipeStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    // AIM Discussion is nested in the project shell and has no chat drawer.
    if (mode === 'aim' || (os !== 'ios' && os !== 'android') || !isMobile || mobileSidebarOpen) return
    const touch = event.touches[0]
    if (!touch || touch.clientX > 24) return
    mobileSidebarSwipeStartRef.current = { x: touch.clientX, y: touch.clientY }
  }, [isMobile, mobileSidebarOpen, mode, os])

  const handleMobileSidebarSwipeMove = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const start = mobileSidebarSwipeStartRef.current
    if (!start || (os !== 'ios' && os !== 'android') || !isMobile || mobileSidebarOpen) return
    const touch = event.touches[0]
    if (!touch) return
    const deltaX = touch.clientX - start.x
    const deltaY = touch.clientY - start.y
    if (deltaX > 56 && Math.abs(deltaY) < 36) {
      if (mode === 'coding') {
        closeCodingPanels()
      }
      setMobileSidebarOpen(true)
      mobileSidebarSwipeStartRef.current = null
    }
  }, [isMobile, mobileSidebarOpen, mode, os, closeCodingPanels, setMobileSidebarOpen])

  const handleMobileSidebarSwipeEnd = useCallback(() => {
    mobileSidebarSwipeStartRef.current = null
  }, [])

  const handleMobileActionsSwipeStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    if ((os !== 'ios' && os !== 'android') || !isMobile || showMobileActions) return
    const touch = event.touches[0]
    if (!touch || window.innerWidth - touch.clientX > 24) return
    mobileActionsSwipeStartRef.current = { x: touch.clientX, y: touch.clientY }
  }, [isMobile, os, showMobileActions])

  const handleMobileActionsSwipeMove = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const start = mobileActionsSwipeStartRef.current
    if (!start || (os !== 'ios' && os !== 'android') || !isMobile || showMobileActions) return
    const touch = event.touches[0]
    if (!touch) return
    const deltaX = touch.clientX - start.x
    const deltaY = touch.clientY - start.y
    if (deltaX < -56 && Math.abs(deltaY) < 36) {
      setShowMobileActions(true)
      mobileActionsSwipeStartRef.current = null
    }
  }, [isMobile, os, showMobileActions, setShowMobileActions])

  const handleMobileActionsSwipeEnd = useCallback(() => {
    mobileActionsSwipeStartRef.current = null
  }, [])

  return {
    onTouchStart: (event: React.TouchEvent<HTMLDivElement>) => {
      handleMobileSidebarSwipeStart(event)
      handleMobileActionsSwipeStart(event)
    },
    onTouchMove: (event: React.TouchEvent<HTMLDivElement>) => {
      handleMobileSidebarSwipeMove(event)
      handleMobileActionsSwipeMove(event)
    },
    onTouchEnd: () => {
      handleMobileSidebarSwipeEnd()
      handleMobileActionsSwipeEnd()
    },
    onTouchCancel: () => {
      handleMobileSidebarSwipeEnd()
      handleMobileActionsSwipeEnd()
    },
  }
}
