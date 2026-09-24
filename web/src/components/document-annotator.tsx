/**
 * DeckAnnotator — select part of a slide or sheet in the document viewer and
 * tell the agent what to change there.
 *
 * While annotating, hovering a slide outlines the shape under the pointer
 * (native renderer: every shape carries `data-shape-id`), a click selects it
 * and a drag selects a free area — the only option on exact (LibreOffice)
 * pages, which are images. On a workbook's cell grid a click selects a cell
 * and a drag a range of cells (`B3:D8`), sent with the sheet's name. A popover takes the instruction: send it now, or
 * add it to the composer's batch and keep selecting. Batched selections stay
 * pinned with their number; sent ones shimmer until the agent's turn ends.
 *
 * All drawing happens inside the preview frame (same-origin, script-free),
 * positioned in percent of the slide so zoom, fit and scroll never skew it.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowUp, MessageSquarePlus, X } from 'lucide-react'

import { changeDocumentVersion } from '@/api/client'
import {
  describeAnnotation,
  type AnnotationArea,
  type DocumentAnnotation,
} from '@/lib/document-annotations'
import { cn } from '@/lib/utils'
import {
  MAX_BATCH_ANNOTATIONS,
  useDocumentAnnotationsStore,
  usePendingAnnotations,
} from '@/stores/useDocumentAnnotationsStore'

// A slide, an exact-render page, or a sheet's cell grid.
const SURFACE = '.slide:not(.slide-skeleton), .pdf-page-surface, .sheet:not(.sheet-skeleton) .grid-stage'
const MAX_RANGE_TEXT_CELLS = 40
const DRAG_THRESHOLD_PX = 4
const MAX_AREA_SHAPES = 12

const ANNOTATOR_CSS = `
html[data-evoflux-annotating] .slide,html[data-evoflux-annotating] .pdf-page-surface{cursor:crosshair;user-select:none;-webkit-user-select:none}
html[data-evoflux-annotating] .grid-stage{cursor:cell;user-select:none;-webkit-user-select:none}
[data-evoflux-anno]{position:absolute;pointer-events:none;box-sizing:border-box;z-index:2147483000;border-radius:3px}
[data-evoflux-anno="hover"]{outline:2px solid #1a73e8;background:#1a73e812}
[data-evoflux-anno="selection"]{outline:2px solid #1a73e8;box-shadow:0 0 0 4px #1a73e82e;background:#1a73e80d}
[data-evoflux-anno="drag"]{border:1.5px dashed #1a73e8;background:#1a73e81a}
[data-evoflux-anno="pin"]{outline:1.5px solid #1a73e8b3;background:#1a73e80a}
[data-evoflux-anno="pin"]::before,[data-evoflux-anno="working"]::before{content:attr(data-n);position:absolute;top:-9px;left:-9px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:#1a73e8;color:#fff;font:600 11px/18px Arial,sans-serif;text-align:center;box-shadow:0 1px 4px #0004}
[data-evoflux-anno="working"]{outline:2px solid #1a73e8;background:linear-gradient(100deg,transparent 30%,#8ab4f84d 50%,transparent 70%) 0 0/250% 100%;animation:evx-anno-work 1.8s ease-in-out infinite}
@keyframes evx-anno-work{0%{background-position:120% 0;box-shadow:0 0 0 0 #1a73e866}50%{box-shadow:0 0 0 7px #1a73e800}100%{background-position:-120% 0;box-shadow:0 0 0 0 #1a73e800}}
@media (prefers-reduced-motion:reduce){[data-evoflux-anno="working"]{animation:none}}
`

interface Selection {
  slide: number
  shapes: Array<{ id: number; name: string }>
  area: AnnotationArea
  text: string
  /** Workbooks: the sheet's name and the selected cells ("B3" or "B3:D8"). */
  sheet?: string
  range?: string
}

interface Box {
  kind: 'hover' | 'selection' | 'drag' | 'pin' | 'working'
  slide: number
  area: AnnotationArea
  n?: number
}

function clampArea(area: AnnotationArea): AnnotationArea {
  const x = Math.max(0, Math.min(100, area.x))
  const y = Math.max(0, Math.min(100, area.y))
  return { x, y, w: Math.max(0, Math.min(100 - x, area.w)), h: Math.max(0, Math.min(100 - y, area.h)) }
}

