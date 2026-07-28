/**
 * BlockEnter — intensity-aware fade-rise for transcript / list mounts.
 * Animates once on mount; children can stream without re-triggering motion.
 */
import { motion, type HTMLMotionProps } from 'framer-motion'
import type { HTMLAttributes, ReactNode } from 'react'

import { fadeRise, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

export interface BlockEnterProps extends Omit<HTMLMotionProps<'div'>, 'children'> {
  children: ReactNode
  /** Base travel in px before intensity distance multiplier. Default 6. */
  basePx?: number
  /** Skip enter animation (e.g. historical hydrate). */
  disabled?: boolean
}

export function BlockEnter({
  children,
  className,
  basePx = 6,
  disabled = false,
  ...rest
}: BlockEnterProps) {
  const preset = useMotionPreset()
  const rise = fadeRise(preset, basePx)

  if (disabled || preset.intensity === 'reduced') {
    return (
      <div className={className} {...(rest as HTMLAttributes<HTMLDivElement>)}>
        {children}
      </div>
    )
  }

  return (
    <motion.div
      className={cn(className)}
      initial={rise.initial}
      animate={rise.animate}
      transition={rise.transition}
      {...rest}
    >
      {children}
    </motion.div>
  )
}
