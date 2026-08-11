import type { RenderIssue } from './slide-editable'

export interface SlideCanvasOptions {
  width: number
  height: number
  pixelRatio: number
}

export interface SlideCanvasResult {
  dataUrl: string
  issues: RenderIssue[]
}

interface RelativeRect {
  x: number
  y: number
  width: number
  height: number
}

const TRANSPARENT = /^(?:transparent|rgba\([^)]*,\s*0(?:\.0+)?\s*\))$/i

function px(value: string, fallback = 0): number {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function relativeRect(element: Element, rootRect: DOMRect): RelativeRect {
  const rect = element.getBoundingClientRect()
  return {
    x: rect.left - rootRect.left,
    y: rect.top - rootRect.top,
    width: rect.width,
    height: rect.height,
  }
}

function roundedPath(
  context: CanvasRenderingContext2D,
  rect: RelativeRect,
  radii: [number, number, number, number],
) {
  const [topLeft, topRight, bottomRight, bottomLeft] = radii.map((radius) => (
    Math.max(0, Math.min(radius, rect.width / 2, rect.height / 2))
  )) as [number, number, number, number]
  const right = rect.x + rect.width
  const bottom = rect.y + rect.height
  context.beginPath()
  context.moveTo(rect.x + topLeft, rect.y)
  context.lineTo(right - topRight, rect.y)
  context.quadraticCurveTo(right, rect.y, right, rect.y + topRight)
  context.lineTo(right, bottom - bottomRight)
  context.quadraticCurveTo(right, bottom, right - bottomRight, bottom)
  context.lineTo(rect.x + bottomLeft, bottom)
  context.quadraticCurveTo(rect.x, bottom, rect.x, bottom - bottomLeft)
  context.lineTo(rect.x, rect.y + topLeft)
  context.quadraticCurveTo(rect.x, rect.y, rect.x + topLeft, rect.y)
  context.closePath()
}

function elementRadii(style: CSSStyleDeclaration): [number, number, number, number] {
  return [
    px(style.borderTopLeftRadius),
    px(style.borderTopRightRadius),
    px(style.borderBottomRightRadius),
    px(style.borderBottomLeftRadius),
  ]
}

function splitCssList(value: string): string[] {
  const values: string[] = []
  let depth = 0
  let start = 0
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === '(') depth += 1
    if (value[index] === ')') depth -= 1
    if (value[index] === ',' && depth === 0) {
      values.push(value.slice(start, index).trim())
      start = index + 1
    }
  }
  values.push(value.slice(start).trim())
  return values.filter(Boolean)
}

function gradientFill(
  context: CanvasRenderingContext2D,
  value: string,
  rect: RelativeRect,
): CanvasGradient | null {
  const linear = value.match(/^linear-gradient\((.*)\)$/i)
  const radial = value.match(/^radial-gradient\((.*)\)$/i)
  if (!linear && !radial) return null
  const parts = splitCssList((linear ?? radial)?.[1] ?? '')
  let angle = 180
  if (linear && /(?:deg|turn)$/.test(parts[0] ?? '')) {
    const direction = parts.shift() ?? '180deg'
    angle = direction.endsWith('turn')
      ? px(direction) * 360
      : px(direction, 180)
  }
  const gradient = linear
    ? (() => {
        const radians = (angle - 90) * Math.PI / 180
        const centerX = rect.x + rect.width / 2
        const centerY = rect.y + rect.height / 2
        const radius = Math.abs(rect.width * Math.cos(radians)) / 2
          + Math.abs(rect.height * Math.sin(radians)) / 2
        return context.createLinearGradient(
          centerX - Math.cos(radians) * radius,
          centerY - Math.sin(radians) * radius,
          centerX + Math.cos(radians) * radius,
          centerY + Math.sin(radians) * radius,
        )
      })()
    : context.createRadialGradient(
        rect.x + rect.width / 2,
        rect.y + rect.height / 2,
        0,
        rect.x + rect.width / 2,
        rect.y + rect.height / 2,
        Math.max(rect.width, rect.height) / 2,
      )
  const stops = parts.filter((part) => !/^(?:circle|ellipse|closest|farthest|at\s)/i.test(part))
  stops.forEach((stop, index) => {
    const match = stop.match(/^(.*?)(?:\s+(-?[\d.]+)%?)?$/)
    const color = match?.[1]?.trim() ?? stop
    const explicit = match?.[2] === undefined ? null : Number(match[2]) / 100
    try {
      gradient.addColorStop(
        Math.max(0, Math.min(1, explicit ?? index / Math.max(stops.length - 1, 1))),
        color,
      )
    } catch {
      // The caller records one unsupported-background issue.
    }
  })
  return gradient
}