function areaOf(rect: DOMRect, surface: DOMRect): AnnotationArea {
  return clampArea({
    x: ((rect.left - surface.left) / surface.width) * 100,
    y: ((rect.top - surface.top) / surface.height) * 100,
    w: (rect.width / surface.width) * 100,
    h: (rect.height / surface.height) * 100,
  })
}

function overlapShare(inner: DOMRect, outer: { left: number; top: number; right: number; bottom: number }): number {
  const width = Math.min(inner.right, outer.right) - Math.max(inner.left, outer.left)
  const height = Math.min(inner.bottom, outer.bottom) - Math.max(inner.top, outer.top)
  if (width <= 0 || height <= 0 || inner.width <= 0 || inner.height <= 0) return 0
  return (width * height) / (inner.width * inner.height)
}

/** Frame elements belong to the frame's realm, so `instanceof Element` fails. */
function asElement(target: EventTarget | null): Element | null {
  return target && typeof (target as Element).closest === 'function' ? (target as Element) : null
}

function cleanText(text: string | null | undefined): string {
  return (text ?? '').replace(/\s+/g, ' ').trim().slice(0, 300)
}

/** An editable shape of the slide itself (not its layout or master). */
function slideShape(element: Element | null, surface: HTMLElement): HTMLElement | null {
  const shape = element?.closest<HTMLElement>('[data-shape-id]') ?? null
  if (!shape || !surface.contains(shape)) return null
  const layer = shape.dataset.sourceLayer
  return !layer || layer === 'slide' ? shape : null
}

/** A line of text on an exact page (its invisible, positioned text layer). */
function textLine(element: Element | null, surface: HTMLElement): HTMLElement | null {
  const span = element?.closest<HTMLElement>('.pdf-text-layer span') ?? null
  return span && surface.contains(span) && cleanText(span.textContent) ? span : null
}

function shapeRef(shape: HTMLElement) {
  return {
    id: Number(shape.dataset.shapeId),
    name: shape.dataset.shapeName || shape.dataset.qaLabel || `Shape ${shape.dataset.shapeId}`,
  }
}

function slideNumber(doc: Document, surface: HTMLElement): number {
  const item = surface.closest('[data-preview-item]')
  return Array.from(doc.querySelectorAll('[data-preview-item]')).indexOf(item as Element) + 1
}

function surfaceFor(doc: Document, slide: number): HTMLElement | null {
  const item = doc.querySelectorAll('[data-preview-item]')[slide - 1]
  return item?.querySelector<HTMLElement>(SURFACE) ?? null
}

// ── Workbook cells ─────────────────────────────────────────────────────────

function isGrid(surface: HTMLElement): boolean {
  return surface.classList.contains('grid-stage')
}

/** The rendered cell (`td[data-cell="B3"]`) at an element, inside ``surface``. */
function gridCell(element: Element | null, surface: HTMLElement): HTMLElement | null {
  const cell = element?.closest<HTMLElement>('td[data-cell]') ?? null
  return cell && surface.contains(cell) ? cell : null
}

function cellAt(doc: Document, x: number, y: number, surface: HTMLElement): HTMLElement | null {
  return gridCell(asElement(doc.elementFromPoint(x, y)), surface)
}

