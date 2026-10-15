import { describe, expect, it } from 'vitest'
import { getMotionExportDimensions } from '@/lib/motion-video-export'

describe('motion export dimensions', () => {
  it('keeps the source aspect ratio within the selected quality preset', () => {
    expect(getMotionExportDimensions(1920, 1080, 'balanced')).toEqual({ width: 1280, height: 720 })
    expect(getMotionExportDimensions(1920, 1080, 'high')).toEqual({ width: 1920, height: 1080 })
  })

  it('does not upscale small canvases and rounds output to encoder-safe even dimensions', () => {
    expect(getMotionExportDimensions(801, 601, 'high')).toEqual({ width: 800, height: 600 })
    expect(getMotionExportDimensions(320, 180, 'high')).toEqual({ width: 320, height: 180 })
  })
})