function recordIssue(
  issues: RenderIssue[],
  seen: Set<string>,
  issue: RenderIssue,
) {
  const key = `${issue.code}:${issue.element ?? ''}`
  if (seen.has(key)) return
  seen.add(key)
  issues.push(issue)
}

function paintBackground(
  context: CanvasRenderingContext2D,
  rect: RelativeRect,
  style: CSSStyleDeclaration,
  issues: RenderIssue[],
  seen: Set<string>,
  elementName: string,
) {
  const radii = elementRadii(style)
  const color = style.backgroundColor
  const image = style.backgroundImage
  if (color && !TRANSPARENT.test(color)) {
    roundedPath(context, rect, radii)
    context.fillStyle = color
    context.fill()
  }
  if (image && image !== 'none') {
    const gradient = gradientFill(context, image, rect)
    if (gradient) {
      roundedPath(context, rect, radii)
      context.fillStyle = gradient
      context.fill()
    } else {
      recordIssue(issues, seen, {
        severity: 'error',
        code: 'unsupported-canvas-background',
        message: `${elementName} uses a background image the built-in rasterizer cannot reproduce.`,
        element: elementName,
      })
    }
  }
}

function paintBorder(
  context: CanvasRenderingContext2D,
  rect: RelativeRect,
  style: CSSStyleDeclaration,
) {
  const sides = [
    ['top', style.borderTopWidth, style.borderTopStyle, style.borderTopColor],
    ['right', style.borderRightWidth, style.borderRightStyle, style.borderRightColor],
    ['bottom', style.borderBottomWidth, style.borderBottomStyle, style.borderBottomColor],
    ['left', style.borderLeftWidth, style.borderLeftStyle, style.borderLeftColor],
  ] as const
  for (const [side, widthValue, lineStyle, color] of sides) {
    const width = px(widthValue)
    if (width <= 0 || lineStyle === 'none' || TRANSPARENT.test(color)) continue
    context.save()
    context.strokeStyle = color
    context.lineWidth = width
    context.setLineDash(lineStyle === 'dashed' ? [6, 4] : lineStyle === 'dotted' ? [2, 3] : [])
    context.beginPath()
    if (side === 'top') {
      context.moveTo(rect.x, rect.y + width / 2)
      context.lineTo(rect.x + rect.width, rect.y + width / 2)
    } else if (side === 'right') {
      context.moveTo(rect.x + rect.width - width / 2, rect.y)
      context.lineTo(rect.x + rect.width - width / 2, rect.y + rect.height)
    } else if (side === 'bottom') {
      context.moveTo(rect.x, rect.y + rect.height - width / 2)
      context.lineTo(rect.x + rect.width, rect.y + rect.height - width / 2)
    } else {
      context.moveTo(rect.x + width / 2, rect.y)
      context.lineTo(rect.x + width / 2, rect.y + rect.height)
    }
    context.stroke()
    context.restore()
  }
}

function transformedText(value: string, transform: string): string {
  if (transform === 'uppercase') return value.toUpperCase()
  if (transform === 'lowercase') return value.toLowerCase()
  if (transform === 'capitalize') return value.replace(/\b\p{L}/gu, (letter) => letter.toUpperCase())
  return value
}

