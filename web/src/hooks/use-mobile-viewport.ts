import { useEffect } from 'react'

import { getPlatform } from '@/hooks/use-platform'

export function useMobileViewportGuards() {
  useEffect(() => {
    const { isTauri, os } = getPlatform()
    if (!isTauri || (os !== 'ios' && os !== 'android')) return

    const root = document.documentElement
    root.setAttribute('data-mobile-shell', os)

    const preventGestureZoom = (event: Event) => {
      event.preventDefault()
    }

    let lastTouchEnd = 0
    const preventDoubleTapZoom = (event: TouchEvent) => {
      const now = Date.now()
      if (now - lastTouchEnd <= 300) {
        event.preventDefault()
      }
      lastTouchEnd = now
    }

    const preventPinchZoom = (event: TouchEvent) => {
      if (event.touches.length > 1) {
        event.preventDefault()
      }
    }

    document.addEventListener('gesturestart', preventGestureZoom)
    document.addEventListener('gesturechange', preventGestureZoom)
    document.addEventListener('gestureend', preventGestureZoom)
    document.addEventListener('touchend', preventDoubleTapZoom, { passive: false })
    document.addEventListener('touchmove', preventPinchZoom, { passive: false })

    return () => {
      root.removeAttribute('data-mobile-shell')
      document.removeEventListener('gesturestart', preventGestureZoom)
      document.removeEventListener('gesturechange', preventGestureZoom)
      document.removeEventListener('gestureend', preventGestureZoom)
      document.removeEventListener('touchend', preventDoubleTapZoom)
      document.removeEventListener('touchmove', preventPinchZoom)
    }
  }, [])
}
