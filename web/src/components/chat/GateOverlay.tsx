/**
 * GateOverlay — modal layer for the gates that block a run (ask_user,
 * permission approval). It sits absolutely over the chat canvas (`<main>` is
 * the positioned ancestor), so opening one never reflows the transcript or
 * the composer, and the sidebar stays usable for switching sessions.
 */
import { forwardRef, type ReactNode } from 'react'
import { motion } from 'framer-motion'

import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

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
      className="absolute inset-0 z-(--z-overlay) flex items-center justify-center bg-black/10 p-4 supports-backdrop-filter:backdrop-blur-xs"
    >
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        initial={{ opacity: 0, y: 6 * preset.distance, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 6 * preset.distance, scale: 0.98 }}
        transition={preset.spring}
        className={cn('flex max-h-full w-full flex-col', className)}
      >
        {children}
      </motion.div>
    </motion.div>
  )
})
