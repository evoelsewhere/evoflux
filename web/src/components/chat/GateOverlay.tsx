/**
 * GateOverlay — docked card for the gates that block a run (ask_user,
 * permission approval). It grows upward from the top edge of the composer, so
 * the question rises out of the chat input instead of covering the middle of
 * the canvas. The mount point (`GateDock`) is a zero-height slot directly above
 * the composer, so opening a gate never reflows the transcript or the
 * composer, and the transcript and sidebar stay usable underneath.
 */
import { forwardRef, type ReactNode } from 'react'
import { motion } from 'framer-motion'

import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

/** Zero-height slot placed immediately above the composer; gates anchor to it. */
export function GateDock({ children }: { children: ReactNode }) {
  return <div className="pointer-events-none relative z-(--z-overlay) h-0 shrink-0">{children}</div>
}

export const GateOverlay = forwardRef<
  HTMLDivElement,
  {
    label: string
    className?: string
    children: ReactNode
  }
>(function GateOverlay({ label, className, children }, ref) {
  const preset = useMotionPreset()

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={preset.spring}
      className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-4 pb-2"
    >
      <motion.div
        role="dialog"
        aria-label={label}
        initial={{ opacity: 0, y: 16 * preset.distance }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 16 * preset.distance }}
        transition={preset.spring}
        className={cn(
          'pointer-events-auto flex max-h-[min(60vh,32rem)] w-full flex-col',
          className,
        )}
      >
        {children}
      </motion.div>
    </motion.div>
  )
})
