export interface RenderRequest {
  request_id: string
  slide_id: string
  width: number
  height: number
  html: string
  css: string
  assets: Record<string, { mime_type: string; suffix: string }>
}

export interface EditableTextPadding {
  left: number
  right: number
  top: number
  bottom: number
}

export interface EditableTextRun {
  text: string
  font_family: string
  font_size: number
  letter_spacing: number
  bold: boolean
  italic: boolean
  underline: boolean
  color: string
}

export interface EditableTextBullet {
  kind: 'bullet' | 'number'
  marker?: string
  level?: number
  start?: number
}

export interface EditableTextParagraph {
  runs: EditableTextRun[]
  bullet?: EditableTextBullet
  level?: number
}

export interface EditableElement {
  kind: 'text' | 'image'
  name: string
  role?: string
  x: number
  y: number
  width: number
  height: number
  padding?: EditableTextPadding
  paragraphs?: EditableTextParagraph[]
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

export interface FlattenedTextBlock {
  name: string
  reason: string
  characters: number
}

export interface TextCoverage {
  visible_blocks: number
  visible_characters: number
  native_blocks: number
  native_characters: number
  flattened: FlattenedTextBlock[]
}

export interface RenderIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
  element?: string
}

interface TextCandidate {
  node: HTMLElement
  explicit: boolean
}

interface RunToken {
  run: EditableTextRun
  preserveWhitespace: boolean
  hardBreak?: boolean
}

interface ParagraphExtraction {
  paragraphs: EditableTextParagraph[]
  text: string
  unsupported: string[]
}

const STRUCTURAL_TEXT_SELECTOR = 'h1,h2,h3,h4,h5,h6,p,li,dt,dd,figcaption,blockquote,td,th'
const INLINE_TEXT_SELECTOR = 'label,span'
const GENERIC_TEXT_SELECTOR = 'div,section,article,aside,header,footer,main,nav'
const EXPLICIT_TEXT_SELECTOR = '[data-pptx-editable="text"]'
const ART_TEXT_SELECTOR = '[data-pptx-text-mode="art"]'
const BLOCK_TEXT_TAGS = new Set([
  'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'P', 'LI', 'DT', 'DD', 'FIGCAPTION',
  'BLOCKQUOTE', 'TD', 'TH',
])

