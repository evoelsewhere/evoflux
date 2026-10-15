import { describe, expect, it } from 'vitest'
import { calculateSceneCameraDistance } from '@/lib/visual-artifact-three-runtime'

describe('3D scene camera framing', () => {
  it('moves back to fit a larger scene', () => {
    expect(calculateSceneCameraDistance(40, 42, 16 / 9)).toBeGreaterThan(
      calculateSceneCameraDistance(2, 42, 16 / 9),
    )
  })

  it('accounts for narrow viewports without clipping the horizontal extent', () => {
    expect(calculateSceneCameraDistance(4, 42, 0.5)).toBeGreaterThan(
      calculateSceneCameraDistance(4, 42, 1.8),
    )
  })
})
