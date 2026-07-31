import { useEffect } from 'react'
import { SplitViewIcon } from '@/components/ui/layout-icons'

export const AUTOMATIC_SPLIT_TRANSITION_MS = 1050
const REDUCED_MOTION_TRANSITION_MS = 180

interface AutomaticSplitTransitionProps {
  activeAgentCount: number
  onComplete: () => void
}

/**
 * Brief, non-blocking transition shown before the conversation reorganizes
 * into Split. The border carries the motion so transcript content stays still.
 */
export function AutomaticSplitTransition({
  activeAgentCount,
  onComplete,
}: AutomaticSplitTransitionProps) {
  useEffect(() => {
    const reducedMotion =
      typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const timer = window.setTimeout(
      onComplete,
      reducedMotion ? REDUCED_MOTION_TRANSITION_MS : AUTOMATIC_SPLIT_TRANSITION_MS,
    )
    return () => window.clearTimeout(timer)
  }, [onComplete])

  return (
    <div
      className="pointer-events-none absolute inset-0 z-50 overflow-hidden rounded-[inherit]"
      role="status"
      aria-label={`Organizing ${activeAgentCount} active agents into Split layout`}
    >
      <div className="oa-layout-switch-wash absolute inset-0" aria-hidden="true" />
      <div
        className="oa-layout-switch-ring oa-layout-switch-ring-blur"
        aria-hidden="true"
      />
      <div
        className="oa-layout-switch-ring"
        aria-hidden="true"
      />
      <div className="oa-layout-switch-pill absolute left-1/2 top-3 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-white/12 bg-black/65 px-3 py-1.5 text-[11px] font-medium text-white shadow-lg backdrop-blur-xl">
        <SplitViewIcon size={13} aria-hidden="true" />
        <span>Organizing {activeAgentCount} active agents</span>
      </div>
    </div>
  )
}