export function parseSlideColor(value: string): string | null {
  const normalized = value.trim()
  const named: Record<string, string> = {
    black: '#000000',
    white: '#FFFFFF',
  }
  if (named[normalized.toLowerCase()]) return named[normalized.toLowerCase()]
  const hex = normalized.match(/^#([0-9a-f]{6})$/i)
  if (hex) return `#${hex[1].toUpperCase()}`
  if (!/^rgba?\(/i.test(normalized)) return null
  const parts = normalized.match(/[\d.]+/g)?.map(Number) ?? []
  if (parts.length < 3 || parts.slice(0, 3).some((part) => part < 0 || part > 255)) return null
  if (parts[3] !== undefined && parts[3] < 0.999) return null
  return `#${parts.slice(0, 3).map((part) => Math.round(part).toString(16).padStart(2, '0')).join('').toUpperCase()}`
}

function px(value: string | undefined, fallback = 0): number {
  const parsed = Number.parseFloat(value ?? '')
  return Number.isFinite(parsed) ? parsed : fallback
}

function pptxFontFamily(value: string | undefined): string {
  const source = value?.trim() || 'Arial'
  let quoted = false
  let quote = ''
  let family = ''
  for (const character of source) {
    if ((character === '"' || character === "'") && (!quoted || character === quote)) {
      quoted = !quoted
      quote = quoted ? character : ''
      continue
    }
    if (character === ',' && !quoted) break
    family += character
  }
  const normalized = family.trim() || 'Arial'
  return {
    'sans-serif': 'Arial',
    'system-ui': 'Arial',
    '-apple-system': 'Arial',
    'serif': 'Georgia',
    'monospace': 'Courier New',
  }[normalized.toLowerCase()] ?? normalized
}

function cssEffectEnabled(value: string | undefined): boolean {
  if (!value || ['none', 'initial', 'unset', 'normal'].includes(value)) return false
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

function queryIncludingRoot(root: HTMLElement, selector: string): HTMLElement[] {
  const nodes = Array.from(root.querySelectorAll<HTMLElement>(selector))
  return root.matches(selector) ? [root, ...nodes] : nodes
}

function isRendered(element: Element, stop: Element): boolean {
  let current: Element | null = element
  while (current) {
    const style = current.ownerDocument.defaultView?.getComputedStyle(current)
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false
    const opacity = Number.parseFloat(style.opacity || '1')
    if (Number.isFinite(opacity) && opacity <= 0) return false
    if (current === stop) break
    current = current.parentElement
  }
  return true
}

function hasText(element: HTMLElement): boolean {
  return Boolean(element.textContent?.replace(/\s+/g, ' ').trim())
}

function hasDirectText(element: HTMLElement): boolean {
  return Array.from(element.childNodes).some((node) => (
    node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.replace(/\s+/g, ' ').trim())
  ))
}

function elementDepth(element: HTMLElement): number {
  let depth = 0
  let current = element.parentElement
  while (current) {
    depth += 1
    current = current.parentElement
  }
  return depth
}

function hasUnclaimedText(
  source: HTMLElement,
  node: Node,
  claimed: Set<HTMLElement>,
): boolean {
  if (node.nodeType === Node.TEXT_NODE) {
    return Boolean(node.textContent?.replace(/\s+/g, ' ').trim())
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return false
  const element = node as HTMLElement
  if (element !== source && claimed.has(element)) return false
  if (element !== source && (element.matches('script,style') || element.getAttribute('aria-hidden') === 'true')) return false
  if (!isRendered(element, source)) return false
  return Array.from(element.childNodes).some((child) => hasUnclaimedText(source, child, claimed))
}

function documentOrder(left: TextCandidate, right: TextCandidate): number {
  if (left.node === right.node) return 0
  const position = left.node.compareDocumentPosition(right.node)
  return position & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1
}

function textCandidates(root: HTMLElement): TextCandidate[] {
  const explicit = queryIncludingRoot(root, EXPLICIT_TEXT_SELECTOR)
  const explicitSet = new Set(explicit)
  const structural = queryIncludingRoot(root, STRUCTURAL_TEXT_SELECTOR).filter((node) => {
    if (!hasText(node) || explicitSet.has(node)) return false
    if (node.matches('[data-slide-root]')) return false
    if (node.closest(EXPLICIT_TEXT_SELECTOR) || node.querySelector(EXPLICIT_TEXT_SELECTOR)) return false
    const listItem = node.closest('li')
    if (listItem && listItem !== node) return false
    if (node.tagName === 'LI') return true
    return !Array.from(node.querySelectorAll<HTMLElement>(STRUCTURAL_TEXT_SELECTOR))
      .some((child) => hasText(child))
  })
  const structuralSet = new Set(structural)
  const inline = queryIncludingRoot(root, INLINE_TEXT_SELECTOR).filter((node) => {
    if (!hasText(node) || explicitSet.has(node)) return false
    if (node.matches('[data-slide-root]')) return false
    if (node.closest(EXPLICIT_TEXT_SELECTOR) || node.querySelector(EXPLICIT_TEXT_SELECTOR)) return false
    let ancestor = node.parentElement
    while (ancestor && ancestor !== root.parentElement) {
      if (structuralSet.has(ancestor) || ancestor.matches(INLINE_TEXT_SELECTOR)) return false
      if (ancestor === root) break
      ancestor = ancestor.parentElement
    }
    return true
  })
  const owned = new Set([...explicit, ...structural, ...inline])
  const genericPool = queryIncludingRoot(root, GENERIC_TEXT_SELECTOR).filter((node) => {
    if (!hasText(node) || owned.has(node)) return false
    if (node.matches('[data-slide-root]')) return false
    if (node.closest(EXPLICIT_TEXT_SELECTOR)) return false
    if (node.closest('li') && !node.matches('li')) return false
    return true
  })
  const claimed = new Set(owned)
  const generic: HTMLElement[] = []
  genericPool
    .sort((left, right) => elementDepth(right) - elementDepth(left))
    .forEach((node) => {
      if (!hasDirectText(node) && !hasUnclaimedText(node, node, claimed)) return
      generic.push(node)
      claimed.add(node)
    })
  const values = [
    ...explicit.map((node) => ({ node, explicit: true })),
    ...structural.map((node) => ({ node, explicit: false })),
    ...inline.map((node) => ({ node, explicit: false })),
    ...generic.map((node) => ({ node, explicit: false })),
  ]
  const unique = new Map<HTMLElement, TextCandidate>()
  values.forEach((candidate) => unique.set(candidate.node, candidate))
  return Array.from(unique.values()).sort(documentOrder)
}

function textRole(node: HTMLElement): string {
  if (node.dataset.pptxRole) return node.dataset.pptxRole
  const tag = node.tagName.toLowerCase()
  if (/^h[1-6]$/.test(tag)) return `heading-${tag.slice(1)}`
  return {
    p: 'paragraph',
    li: 'list-item',
    dt: 'term',
    dd: 'description',
    figcaption: 'caption',
    blockquote: 'quotation',
    td: 'table-cell',
    th: 'table-header',
    label: 'label',
    span: 'inline-text',
  }[tag] ?? 'text'
}

function textName(node: HTMLElement, role: string, ordinal: number): string {
  return node.dataset.pptxName
    || node.id
    || node.getAttribute('aria-label')
    || `${role}-${ordinal}`
}

function svgTextName(node: SVGTextElement, ordinal: number): string {
  return node.dataset.pptxName
    || node.id
    || node.getAttribute('aria-label')
    || `svg-text-${ordinal}`
}

function unsupportedTextStyle(style: CSSStyleDeclaration): string[] {
  const unsupported: string[] = []
  if (cssEffectEnabled(style.transform)) unsupported.push('transform')
  if (cssEffectEnabled(style.filter)) unsupported.push('filter')
  if (cssEffectEnabled(style.textShadow)) unsupported.push(`text-shadow (${style.textShadow})`)
  if (style.webkitBackgroundClip === 'text') unsupported.push('background-clip')
  if (parseSlideColor(style.color) === null) unsupported.push('non-solid color')
  const letterSpacing = style.letterSpacing === 'normal' ? 0 : px(style.letterSpacing)
  if (letterSpacing < -32 || letterSpacing > 128) unsupported.push('letter-spacing out of range')
  if (style.textTransform && style.textTransform !== 'none') unsupported.push('text-transform')
  if (style.writingMode && style.writingMode !== 'horizontal-tb') unsupported.push('writing-mode')
  if (style.direction === 'rtl') unsupported.push('right-to-left text')
  if (Number.parseFloat(style.opacity || '1') < 0.999) unsupported.push('opacity')
  if (style.mixBlendMode && style.mixBlendMode !== 'normal') unsupported.push('mix-blend-mode')
  if (cssEffectEnabled(style.clipPath)) unsupported.push('clip-path')
  if (cssEffectEnabled(style.maskImage)) unsupported.push('mask')
  if (px(style.webkitTextStrokeWidth) > 0) unsupported.push('text-stroke')
  const decorations = style.textDecorationLine.split(/\s+/).filter(Boolean)
  if (decorations.some((value) => !['none', 'underline'].includes(value))) {
    unsupported.push('unsupported text-decoration')
  }
  return unsupported
}

function hasEmbeddedGraphic(node: HTMLElement): boolean {
  const selector = 'svg,canvas,img,picture,video,object,embed,iframe,[role="img"]'
  return node.matches(selector) || Boolean(node.querySelector(selector))
}

function foregroundOccluder(node: HTMLElement, root: HTMLElement): Element | null {
  const elementsFromPoint = node.ownerDocument.elementsFromPoint
  if (typeof elementsFromPoint !== 'function') return null
  const rect = node.getBoundingClientRect()
  const samples = [
    [0.5, 0.5],
    [0.15, 0.15],
    [0.85, 0.15],
    [0.15, 0.85],
    [0.85, 0.85],
  ]
  for (const [horizontal, vertical] of samples) {
    const hits = elementsFromPoint.call(
      node.ownerDocument,
      rect.left + rect.width * horizontal,
      rect.top + rect.height * vertical,
    )
    const relatedIndex = hits.findIndex((hit) => (
      hit === node || node.contains(hit) || hit.contains(node)
    ))
    if (relatedIndex < 0) continue
    const occluder = hits.slice(0, relatedIndex).find((hit) => {
      if (hit === node || node.contains(hit) || hit.contains(node)) return false
      return isRendered(hit, root)
    })
    if (occluder) return occluder
  }
  return null
}

function textRun(style: CSSStyleDeclaration, text: string): EditableTextRun {
  const fontWeight = Number.parseInt(style.fontWeight, 10)
  return {
    text,
    font_family: pptxFontFamily(style.fontFamily),
    font_size: px(style.fontSize, 24),
    letter_spacing: style.letterSpacing === 'normal' ? 0 : px(style.letterSpacing),
    bold: Number.isFinite(fontWeight) ? fontWeight >= 600 : ['bold', 'bolder'].includes(style.fontWeight),
    italic: style.fontStyle === 'italic' || style.fontStyle === 'oblique',
    underline: style.textDecorationLine.includes('underline'),
    color: parseSlideColor(style.color) ?? '#111827',
  }
}

function appendTextTokens(
  source: HTMLElement,
  node: Node,
  tokens: RunToken[],
  unsupported: Set<string>,
  claimed: Set<HTMLElement>,
) {
  if (node.nodeType === Node.TEXT_NODE) {
    const parent = node.parentElement
    if (!parent || !node.textContent || !isRendered(parent, source)) return
    const style = parent.ownerDocument.defaultView?.getComputedStyle(parent)
    if (!style) return
    unsupportedTextStyle(style).forEach((value) => unsupported.add(value))
    tokens.push({
      run: textRun(style, node.textContent),
      preserveWhitespace: /^(?:pre|pre-wrap|break-spaces)$/.test(style.whiteSpace),
    })
    return
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return
  const element = node as HTMLElement
  if (element !== source && claimed.has(element)) return
  if (element !== source && (element.matches('script,style') || element.getAttribute('aria-hidden') === 'true')) return
  if (source.tagName === 'LI' && element !== source && element.matches('ul,ol')) return
  if (!isRendered(element, source)) return
  const style = element.ownerDocument.defaultView?.getComputedStyle(element)
  if (style) unsupportedTextStyle(style).forEach((value) => unsupported.add(value))
  if (element.tagName === 'BR') {
    const parentStyle = element.parentElement?.ownerDocument.defaultView?.getComputedStyle(element.parentElement)
    if (parentStyle) {
      tokens.push({ run: textRun(parentStyle, '\n'), preserveWhitespace: true, hardBreak: true })
    }
    return
  }
  const nestedBlock = element !== source && BLOCK_TEXT_TAGS.has(element.tagName)
  if (nestedBlock && tokens.length && !tokens.at(-1)?.hardBreak) {
    const parentStyle = element.parentElement?.ownerDocument.defaultView?.getComputedStyle(element.parentElement)
    if (parentStyle) tokens.push({ run: textRun(parentStyle, '\n'), preserveWhitespace: true, hardBreak: true })
  }
  Array.from(element.childNodes).forEach((child) => appendTextTokens(source, child, tokens, unsupported, claimed))
  if (nestedBlock && tokens.length && !tokens.at(-1)?.hardBreak) {
    const blockStyle = element.ownerDocument.defaultView?.getComputedStyle(element)
    if (blockStyle) tokens.push({ run: textRun(blockStyle, '\n'), preserveWhitespace: true, hardBreak: true })
  }
}

function sameRunStyle(left: EditableTextRun, right: EditableTextRun): boolean {
  return left.font_family === right.font_family
    && left.font_size === right.font_size
    && left.letter_spacing === right.letter_spacing
    && left.bold === right.bold
    && left.italic === right.italic
    && left.underline === right.underline
    && left.color === right.color
}

function normalizeRunTokens(tokens: RunToken[]): EditableTextRun[] {
  const normalized: EditableTextRun[] = []
  for (const token of tokens) {
    let value = token.hardBreak
      ? '\n'
      : token.preserveWhitespace
        ? token.run.text.replace(/\r\n?/g, '\n')
        : token.run.text.replace(/\s+/g, ' ')
    if (!value) continue
    if (normalized.length === 0) value = value.replace(/^[\s\n]+/, '')
    if (normalized.at(-1)?.text.endsWith(' ') && value.startsWith(' ')) value = value.slice(1)
    if (!value) continue
    const run = { ...token.run, text: value }
    const previous = normalized.at(-1)
    if (previous && sameRunStyle(previous, run)) previous.text += run.text
    else normalized.push(run)
  }
  const last = normalized.at(-1)
  if (last) last.text = last.text.replace(/[\s\n]+$/, '')
  return normalized.filter((run) => run.text.length > 0)
}

function listLevel(node: HTMLElement): number {
  let level = -1
  let current: HTMLElement | null = node
  while (current) {
    if (current.matches('ul,ol')) level += 1
    current = current.parentElement
  }
  return Math.max(0, level)
}

function integerAttribute(node: Element, name: string): number | undefined {
  const raw = node.getAttribute(name)?.trim()
  if (!raw || !/^[+-]?\d+$/.test(raw)) return undefined
  const value = Number(raw)
  return Number.isSafeInteger(value) ? value : undefined
}

function orderedListOrdinal(node: HTMLElement, list: HTMLElement): number | undefined {
  const items = Array.from(list.children).filter((child) => child.tagName === 'LI') as HTMLElement[]
  const reversed = list.hasAttribute('reversed')
  let ordinal = integerAttribute(list, 'start') ?? (reversed ? items.length : 1)
  const step = reversed ? -1 : 1
  for (const item of items) {
    ordinal = integerAttribute(item, 'value') ?? ordinal
    if (item === node) {
      return ordinal >= 1 && ordinal <= 32_767 ? ordinal : undefined
    }
    ordinal += step
  }
  return undefined
}

function paragraphBullet(node: HTMLElement): EditableTextBullet | undefined {
  if (node.tagName !== 'LI') return undefined
  const list = node.parentElement?.closest<HTMLElement>('ul,ol')
  const level = listLevel(node)
  if (list?.tagName === 'OL') {
    const start = orderedListOrdinal(node, list)
    return { kind: 'number', level, ...(start !== undefined ? { start } : {}) }
  }
  const style = node.ownerDocument.defaultView?.getComputedStyle(node)
  const marker = {
    circle: '◦',
    square: '▪',
  }[style?.listStyleType ?? ''] ?? '•'
  return { kind: 'bullet', marker, level }
}

function extractParagraphs(node: HTMLElement, claimed: Set<HTMLElement>): ParagraphExtraction {
  const unsupported = new Set<string>()
  const tokens: RunToken[] = []
  appendTextTokens(node, node, tokens, unsupported, claimed)
  const runs = normalizeRunTokens(tokens)
  const bullet = paragraphBullet(node)
  const level = bullet?.level
  const paragraph: EditableTextParagraph = {
    runs,
    ...(bullet ? { bullet } : {}),
    ...(level !== undefined ? { level } : {}),
  }
  return {
    paragraphs: runs.length ? [paragraph] : [],
    text: runs.map((run) => run.text).join(''),
    unsupported: Array.from(unsupported),
  }
}

function characterCount(value: string): number {
  return Array.from(value.trim()).length
}

function textPadding(style: CSSStyleDeclaration): EditableTextPadding {
  return {
    left: Math.max(0, px(style.paddingLeft)),
    right: Math.max(0, px(style.paddingRight)),
    top: Math.max(0, px(style.paddingTop)),
    bottom: Math.max(0, px(style.paddingBottom)),
  }
}

function lineHeightRatio(style: CSSStyleDeclaration, fontSize: number): number {
  const lineHeight = style.lineHeight === 'normal'
    ? fontSize * 1.2
    : px(style.lineHeight, fontSize * 1.2)
  return Math.max(0.8, Math.min(3, lineHeight / Math.max(fontSize, 1)))
}

export function collectEditableElements(
  root: HTMLElement,
  request: RenderRequest,
): { elements: EditableElement[]; issues: RenderIssue[]; hidden: Element[]; text_coverage: TextCoverage } {
  const elements: EditableElement[] = []
  const issues: RenderIssue[] = []
  const hidden: Element[] = []
  const text_coverage: TextCoverage = {
    visible_blocks: 0,
    visible_characters: 0,
    native_blocks: 0,
    native_characters: 0,
    flattened: [],
  }
  const roleOrdinals = new Map<string, number>()
  const candidates = textCandidates(root)
  const claimed = new Set(candidates.map((candidate) => candidate.node))

  for (const candidate of candidates) {
    const { node } = candidate
    if (!isRendered(node, root)) continue
    const rect = relativeRect(node, root)
    const role = textRole(node)
    const ordinal = (roleOrdinals.get(role) ?? 0) + 1
    roleOrdinals.set(role, ordinal)
    const name = textName(node, role, ordinal)
    if (rect.width <= 0 || rect.height <= 0) {
      if (candidate.explicit) {
        issues.push({ severity: 'warning', code: 'empty-editable-element', message: `${name} has no visible area.`, element: name })
      }
      continue
    }
    const extraction = extractParagraphs(node, claimed)
    const characters = characterCount(extraction.text)
    if (!characters) continue
    text_coverage.visible_blocks += 1
    text_coverage.visible_characters += characters
    if (node.closest(ART_TEXT_SELECTOR)) {
      text_coverage.flattened.push({ name, reason: 'explicit-art-mode', characters })
      continue
    }
    if (rect.x < -0.5 || rect.y < -0.5 || rect.x + rect.width > request.width + 0.5 || rect.y + rect.height > request.height + 0.5) {
      issues.push({ severity: 'error', code: 'editable-element-overflow', message: `${name} extends outside the slide.`, element: name })
      text_coverage.flattened.push({ name, reason: 'outside-slide-canvas', characters })
      continue
    }
    if (hasEmbeddedGraphic(node)) {
      issues.push({ severity: 'warning', code: 'editable-text-flattened', message: `${name} contains an embedded graphic and remains in the visual shell.`, element: name })
      text_coverage.flattened.push({ name, reason: 'embedded-graphic', characters })
      continue
    }
    if (foregroundOccluder(node, root)) {
      issues.push({ severity: 'warning', code: 'editable-text-flattened', message: `${name} is covered by foreground content and remains in the visual shell to preserve stacking order.`, element: name })
      text_coverage.flattened.push({ name, reason: 'foreground-occlusion', characters })
      continue
    }
    const style = node.ownerDocument.defaultView?.getComputedStyle(node)
    if (!style) {
      text_coverage.flattened.push({ name, reason: 'computed-style-unavailable', characters })
      continue
    }
    const unsupported = Array.from(new Set([
      ...unsupportedTextStyle(style),
      ...extraction.unsupported,
    ]))
    if (unsupported.length) {
      const reason = `unsupported CSS: ${unsupported.join(', ')}`
      issues.push({ severity: 'warning', code: 'editable-text-flattened', message: `${name} uses ${unsupported.join(', ')} which PowerPoint cannot preserve and remains in the visual shell.`, element: name })
      text_coverage.flattened.push({ name, reason, characters })
      continue
    }
    const firstRun = extraction.paragraphs[0]?.runs[0]
    if (!firstRun) {
      text_coverage.flattened.push({ name, reason: 'no-extractable-text-runs', characters })
      continue
    }
    if (firstRun.font_size < 21.33) {
      issues.push({ severity: 'warning', code: 'small-slide-text', message: `${name} is smaller than the 16pt presentation baseline.`, element: name })
    }
    elements.push({
      kind: 'text',
      name,
      role,
      ...rect,
      padding: textPadding(style),
      paragraphs: extraction.paragraphs,
      // Legacy fields keep older sidecars functional during the schema rollout.
      text: extraction.text,
      font_family: firstRun.font_family,
      font_size: firstRun.font_size,
      bold: firstRun.bold,
      italic: firstRun.italic,
      underline: firstRun.underline,
      color: firstRun.color,
      text_align: style.textAlign || 'left',
      vertical_align: node.dataset.pptxVerticalAlign || 'top',
      line_height_ratio: lineHeightRatio(style, firstRun.font_size),
      rotation: 0,
    })
    hidden.push(node)
    text_coverage.native_blocks += 1
    text_coverage.native_characters += characters
  }

  if (!claimed.has(root) && isRendered(root, root)) {
    let rootTextOrdinal = 0
    Array.from(root.childNodes).forEach((node) => {
      if (node.nodeType !== Node.TEXT_NODE) return
      const text = node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
      const characters = characterCount(text)
      if (!characters) return
      rootTextOrdinal += 1
      text_coverage.visible_blocks += 1
      text_coverage.visible_characters += characters
      text_coverage.flattened.push({
        name: `root-text-${rootTextOrdinal}`,
        reason: 'unstructured-root-text',
        characters,
      })
    })
  }

  const svgTextNodes = Array.from(root.querySelectorAll<SVGTextElement>('svg text'))
  svgTextNodes.forEach((node, index) => {
    if (!isRendered(node, root)) return
    const rect = relativeRect(node, root)
    if (rect.width <= 0 || rect.height <= 0) return
    const text = node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
    const characters = characterCount(text)
    if (!characters) return
    const name = svgTextName(node, index + 1)
    text_coverage.visible_blocks += 1
    text_coverage.visible_characters += characters
    text_coverage.flattened.push({ name, reason: 'svg-text', characters })
  })

  const explicitNodes = queryIncludingRoot(root, '[data-pptx-editable]')
  explicitNodes.forEach((node, index) => {
    const kind = node.dataset.pptxEditable
    if (kind === 'text') return
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
        || Number.parseFloat(style.opacity || '1') < 0.999
        || (style.mixBlendMode && style.mixBlendMode !== 'normal')
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
  return { elements, issues, hidden, text_coverage }
}
