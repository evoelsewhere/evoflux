/**
 * Applies the Appearance → UI animations choice to every framer-motion
 * component in the tree. Components that pass their own `transition` still
 * win; everything else inherits the user's intensity.
 */
import type { ReactNode } from 'react'
import { MotionConfig } from 'framer-motion'

import { useMotionPreset } from '@/lib/motion'

export function AppMotionConfig({ children }: { children: ReactNode }) {
  const preset = useMotionPreset()
  return (
    <MotionConfig
      transition={preset.transition}
      reducedMotion={preset.intensity === 'reduced' ? 'always' : 'user'}
    >
      {children}
    </MotionConfig>
  )
}