function textSegments(node: Text): Array<{ value: string; rect: DOMRect }> {
  const document = node.ownerDocument
  const segments: Array<{ value: string; rect: DOMRect }> = []
  let active: { value: string; rect: DOMRect } | null = null
  for (let index = 0; index < node.data.length; index += 1) {
    const range = document.createRange()
    range.setStart(node, index)
    range.setEnd(node, index + 1)
    const rect = range.getBoundingClientRect()
    range.detach()
    if (rect.width <= 0 || rect.height <= 0) continue
    const value = node.data[index]
    if (
      active
      && Math.abs(active.rect.top - rect.top) < 0.75
      && Math.abs(active.rect.right - rect.left) < 1.5
    ) {
      active.value += value
      active.rect = new DOMRect(
        active.rect.x,
        active.rect.y,
        rect.right - active.rect.left,
        Math.max(active.rect.height, rect.height),
      )
    } else {
      active = { value, rect }
      segments.push(active)
    }
  }
  return segments
}

function paintTextNode(
  context: CanvasRenderingContext2D,
  node: Text,
  rootRect: DOMRect,
  parentStyle: CSSStyleDeclaration,
) {
  if (!node.data.trim() || TRANSPARENT.test(parentStyle.color)) return
  context.save()
  context.fillStyle = parentStyle.color
  context.font = parentStyle.font || [
    parentStyle.fontStyle,
    parentStyle.fontWeight,
    parentStyle.fontSize,
    parentStyle.fontFamily,
  ].join(' ')
  context.textBaseline = 'top'
  const canvasText = context as CanvasRenderingContext2D & { letterSpacing?: string }
  if ('letterSpacing' in canvasText) canvasText.letterSpacing = parentStyle.letterSpacing
  for (const segment of textSegments(node)) {
    const value = transformedText(segment.value, parentStyle.textTransform)
    const x = segment.rect.left - rootRect.left
    const y = segment.rect.top - rootRect.top
    context.fillText(value, x, y, Math.max(1, segment.rect.width + 1))
    const decoration = parentStyle.textDecorationLine
    context.strokeStyle = parentStyle.textDecorationColor || parentStyle.color
    context.lineWidth = Math.max(1, px(parentStyle.textDecorationThickness, 1))
    if (decoration.includes('underline')) {
      context.beginPath()
      context.moveTo(x, y + segment.rect.height - 1)
      context.lineTo(x + segment.rect.width, y + segment.rect.height - 1)
      context.stroke()
    }
    if (decoration.includes('line-through')) {
      context.beginPath()
      context.moveTo(x, y + segment.rect.height * 0.52)
      context.lineTo(x + segment.rect.width, y + segment.rect.height * 0.52)
      context.stroke()
    }
  }
  context.restore()
}

