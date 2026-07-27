/**
 * ListEnter — BlockEnter with per-index stagger delay from the motion preset.
 */
import type { ReactNode } from 'react'

import { BlockEnter, type BlockEnterProps } from './BlockEnter'
import { staggerDelay, useMotionPreset } from '@/lib/motion'

export interface ListEnterProps extends Omit<BlockEnterProps, 'style'> {
  children: ReactNode
  index: number
}

export function ListEnter({ children, index, ...rest }: ListEnterProps) {
  const preset = useMotionPreset()
  const delay = staggerDelay(preset, index)

  return (
    <BlockEnter
      {...rest}
      transition={{
        ...preset.transition,
        delay,
      }}
    >
      {children}
    </BlockEnter>
  )
}
