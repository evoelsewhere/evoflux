/**
 * MacTitleBar — platform marker + 70 × 40 corner drag pad over the
 * macOS traffic-light inset.
 *
 * Routes provide drag on the rest of the top edge via `useTauriDrag`
 * on their own headers. A full-width strip would steal mousedowns
 * from route header buttons; the corner pad sits over empty pixels
 * only, so collisions are impossible.
 */
import { useEffect } from 'react'

import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'

export function MacTitleBar() {
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()

  useEffect(() => {
    if (!isMacOverlay) return
    document.documentElement.setAttribute('data-platform', 'mac-overlay')
    return () => document.documentElement.removeAttribute('data-platform')
  }, [isMacOverlay])

  if (!isMacOverlay) return null

  return (
    <div
      {...dragHandlers}
      className="fixed left-0 top-0 z-(--z-header) h-10 w-(--spacing-mac-traffic-inset) select-none"
      aria-hidden="true"
    />
  )
}