async function loadSvg(svg: SVGSVGElement): Promise<HTMLImageElement> {
  const serialized = new XMLSerializer().serializeToString(svg)
  const source = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(serialized)}`
  const image = new Image()
  image.decoding = 'async'
  image.src = source
  await new Promise<void>((resolve, reject) => {
    image.addEventListener('load', () => resolve(), { once: true })
    image.addEventListener('error', () => reject(new Error('Inline SVG failed to load.')), { once: true })
  })
  return image
}

function drawContainedImage(
  context: CanvasRenderingContext2D,
  source: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
  rect: RelativeRect,
  objectFit: string,
) {
  if (objectFit === 'fill' || sourceWidth <= 0 || sourceHeight <= 0) {
    context.drawImage(source, rect.x, rect.y, rect.width, rect.height)
    return
  }
  const contain = objectFit !== 'cover'
  const scale = contain
    ? Math.min(rect.width / sourceWidth, rect.height / sourceHeight)
    : Math.max(rect.width / sourceWidth, rect.height / sourceHeight)
  const width = sourceWidth * scale
  const height = sourceHeight * scale
  context.drawImage(
    source,
    rect.x + (rect.width - width) / 2,
    rect.y + (rect.height - height) / 2,
    width,
    height,
  )
}

async function paintElement(
  context: CanvasRenderingContext2D,
  element: HTMLElement | SVGSVGElement,
  rootRect: DOMRect,
  issues: RenderIssue[],
  seen: Set<string>,
) {
  const view = element.ownerDocument.defaultView
  const style = view?.getComputedStyle(element)
  if (!style || style.display === 'none' || style.visibility === 'hidden' || px(style.opacity, 1) <= 0) return
  const rect = relativeRect(element, rootRect)
  if (rect.width <= 0 || rect.height <= 0) return
  const elementName = (element as HTMLElement).dataset?.pptxName
    || element.getAttribute('aria-label')
    || element.id
    || element.tagName.toLowerCase()
  const unsupported = [
    ['transform', style.transform],
    ['filter', style.filter],
    ['clip-path', style.clipPath],
    ['mix-blend-mode', style.mixBlendMode === 'normal' ? 'none' : style.mixBlendMode],
    ['mask', style.maskImage],
    ['box-shadow', style.boxShadow],
    ['text-shadow', style.textShadow],
  ].filter(([property, value]) => (
    value
    && !['none', 'initial', 'unset'].includes(value)
    && !(property === 'text-shadow' && TRANSPARENT.test(value))
  ))
  for (const [property] of unsupported) {
    recordIssue(issues, seen, {
      severity: 'error',
      code: 'unsupported-canvas-effect',
      message: `${elementName} uses ${property}, which the built-in rasterizer cannot reproduce exactly.`,
      element: elementName,
    })
  }
  context.save()
  context.globalAlpha *= Math.max(0, Math.min(1, px(style.opacity, 1)))
  paintBackground(context, rect, style, issues, seen, elementName)
  paintBorder(context, rect, style)
  if (style.overflow === 'hidden' || style.overflowX === 'hidden' || style.overflowY === 'hidden') {
    roundedPath(context, rect, elementRadii(style))
    context.clip()
  }

  if (element.tagName.toLowerCase() === 'svg') {
    try {
      const image = await loadSvg(element as SVGSVGElement)
      context.drawImage(image, rect.x, rect.y, rect.width, rect.height)
    } catch (error) {
      recordIssue(issues, seen, {
        severity: 'error',
        code: 'inline-svg-raster-failed',
        message: error instanceof Error ? error.message : String(error),
        element: elementName,
      })
    }
    context.restore()
    return
  }

  if (element.tagName.toLowerCase() === 'img') {
    const imageElement = element as HTMLImageElement
    if (!imageElement.src.startsWith('data:')) {
      recordIssue(issues, seen, {
        severity: 'error',
        code: 'external-slide-image',
        message: `${elementName} is not an inlined data-URI image.`,
        element: elementName,
      })
    } else if (imageElement.complete && imageElement.naturalWidth > 0) {
      drawContainedImage(
        context,
        imageElement,
        imageElement.naturalWidth,
        imageElement.naturalHeight,
        rect,
        style.objectFit || 'fill',
      )
    }
    context.restore()
    return
  }

  if (element.tagName.toLowerCase() === 'canvas') {
    context.drawImage(element as HTMLCanvasElement, rect.x, rect.y, rect.width, rect.height)
    context.restore()
    return
  }

  for (const child of Array.from(element.childNodes)) {
    if (child.nodeType === 3) {
      paintTextNode(context, child as Text, rootRect, style)
    } else if (child.nodeType === 1) {
      await paintElement(context, child as HTMLElement, rootRect, issues, seen)
    }
  }
  context.restore()
}

/**
 * Paint a laid-out slide without SVG foreignObject.
 *
 * Browser layout remains the source of geometry, but every pixel is drawn from
 * origin-clean primitives.  This keeps WKWebView canvases exportable and makes
 * unsupported CSS an explicit, fail-closed artifact issue.
 */
export async function rasterizeSlideElement(
  root: HTMLElement,
  options: SlideCanvasOptions,
): Promise<SlideCanvasResult> {
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(options.width * options.pixelRatio)
  canvas.height = Math.round(options.height * options.pixelRatio)
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Slide canvas context is unavailable.')
  context.scale(options.pixelRatio, options.pixelRatio)
  const issues: RenderIssue[] = []
  await paintElement(context, root, root.getBoundingClientRect(), issues, new Set())
  try {
    return { dataUrl: canvas.toDataURL('image/png'), issues }
  } catch (error) {
    throw new Error(
      `Built-in slide canvas export failed: ${error instanceof Error ? error.message : String(error)}`,
    )
  }
}
