import { afterEach, describe, expect, it, vi } from 'vitest'
import { rasterizeSlideElement } from '@/components/artifacts/safe-slide-canvas'

function canvasContext() {
  const noop = vi.fn()
  return {
    beginPath: noop,
    clip: noop,
    closePath: noop,
    createLinearGradient: vi.fn(() => ({ addColorStop: noop })),
    createRadialGradient: vi.fn(() => ({ addColorStop: noop })),
    drawImage: noop,
    ellipse: noop,
    fill: noop,
    fillText: noop,
    globalAlpha: 1,
    lineTo: noop,
    moveTo: noop,
    quadraticCurveTo: noop,
    restore: noop,
    save: noop,
    scale: noop,
    setLineDash: noop,
    stroke: noop,
  } as unknown as CanvasRenderingContext2D
}

describe('safe slide canvas', () => {
  afterEach(() => vi.restoreAllMocks())

  it('exports an origin-clean PNG without an SVG foreignObject round trip', async () => {
    const context = canvasContext()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
      'data:image/png;base64,c2xpZGU=',
    )
    const root = document.createElement('div')
    root.style.backgroundColor = '#ffffff'
    root.style.overflow = 'hidden'
    root.getBoundingClientRect = () => new DOMRect(0, 0, 1280, 720)
    document.body.append(root)

    const result = await rasterizeSlideElement(root, {
      width: 1280,
      height: 720,
      pixelRatio: 1,
    })

    expect(result.dataUrl).toBe('data:image/png;base64,c2xpZGU=')
    expect(result.issues).toEqual([])
    expect(context.scale).toHaveBeenCalledWith(1, 1)
    expect(HTMLCanvasElement.prototype.toDataURL).toHaveBeenCalledWith('image/png')
    root.remove()
  })

  it('fails closed when a visual effect cannot be reproduced', async () => {
    const context = canvasContext()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
      'data:image/png;base64,c2xpZGU=',
    )
    const root = document.createElement('div')
    root.style.boxShadow = '0 4px 12px rgb(0 0 0 / 25%)'
    root.getBoundingClientRect = () => new DOMRect(0, 0, 1280, 720)
    document.body.append(root)

    const result = await rasterizeSlideElement(root, {
      width: 1280,
      height: 720,
      pixelRatio: 1,
    })

    expect(result.issues).toContainEqual(expect.objectContaining({
      severity: 'error',
      code: 'unsupported-canvas-effect',
      element: 'div',
    }))
    root.remove()
  })
})
