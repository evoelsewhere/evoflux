import { describe, expect, it } from 'vitest'
import { reducedMotionTransition, SPRINGS } from './motion'

describe('reduced motion transition', () => {
  it('uses an effectively instant transition when reduced motion is requested', () => {
    expect(reducedMotionTransition(true, SPRINGS.fast)).toEqual({ duration: 0.01 })
    expect(reducedMotionTransition(false, SPRINGS.fast)).toBe(SPRINGS.fast)
  })
})
