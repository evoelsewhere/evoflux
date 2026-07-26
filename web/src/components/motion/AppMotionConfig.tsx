/**
 * Applies the Appearance → UI animations choice to the complete application
 * tree. The shared LayoutGroup also lets shell surfaces (topbar, main canvas,
 * workbench and side panels) coordinate their geometry instead of snapping
 * independently when one of them opens or closes.
 */
import type { ReactNode } from 'react'
import { LayoutGroup, MotionConfig } from 'framer-motion'

import { useMotionPreset } from '@/lib/motion'

export function AppMotionConfig({ children }: { children: ReactNode }) {
  const preset = useMotionPreset()
  return (
    <MotionConfig
      transition={preset.transition}
      reducedMotion={preset.intensity === 'reduced' ? 'always' : 'user'}
    >
      <LayoutGroup id="evoflux-app-shell">{children}</LayoutGroup>
    </MotionConfig>
  )
}
