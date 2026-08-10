export interface RenderRequest {
  request_id: string
  slide_id: string
  width: number
  height: number
  html: string
  css: string
  assets: Record<string, { mime_type: string; suffix: string }>
}

export interface EditableElement {
  kind: 'text' | 'image'
  name: string
  x: number
  y: number
  width: number
  height: number
  text?: string
  asset_id?: string
  alt?: string
  font_family?: string
  font_size?: number
  bold?: boolean
  italic?: boolean
  underline?: boolean
  color?: string
  text_align?: string
  vertical_align?: string
  line_height_ratio?: number
  rotation?: number
}

export interface RenderIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
  element?: string
}

export function parseSlideColor(value: string): string | null {
  const hex = value.match(/^#([0-9a-f]{6})$/i)
  if (hex) return `#${hex[1].toUpperCase()}`
  const rgb = value.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)$/i)
  if (!rgb || (rgb[4] !== undefined && Number(rgb[4]) < 0.999)) return null
  return `#${[rgb[1], rgb[2], rgb[3]].map((part) => Number(part).toString(16).padStart(2, '0')).join('').toUpperCase()}`
}

function px(value: string, fallback = 0): number {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function cssEffectEnabled(value: string | undefined): boolean {
  if (!value || ['none', 'initial', 'unset'].includes(value)) return false
  if (/^rgba\([^)]*,\s*0\s*\)$/i.test(value)) return false
  return true
}

function relativeRect(element: Element, root: HTMLElement) {
  const rect = element.getBoundingClientRect()
  const rootRect = root.getBoundingClientRect()
  return {
    x: rect.left - rootRect.left,
    y: rect.top - rootRect.top,
    width: rect.width,
    height: rect.height,
  }
}

function hasRichTextStyling(node: HTMLElement, style: CSSStyleDeclaration): boolean {
  return Array.from(node.querySelectorAll<HTMLElement>('*')).some((child) => {
    const childStyle = child.ownerDocument.defaultView?.getComputedStyle(child)
    if (!childStyle) return true
    return childStyle.fontFamily !== style.fontFamily
      || childStyle.fontSize !== style.fontSize
      || childStyle.fontWeight !== style.fontWeight
      || childStyle.fontStyle !== style.fontStyle
      || childStyle.textDecorationLine !== style.textDecorationLine
      || childStyle.color !== style.color
      || childStyle.letterSpacing !== style.letterSpacing
  })
}

export function collectEditableElements(
  root: HTMLElement,
  request: RenderRequest,
): { elements: EditableElement[]; issues: RenderIssue[]; hidden: Element[] } {
  const elements: EditableElement[] = []
  const issues: RenderIssue[] = []
  const hidden: Element[] = []
  const nodes = Array.from(root.querySelectorAll<HTMLElement>('[data-pptx-editable]'))
  nodes.forEach((node, index) => {
    const kind = node.dataset.pptxEditable
    const name = node.dataset.pptxName || `${kind || 'element'}-${index + 1}`
    const rect = relativeRect(node, root)
    if (rect.width <= 0 || rect.height <= 0) {
      issues.push({ severity: 'warning', code: 'empty-editable-element', message: `${name} has no visible area.`, element: name })
      return
    }
    if (rect.x < -0.5 || rect.y < -0.5 || rect.x + rect.width > request.width + 0.5 || rect.y + rect.height > request.height + 0.5) {
      issues.push({ severity: 'error', code: 'editable-element-overflow', message: `${name} extends outside the slide.`, element: name })
      return
    }
    const style = node.ownerDocument.defaultView?.getComputedStyle(node)
    if (!style) return
    if (kind === 'text') {
      const color = parseSlideColor(style.color)
      const unsupported: string[] = []
      if (cssEffectEnabled(style.transform)) unsupported.push('transform')
      if (cssEffectEnabled(style.filter)) unsupported.push('filter')
      if (cssEffectEnabled(style.textShadow)) unsupported.push(`text-shadow (${style.textShadow})`)
      if (style.webkitBackgroundClip === 'text') unsupported.push('background-clip')
      if (color === null) unsupported.push('non-solid color')
      if (!['normal', '0px'].includes(style.letterSpacing)) unsupported.push('letter-spacing')
      if (style.textTransform !== 'none') unsupported.push('text-transform')
      if (style.writingMode !== 'horizontal-tb') unsupported.push('writing-mode')
      if (Number(style.opacity) < 0.999) unsupported.push('opacity')
      if (style.mixBlendMode !== 'normal') unsupported.push('mix-blend-mode')
      if (cssEffectEnabled(style.clipPath)) unsupported.push('clip-path')
      if (px(style.webkitTextStrokeWidth) > 0) unsupported.push('text-stroke')
      if (hasRichTextStyling(node, style)) unsupported.push('mixed inline text styling')
      if (unsupported.length) {
        issues.push({ severity: 'warning', code: 'editable-text-flattened', message: `${name} uses ${unsupported.join(', ')} which PowerPoint cannot preserve and remains in the visual shell.`, element: name })
        return
      }
      const fontSize = px(style.fontSize, 24)
      if (fontSize < 21.33) {
        issues.push({ severity: 'warning', code: 'small-slide-text', message: `${name} is smaller than the 16pt presentation baseline.`, element: name })
      }
      const lineHeight = style.lineHeight === 'normal' ? fontSize * 1.2 : px(style.lineHeight, fontSize * 1.2)
      elements.push({
        kind: 'text',
        name,
        ...rect,
        text: node.innerText || node.textContent || '',
        font_family: style.fontFamily,
        font_size: fontSize,
        bold: Number.parseInt(style.fontWeight, 10) >= 600 || style.fontWeight === 'bold',
        italic: style.fontStyle === 'italic',
        underline: style.textDecorationLine.includes('underline'),
        color: color ?? '#111827',
        text_align: style.textAlign,
        vertical_align: node.dataset.pptxVerticalAlign || 'top',
        line_height_ratio: Math.max(0.8, Math.min(3, lineHeight / fontSize)),
        rotation: 0,
      })
      hidden.push(node)
      return
    }
    if (kind === 'image') {
      const assetId = node.dataset.pptxAsset || ''
      const asset = request.assets[assetId]
      const objectFit = style.objectFit || 'fill'
      const hasVisualEffect = objectFit !== 'fill'
        || cssEffectEnabled(style.transform)
        || cssEffectEnabled(style.filter)
        || cssEffectEnabled(style.clipPath)
        || cssEffectEnabled(style.maskImage)
        || style.borderRadius.split(' ').some((value) => px(value) > 0)
        || Number(style.opacity) < 0.999
        || style.mixBlendMode !== 'normal'
      if (!asset || !asset.mime_type.startsWith('image/') || asset.mime_type === 'image/svg+xml' || hasVisualEffect) {
        issues.push({ severity: 'warning', code: 'editable-image-flattened', message: `${name} cannot be reproduced as a native raster image without visual drift and remains in the visual shell.`, element: name })
        return
      }
      elements.push({
        kind: 'image',
        name,
        ...rect,
        asset_id: assetId,
        alt: node.getAttribute('alt') || name,
      })
      hidden.push(node)
      return
    }
    issues.push({ severity: 'warning', code: 'unknown-editable-kind', message: `${name} requested unsupported editability kind ${kind}.`, element: name })
  })
  return { elements, issues, hidden }
}
