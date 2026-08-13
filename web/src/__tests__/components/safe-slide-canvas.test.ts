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
    fillRect: vi.fn(),
    fillText: vi.fn(),
    globalAlpha: 1,
    lineTo: noop,
    moveTo: noop,
    measureText: vi.fn(() => ({ width: 12 })),
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

  it('paints every CSS gradient layer over an inherited opaque background', async () => {
    const context = canvasContext()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
      'data:image/png;base64,c2xpZGU=',
    )
    document.body.style.backgroundColor = '#071626'
    const root = document.createElement('div')
    root.style.backgroundImage = [
      'radial-gradient(circle at 84% 18%, rgba(61, 242, 255, 0.18), transparent 18%)',
      'linear-gradient(135deg, #06111e 0%, #102743 100%)',
    ].join(', ')
    root.getBoundingClientRect = () => new DOMRect(0, 0, 1280, 720)
    document.body.append(root)

    const result = await rasterizeSlideElement(root, {
      width: 1280,
      height: 720,
      pixelRatio: 1,
    })

    expect(result.issues).toEqual([])
    expect(context.fillRect).toHaveBeenCalledWith(0, 0, 1280, 720)
    expect(context.createLinearGradient).toHaveBeenCalledTimes(1)
    expect(context.createRadialGradient).toHaveBeenCalledTimes(1)
    root.remove()
    document.body.style.backgroundColor = ''
  })

  it('paints ordered and unordered list markers in the source preview', async () => {
    const context = canvasContext()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
      'data:image/png;base64,c2xpZGU=',
    )
    vi.spyOn(document, 'createRange').mockReturnValue({
      setStart: vi.fn(),
      setEnd: vi.fn(),
      getBoundingClientRect: vi.fn(() => new DOMRect(90, 40, 20, 20)),
      detach: vi.fn(),
    } as unknown as Range)
    const root = document.createElement('div')
    root.innerHTML = '<ol start="3"><li>Third</li></ol><ul><li>Bullet</li></ul>'
    root.getBoundingClientRect = () => new DOMRect(0, 0, 1280, 720)
    Array.from(root.querySelectorAll('ol,ul')).forEach((list, index) => {
      list.getBoundingClientRect = () => new DOMRect(60, 30 + index * 50, 500, 42)
    })
    Array.from(root.querySelectorAll('li')).forEach((item, index) => {
      item.getBoundingClientRect = () => new DOMRect(80, 40 + index * 50, 400, 32)
    })
    document.body.append(root)

    await rasterizeSlideElement(root, { width: 1280, height: 720, pixelRatio: 1 })

    expect(context.fillText).toHaveBeenCalledWith('3.', expect.any(Number), 40)
    expect(context.fillText).toHaveBeenCalledWith('•', expect.any(Number), 90)
    root.remove()
  })
})