function parseCell(name: string): { column: number; row: number } | null {
  const match = /^([A-Z]+)(\d+)$/.exec(name)
  if (!match) return null
  const column = [...match[1]].reduce((total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0)
  return { column, row: Number(match[2]) }
}

function columnName(column: number): string {
  let name = ''
  for (let value = column; value > 0; value = Math.floor((value - 1) / 26)) {
    name = String.fromCharCode(65 + ((value - 1) % 26)) + name
  }
  return name
}

/** The cells ``a`` and ``b`` span, as an A1 range, with its bounds. */
function cellRange(a: HTMLElement, b: HTMLElement) {
  const start = parseCell(a.dataset.cell ?? '')
  const end = parseCell(b.dataset.cell ?? '')
  if (!start || !end) return null
  const left = Math.min(start.column, end.column)
  const right = Math.max(start.column, end.column)
  const top = Math.min(start.row, end.row)
  const bottom = Math.max(start.row, end.row)
  const first = `${columnName(left)}${top}`
  const last = `${columnName(right)}${bottom}`
  return { name: first === last ? first : `${first}:${last}`, left, right, top, bottom }
}

function unionRect(a: DOMRect, b: DOMRect): DOMRect {
  const left = Math.min(a.left, b.left)
  const top = Math.min(a.top, b.top)
  return new DOMRect(left, top, Math.max(a.right, b.right) - left, Math.max(a.bottom, b.bottom) - top)
}

function sheetName(surface: HTMLElement): string {
  const label = surface.closest<HTMLElement>('[data-preview-item]')?.dataset.previewLabel ?? ''
  return label.replace(/ \(hidden\)$/, '')
}

function cellSelection(doc: Document, surface: HTMLElement, from: HTMLElement, to: HTMLElement): Selection | null {
  const range = cellRange(from, to)
  if (!range) return null
  const text = Array.from(surface.querySelectorAll<HTMLElement>('td[data-cell]'))
    .filter((cell) => {
      const at = parseCell(cell.dataset.cell ?? '')
      return at && at.column >= range.left && at.column <= range.right && at.row >= range.top && at.row <= range.bottom
    })
    .slice(0, MAX_RANGE_TEXT_CELLS)
    .map((cell) => cleanText(cell.textContent))
    .filter(Boolean)
    .join(' · ')
  return {
    slide: slideNumber(doc, surface),
    shapes: [],
    area: areaOf(unionRect(from.getBoundingClientRect(), to.getBoundingClientRect()), surface.getBoundingClientRect()),
    text: cleanText(text),
    sheet: sheetName(surface),
    range: range.name,
  }
}

function nextId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export interface DeckAnnotatorProps {
  iframeRef: React.RefObject<HTMLIFrameElement | null>
  /** Changes whenever the frame document is replaced (its HTML). */
  frameKey: string | undefined
  sessionId: string
  filePath: string
  /** Annotate mode: pointer selects instead of scrolling text. */
  active: boolean
  /** Whether the session's agent turn is running (ends the shimmer). */
  agentWorking: boolean
  onExit: () => void
}

export function DeckAnnotator({ iframeRef, frameKey, sessionId, filePath, active, agentWorking, onExit }: DeckAnnotatorProps) {
  const [selection, setSelection] = useState<Selection | null>(null)
  const [hover, setHover] = useState<Box | null>(null)
  const [drag, setDrag] = useState<Box | null>(null)
  const [instruction, setInstruction] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState<DocumentAnnotation[]>([])
  const [frameTick, setFrameTick] = useState(0)
  const [position, setPosition] = useState<{ left: number; top: number; above: boolean } | null>(null)
  // Exact (LibreOffice) pages are images with a text layer: no shapes to click.
  const [exactPages, setExactPages] = useState(false)
  // A workbook's sheets are cell grids: a click picks a cell, a drag a range.
  const [workbook, setWorkbook] = useState(false)
  const selectionRef = useRef<Selection | null>(null)

  // Place the popover next to the selection's box: its bottom edge just above
  // the box when there is room (CSS lifts it by its own height), else below.
  const placePopover = useCallback((next: Selection | null) => {
    selectionRef.current = next
    const frame = iframeRef.current
    const doc = frame?.contentDocument
    const surface = next && doc ? surfaceFor(doc, next.slide) : null
    if (!next || !frame || !surface) {
      setPosition(null)
      return
    }
    const frameRect = frame.getBoundingClientRect()
    const containerRect = (frame.offsetParent as HTMLElement | null)?.getBoundingClientRect() ?? frameRect
    const rect = surface.getBoundingClientRect()
    const boxTop = rect.top + (rect.height * next.area.y) / 100
    const boxLeft = rect.left + (rect.width * next.area.x) / 100
    const boxBottom = boxTop + (rect.height * next.area.h) / 100
    const width = 340
    const roughHeight = 120
    const offsetX = frameRect.left - containerRect.left
    const offsetY = frameRect.top - containerRect.top
    const above = offsetY + boxTop - 8 >= roughHeight
    const top = above
      ? offsetY + boxTop - 8
      : Math.max(4, Math.min(offsetY + boxBottom + 8, containerRect.height - roughHeight - 4))
    const left = Math.max(4, Math.min(offsetX + boxLeft, containerRect.width - width - 4))
    setPosition({ left, top, above })
  }, [iframeRef])

  const select = useCallback((next: Selection | null) => {
    setSelection(next)
    placePopover(next)
  }, [placePopover])
  const pending = usePendingAnnotations(sessionId)
  const pins = pending.filter((annotation) => annotation.file === filePath)
  const teamWorking = agentWorking
  const sawWorkingRef = useRef(false)

  // Sent selections shimmer while the agent works on them.
  useEffect(() => {
    if (sent.length === 0) {
      sawWorkingRef.current = false
      return
    }
    if (teamWorking) {
      sawWorkingRef.current = true
      return
    }
    if (!sawWorkingRef.current) {
      // The turn has not started yet; give up if it never does.
      const timer = window.setTimeout(() => setSent([]), 60_000)
      return () => window.clearTimeout(timer)
    }
    sawWorkingRef.current = false
    const timer = window.setTimeout(() => setSent([]), 0)
    return () => window.clearTimeout(timer)
  }, [sent.length, teamWorking])

  const frameDocument = useCallback(() => iframeRef.current?.contentDocument ?? null, [iframeRef])

  // Redraw boxes whenever anything shown changes (and after frame reloads).
  useLayoutEffect(() => {
    const doc = frameDocument()
    if (!doc?.body) return
    let style = doc.querySelector<HTMLStyleElement>('style[data-evoflux-annotator]')
    if (!style) {
      style = doc.createElement('style')
      style.dataset.evofluxAnnotator = ''
      doc.head?.appendChild(style)
    }
    if (style.textContent !== ANNOTATOR_CSS) style.textContent = ANNOTATOR_CSS
    doc.documentElement.toggleAttribute('data-evoflux-annotating', active)
    doc.querySelectorAll('[data-evoflux-anno]').forEach((element) => element.remove())
    const boxes: Box[] = [
      ...sent.filter((a) => a.file === filePath).map((a, index): Box => ({ kind: 'working', slide: a.slide, area: a.area, n: index + 1 })),
      ...pins.map((a, index): Box => ({ kind: 'pin', slide: a.slide, area: a.area, n: pending.indexOf(a) + 1 || index + 1 })),
    ]
    if (active && hover && !drag) boxes.push(hover)
    if (selection) boxes.push({ kind: 'selection', slide: selection.slide, area: selection.area })
    if (drag) boxes.push(drag)
    for (const box of boxes) {
      const surface = surfaceFor(doc, box.slide)
      if (!surface) continue
      const element = doc.createElement('div')
      element.dataset.evofluxAnno = box.kind
      if (box.n) element.dataset.n = String(box.n)
      Object.assign(element.style, {
        left: `${box.area.x}%`,
        top: `${box.area.y}%`,
        width: `${box.area.w}%`,
        height: `${box.area.h}%`,
      })
      surface.appendChild(element)
    }
  }, [active, drag, filePath, frameDocument, frameKey, frameTick, hover, pending, pins, selection, sent])

  // Pointer handling inside the frame.
  useEffect(() => {
    const frame = iframeRef.current
    if (!frame) return
    let detach = () => {}
    const attach = () => {
      detach()
      const doc = frame.contentDocument
      const win = frame.contentWindow
      if (!doc || !win) return
      setFrameTick((tick) => tick + 1)
      setExactPages(Boolean(doc.querySelector('[data-preview-renderer^="libreoffice-"]')))
      setWorkbook(Boolean(doc.querySelector('.sheet .grid-stage')))
      // A reloaded frame has new slide elements; re-anchor the popover.
      placePopover(selectionRef.current)
      let start: { surface: HTMLElement; x: number; y: number; target: Element | null } | null = null
      let dragging = false

      const onMove = (event: PointerEvent) => {
        if (!active) return
        const target = asElement(event.target)
        if (start) {
          if (!dragging && Math.hypot(event.clientX - start.x, event.clientY - start.y) < DRAG_THRESHOLD_PX) return
          dragging = true
          const rect = start.surface.getBoundingClientRect()
          if (isGrid(start.surface)) {
            // A drag across cells selects whole cells, from the first to the one under the pointer.
            const from = gridCell(start.target, start.surface)
            const to = cellAt(doc, event.clientX, event.clientY, start.surface) ?? from
            if (from && to) {
              setDrag({
                kind: 'drag',
                slide: slideNumber(doc, start.surface),
                area: areaOf(unionRect(from.getBoundingClientRect(), to.getBoundingClientRect()), rect),
              })
            }
            return
          }
          const left = Math.min(start.x, event.clientX)
          const top = Math.min(start.y, event.clientY)
          setDrag({
            kind: 'drag',
            slide: slideNumber(doc, start.surface),
            area: areaOf(new DOMRect(left, top, Math.abs(event.clientX - start.x), Math.abs(event.clientY - start.y)), rect),
          })
          return
        }
        const surface = target?.closest<HTMLElement>(SURFACE) ?? null
        const hit = !surface
          ? null
          : isGrid(surface)
            ? gridCell(target, surface)
            : slideShape(target, surface) ?? textLine(target, surface)
        setHover(surface && hit
          ? { kind: 'hover', slide: slideNumber(doc, surface), area: areaOf(hit.getBoundingClientRect(), surface.getBoundingClientRect()) }
          : null)
      }

      const onDown = (event: PointerEvent) => {
        if (!active || event.button !== 0) return
        const target = asElement(event.target)
        const surface = target?.closest<HTMLElement>(SURFACE) ?? null
        if (!surface) return
        event.preventDefault()
        // Keep receiving the drag even when it strays out of the frame, so it
        // never ends up resizing or selecting anything beside the viewer.
        try {
          (target as Element & { setPointerCapture?: (id: number) => void })
            .setPointerCapture?.(event.pointerId)
        } catch {
          // Synthetic events carry no active pointer.
        }
        start = { surface, x: event.clientX, y: event.clientY, target }
        dragging = false
      }

      const onUp = (event: PointerEvent) => {
        if (!start) return
        const { surface, target } = start
        const surfaceRect = surface.getBoundingClientRect()
        const slide = slideNumber(doc, surface)
        if (isGrid(surface)) {
          const from = gridCell(target, surface)
          const to = dragging ? cellAt(doc, event.clientX, event.clientY, surface) ?? from : from
          select(from && to ? cellSelection(doc, surface, from, to) : null)
        } else if (dragging) {
          const bounds = {
            left: Math.min(start.x, event.clientX),
            top: Math.min(start.y, event.clientY),
            right: Math.max(start.x, event.clientX),
            bottom: Math.max(start.y, event.clientY),
          }
          const area = areaOf(new DOMRect(bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top), surfaceRect)
          const inside = Array.from(surface.querySelectorAll<HTMLElement>('[data-shape-id]'))
            .filter((shape) => slideShape(shape, surface) === shape && overlapShare(shape.getBoundingClientRect(), bounds) > 0.5)
          // Keep the outermost shape of a nested group.
          const outermost = inside.filter((shape) => !inside.some((other) => other !== shape && other.contains(shape)))
          const text = outermost.length > 0
            ? outermost.map((shape) => cleanText(shape.textContent)).filter(Boolean).join(' · ')
            : Array.from(surface.querySelectorAll<HTMLElement>('.pdf-text-layer span'))
                .filter((span) => overlapShare(span.getBoundingClientRect(), bounds) > 0.5)
                .map((span) => span.textContent ?? '')
                .join(' ')
          select({ slide, shapes: outermost.slice(0, MAX_AREA_SHAPES).map(shapeRef), area, text: cleanText(text) })
        } else {
          const shape = slideShape(target, surface)
          if (shape) {
            select({
              slide,
              shapes: [shapeRef(shape)],
              area: areaOf(shape.getBoundingClientRect(), surfaceRect),
              text: cleanText(shape.textContent),
            })
          } else {
            const line = textLine(target, surface)
            select(line
              ? { slide, shapes: [], area: areaOf(line.getBoundingClientRect(), surfaceRect), text: cleanText(line.textContent) }
              : null)
          }
        }
        setInstruction('')
        setError(null)
        setDrag(null)
        start = null
        dragging = false
      }

      const onLeave = () => setHover(null)
      const onScroll = () => placePopover(selectionRef.current)
      const onKey = (event: KeyboardEvent) => {
        if (event.key === 'Escape') select(null)
      }

      doc.addEventListener('pointermove', onMove)
      doc.addEventListener('pointerdown', onDown)
      doc.addEventListener('pointerup', onUp)
      doc.addEventListener('pointerleave', onLeave)
      doc.addEventListener('keydown', onKey)
      win.addEventListener('scroll', onScroll, { passive: true })
      win.addEventListener('resize', onScroll)
      detach = () => {
        doc.removeEventListener('pointermove', onMove)
        doc.removeEventListener('pointerdown', onDown)
        doc.removeEventListener('pointerup', onUp)
        doc.removeEventListener('pointerleave', onLeave)
        doc.removeEventListener('keydown', onKey)
        win.removeEventListener('scroll', onScroll)
        win.removeEventListener('resize', onScroll)
      }
    }
    attach()
    frame.addEventListener('load', attach)
    return () => {
      frame.removeEventListener('load', attach)
      detach()
    }
  }, [active, frameKey, iframeRef, placePopover, select])

  // Leaving annotate mode drops the unsent selection.
  useEffect(() => {
    if (active) return
    const timer = window.setTimeout(() => {
      select(null)
      setHover(null)
      setDrag(null)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [active, select])

  const commit = (sendNow: boolean) => {
    if (!selection) return
    const annotation: DocumentAnnotation = {
      id: nextId(),
      file: filePath,
      slide: selection.slide,
      ...(selection.range ? { sheet: selection.sheet, range: selection.range } : {}),
      shapes: selection.shapes,
      area: selection.area,
      text: selection.text,
      instruction: instruction.trim(),
      label: describeAnnotation(selection),
    }
    const store = useDocumentAnnotationsStore.getState()
    if (!store.add(sessionId, annotation)) {
      setError(`A message carries up to ${MAX_BATCH_ANNOTATIONS} annotations. Send these first.`)
      return
    }
    // Capture the file as it is now, so this edit can be undone.
    void changeDocumentVersion(sessionId, filePath, {
      action: 'checkpoint',
      label: annotation.instruction || annotation.label,
    }).catch(() => undefined)
    if (sendNow) {
      const batch = useDocumentAnnotationsStore.getState().pending[sessionId] ?? []
      setSent(batch.filter((item) => item.file === filePath))
      store.requestSubmit(sessionId)
    }
    select(null)
    setInstruction('')
  }

  if (!selection || !position) {
    if (!active) return null
    return (
      <div
        role="status"
        className="pointer-events-none absolute top-2 left-1/2 z-(--z-panel) max-w-[calc(100%-16px)] -translate-x-1/2 rounded-full border border-(--color-border) bg-(--bg-card)/95 px-3 py-1 text-[11px] text-(--color-text-2) shadow-sm"
      >
        {exactPages
          ? 'Click a line of text or drag across an area to select it'
          : workbook
            ? 'Click a cell or drag across cells to select them'
            : 'Click a shape or drag across an area to select it'}
      </div>
    )
  }
  return (
    <div
      role="dialog"
      aria-label="Annotate selection"
      className="absolute z-(--z-panel) w-[340px] max-w-[calc(100%-8px)] rounded-xl border border-(--color-border) bg-(--bg-card) p-2 shadow-lg"
      style={{
        left: position.left,
        top: position.top,
        transform: position.above ? 'translateY(-100%)' : undefined,
      }}
      data-testid="annotation-popover"
    >
      <div className="mb-1 flex items-center gap-2 px-1 text-[11px] text-(--color-text-muted)">
        <span className="min-w-0 flex-1 truncate">{describeAnnotation(selection)}</span>
        {pending.length > 0 && <span className="shrink-0">{pending.length} in batch</span>}
        <button
          type="button"
          onClick={() => select(null)}
          aria-label="Cancel selection"
          className="flex size-5 shrink-0 items-center justify-center rounded hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          <X size={12} />
        </button>
      </div>
      <div className="flex items-end gap-1.5">
        <textarea
          autoFocus
          rows={2}
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault()
              select(null)
            } else if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              commit(true)
            }
          }}
          placeholder="Edit or ask; leave empty to quote only"
          aria-label="Instruction for the selection"
          className="min-h-[2.5rem] flex-1 resize-none rounded-lg bg-transparent px-2 py-1.5 text-sm text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
        />
        <div className="flex shrink-0 flex-col gap-1">
          <button
            type="button"
            onClick={() => commit(true)}
            title="Send now (Enter)"
            aria-label="Send annotation now"
            className="flex size-7 items-center justify-center rounded-lg bg-(--color-accent) text-white transition-opacity hover:opacity-90"
          >
            <ArrowUp size={14} />
          </button>
          <button
            type="button"
            onClick={() => commit(false)}
            title="Add to batch and keep selecting"
            aria-label="Add annotation to batch"
            className={cn(
              'flex size-7 items-center justify-center rounded-lg border border-(--color-border) text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
            )}
          >
            <MessageSquarePlus size={14} />
          </button>
        </div>
      </div>
      {error && <p className="px-1 pt-1 text-[11px] text-(--color-error)">{error}</p>}
      <p className="px-1 pt-1 text-[10px] text-(--color-text-subtle)">
        Esc cancels ·{' '}
        <button type="button" className="underline hover:text-(--color-text)" onClick={onExit}>Done annotating</button>
      </p>
    </div>
  )
}
