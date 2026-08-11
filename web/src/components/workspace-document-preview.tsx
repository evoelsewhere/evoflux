import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  AlertCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  Loader2,
  Maximize2,
  Minimize2,
  MonitorPlay,
  NotepadText,
  PanelLeft,
  PanelsTopLeft,
  Presentation,
  RefreshCw,
  Search,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'

import {
  codingWorkspaceDocumentPreviewUrl,
  workspaceDocumentPreviewUrl,
} from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'
import { cn } from '@/lib/utils'
import {
  workspaceFileKind,
  type WorkspaceDocumentKind,
} from '@/lib/workspace-file-kind'

type FitMode = 'custom' | 'width' | 'page'
type PresentationView = 'normal' | 'sorter' | 'reading'
type PresentationWorkspaceView = Exclude<PresentationView, 'reading'>

interface NavigatorEntry {
  label: string
  index: number
}

interface SelectedCell {
  name: string
  value: string
}

interface SlidePreviewMeta {
  notes: string
  thumbnailHtml: string
}

interface ViewerKeyEvent {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  target: EventTarget | null
  preventDefault: () => void
}

interface WebkitFullscreenDocument extends Document {
  webkitExitFullscreen?: () => Promise<void> | void
  webkitFullscreenElement?: Element | null
}

interface WebkitFullscreenElement extends HTMLElement {
  webkitRequestFullscreen?: () => Promise<void> | void
}

export interface WorkspaceDocumentPreviewProps {
  file: WorkspaceFileInfo
  sessionId?: string
  workspace?: string
  sourceUrl?: string
}

const FORMAT_META: Record<WorkspaceDocumentKind, { accent: string; label: string }> = {
  docx: { accent: '#185abd', label: 'Word' },
  xlsx: { accent: '#107c41', label: 'Excel' },
  pptx: { accent: '#c43e1c', label: 'PowerPoint' },
  pdf: { accent: '#c42b1c', label: 'PDF' },
}

const MAX_PREVIEW_RESPONSE_BYTES = 36 * 1024 * 1024

function clampZoom(value: number): number {
  return Math.min(300, Math.max(25, Math.round(value)))
}

function previewItems(document: Document): HTMLElement[] {
  const items = Array.from(document.querySelectorAll<HTMLElement>('[data-preview-item]'))
  return items.length > 0 ? items : document.body ? [document.body] : []
}

function slideNotes(element: HTMLElement): string {
  const inlineNotes = element.dataset.previewNotes?.trim()
  if (inlineNotes) return inlineNotes
  return element.querySelector<HTMLElement>('[data-preview-notes]')?.textContent?.trim() ?? ''
}

function slideThumbnailDocument(document: Document, element: HTMLElement): string {
  const clone = element.cloneNode(true) as HTMLElement
  clone.removeAttribute('hidden')
  clone.querySelectorAll('[data-preview-notes]').forEach((notes) => notes.remove())
  const styles = Array.from(document.querySelectorAll('style'))
    .filter((style) => style.dataset.evofluxViewer !== 'true')
    .map((style) => style.outerHTML)
    .join('')
  return `<!doctype html><html><head>
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:">
    ${styles}
    <style>
      html,body{width:100%;height:100%;margin:0!important;padding:0!important;overflow:hidden!important;background:#fff!important}
      body{display:block!important;min-width:0!important;min-height:0!important}
      [data-preview-item]{position:absolute!important;inset:0!important;display:block!important;width:100%!important;max-width:none!important;height:100%!important;margin:0!important;padding:0!important}
      [data-preview-item]>.slide{width:100%!important;height:100%!important;box-shadow:none!important}
      .slide-number,[data-preview-notes]:not([data-preview-item]){display:none!important}
    </style>
  </head><body>${clone.outerHTML}</body></html>`
}

function SlideThumbnail({
  html,
  label,
}: {
  html?: string
  label: string
}) {
  if (!html) {
    return (
      <span className="flex h-full w-full items-center justify-center bg-white text-[#b7472a]">
        <Presentation size={18} aria-hidden="true" />
      </span>
    )
  }
  return (
    <iframe
      srcDoc={html}
      title={label}
      sandbox=""
      referrerPolicy="no-referrer"
      loading="lazy"
      tabIndex={-1}
      aria-hidden="true"
      className="pointer-events-none h-full w-full border-0 bg-white"
    />
  )
}

function clearSearchMarks(document: Document): void {
  document.querySelectorAll<HTMLElement>('mark[data-evoflux-search]').forEach((mark) => {
    mark.replaceWith(document.createTextNode(mark.textContent ?? ''))
  })
  document.body?.normalize()
}

function markSearchMatches(document: Document, query: string): HTMLElement[] {
  clearSearchMarks(document)
  const needle = query.trim().toLocaleLowerCase()
  if (!needle || !document.body) return []

  const showText = document.defaultView?.NodeFilter.SHOW_TEXT ?? NodeFilter.SHOW_TEXT
  const walker = document.createTreeWalker(document.body, showText)
  const textNodes: Text[] = []
  let node = walker.nextNode()
  while (node) {
    const parent = node.parentElement
    if (parent && !['STYLE', 'SCRIPT', 'NOSCRIPT'].includes(parent.tagName)) textNodes.push(node as Text)
    node = walker.nextNode()
  }

  const matches: HTMLElement[] = []
  textNodes.forEach((textNode) => {
    const source = textNode.data
    const lower = source.toLocaleLowerCase()
    let cursor = 0
    let matchIndex = lower.indexOf(needle)
    if (matchIndex < 0 || !textNode.parentNode) return

    const fragment = document.createDocumentFragment()
    while (matchIndex >= 0) {
      if (matchIndex > cursor) fragment.append(document.createTextNode(source.slice(cursor, matchIndex)))
      const mark = document.createElement('mark')
      mark.dataset.evofluxSearch = 'true'
      mark.textContent = source.slice(matchIndex, matchIndex + needle.length)
      mark.style.cssText = 'background:#fde68a;color:inherit;padding:0;border-radius:2px;'
      fragment.append(mark)
      matches.push(mark)
      cursor = matchIndex + needle.length
      matchIndex = lower.indexOf(needle, cursor)
    }
    if (cursor < source.length) fragment.append(document.createTextNode(source.slice(cursor)))
    textNode.parentNode.replaceChild(fragment, textNode)
  })
  return matches
}

function errorMessage(response: Response): Promise<string> {
  return response.text().then((body) => {
    if (body) {
      try {
        const payload = JSON.parse(body) as { detail?: string }
        if (payload.detail) return payload.detail
      } catch {
        // The preview endpoint returns HTML on success and may return plain text on failure.
      }
    }
    return `Preview failed (HTTP ${response.status})`
  })
}

async function previewResponseText(response: Response): Promise<string> {
  const declaredSize = Number(response.headers?.get?.('content-length') ?? 0)
  if (Number.isFinite(declaredSize) && declaredSize > MAX_PREVIEW_RESPONSE_BYTES) {
    throw new Error('This preview is too large for the in-app viewer. Download the file to inspect it externally.')
  }
  if (!response.body) {
    const value = await response.text()
    if (new TextEncoder().encode(value).byteLength > MAX_PREVIEW_RESPONSE_BYTES) {
      throw new Error('This preview is too large for the in-app viewer. Download the file to inspect it externally.')
    }
    return value
  }

  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    size += value.byteLength
    if (size > MAX_PREVIEW_RESPONSE_BYTES) {
      await reader.cancel()
      throw new Error('This preview is too large for the in-app viewer. Download the file to inspect it externally.')
    }
    chunks.push(value)
  }
  const payload = new Uint8Array(size)
  let offset = 0
  chunks.forEach((chunk) => {
    payload.set(chunk, offset)
    offset += chunk.byteLength
  })
  return new TextDecoder().decode(payload)
}

function adjacentCellName(name: string, key: string): string | null {
  const match = /^([A-Z]+)([1-9]\d*)$/.exec(name)
  if (!match) return null
  let column = 0
  for (const character of match[1]) column = column * 26 + character.charCodeAt(0) - 64
  let row = Number(match[2])
  if (key === 'ArrowLeft') column -= 1
  else if (key === 'ArrowRight') column += 1
  else if (key === 'ArrowUp') row -= 1
  else if (key === 'ArrowDown') row += 1
  else return null
  if (column < 1 || row < 1) return null
  let label = ''
  while (column > 0) {
    column -= 1
    label = String.fromCharCode(65 + (column % 26)) + label
    column = Math.floor(column / 26)
  }
  return `${label}${row}`
}

/**
 * Host-owned reader shell for every generated document format.
 *
 * Rendering stays in the backend's inert, self-contained HTML document while
 * navigation, search, zoom, fit and workbook selection are implemented here.
 * This keeps Work and Coding mode on the same UI and avoids format-specific
 * SDKs in the WebView.
 */
export function WorkspaceDocumentPreview({
  file,
  sessionId,
  workspace,
  sourceUrl: providedSourceUrl,
}: WorkspaceDocumentPreviewProps) {
  const kind = workspaceFileKind(file) as WorkspaceDocumentKind
  const meta = FORMAT_META[kind]
  const sourceUrl = useMemo(() => {
    if (providedSourceUrl) return providedSourceUrl
    if (workspace) return codingWorkspaceDocumentPreviewUrl(workspace, file.path)
    if (sessionId) return workspaceDocumentPreviewUrl(sessionId, file.path)
    return ''
  }, [file.path, providedSourceUrl, sessionId, workspace])
  const requestKey = `${sourceUrl}:${file.size}:${file.mtime}`

  const iframeRef = useRef<HTMLIFrameElement>(null)
  const viewerRef = useRef<HTMLElement>(null)
  const itemElementsRef = useRef<HTMLElement[]>([])
  const activeIndexRef = useRef(0)
  const fullscreenActiveRef = useRef(false)
  const readingReturnViewRef = useRef<PresentationWorkspaceView>('normal')
  const frameCleanupRef = useRef<(() => void) | null>(null)
  const selectedCellElementRef = useRef<HTMLElement | null>(null)
  const viewerKeyDownRef = useRef<(event: ViewerKeyEvent) => void>(() => undefined)
  const [result, setResult] = useState<{ key: string; html?: string; error?: string } | null>(null)
  const [retryKey, setRetryKey] = useState(0)
  const [navigatorOpen, setNavigatorOpen] = useState(() => (
    typeof window === 'undefined' || !window.matchMedia
      ? true
      : !window.matchMedia('(max-width: 640px)').matches
  ))
  const [entries, setEntries] = useState<NavigatorEntry[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchCount, setSearchCount] = useState(0)
  const [searchIndex, setSearchIndex] = useState(0)
  const [zoom, setZoom] = useState(100)
  const [fitMode, setFitMode] = useState<FitMode>(kind === 'pptx' ? 'page' : 'width')
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null)
  const [presentationView, setPresentationView] = useState<PresentationView>('normal')
  const [notesOpen, setNotesOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [slidePreviewMeta, setSlidePreviewMeta] = useState<SlidePreviewMeta[]>([])
  const [slideAspectRatio, setSlideAspectRatio] = useState('16 / 9')
  const currentResult = result?.key === `${requestKey}:${retryKey}` ? result : null
  const isPresentation = kind === 'pptx'
  const fullscreenSupported = typeof Element !== 'undefined' && Boolean(
    Element.prototype.requestFullscreen
    || (HTMLElement.prototype as WebkitFullscreenElement).webkitRequestFullscreen,
  )
  const hasSlideNotes = slidePreviewMeta.some((slide) => Boolean(slide.notes))
  const activeSlideNotes = slidePreviewMeta[activeIndex]?.notes

  useEffect(() => {
    const controller = new AbortController()
    const key = `${requestKey}:${retryKey}`

    if (!sourceUrl) {
      queueMicrotask(() => {
        if (!controller.signal.aborted) setResult({ key, error: 'Missing document preview URL.' })
      })
      return () => controller.abort()
    }

    void fetch(sourceUrl, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(await errorMessage(response))
        return previewResponseText(response)
      })
      .then((html) => {
        setPresentationView('normal')
        setNotesOpen(false)
        setSlidePreviewMeta([])
        setSlideAspectRatio('16 / 9')
        setZoom(100)
        setFitMode(kind === 'pptx' ? 'page' : 'width')
        setResult({ key, html })
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setResult({ key, error: reason instanceof Error ? reason.message : String(reason) })
      })

    return () => controller.abort()
  }, [kind, requestKey, retryKey, sourceUrl])

  useEffect(() => () => frameCleanupRef.current?.(), [])

  useEffect(() => {
    if (!window.matchMedia) return
    const mobileViewport = window.matchMedia('(max-width: 640px)')
    const handleViewportChange = (event: MediaQueryListEvent) => {
      if (event.matches) setNavigatorOpen(false)
    }
    mobileViewport.addEventListener('change', handleViewportChange)
    return () => mobileViewport.removeEventListener('change', handleViewportChange)
  }, [])

  useEffect(() => {
    const fullscreenDocument = document as WebkitFullscreenDocument
    const handleFullscreenChange = () => {
      const fullscreenElement = fullscreenDocument.fullscreenElement
        ?? fullscreenDocument.webkitFullscreenElement
        ?? null
      const active = fullscreenElement === viewerRef.current
      const wasActive = fullscreenActiveRef.current
      fullscreenActiveRef.current = active
      setIsFullscreen(active)
      if (wasActive && !active) {
        setPresentationView((view) => (
          view === 'reading' ? readingReturnViewRef.current : view
        ))
      }
    }

    document.addEventListener('fullscreenchange', handleFullscreenChange)
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange)
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange)
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange)
    }
  }, [])

  const applyZoom = useCallback((nextZoom: number, mode: FitMode = 'custom') => {
    const value = clampZoom(nextZoom)
    const document = iframeRef.current?.contentDocument
    document?.body?.style.setProperty('zoom', String(value / 100))
    setZoom(value)
    setFitMode(mode)
  }, [])

  const fitDocument = useCallback((mode: Exclude<FitMode, 'custom'>) => {
    const frame = iframeRef.current
    const document = frame?.contentDocument
    const target = itemElementsRef.current[activeIndexRef.current] ?? itemElementsRef.current[0]
    if (!frame || !document?.body || !target) return

    document.body.style.setProperty('zoom', '1')
    const width = Math.max(target.scrollWidth, target.getBoundingClientRect().width)
    const height = Math.max(target.scrollHeight, target.getBoundingClientRect().height)
    const widthScale = (frame.clientWidth - 32) / Math.max(width, 1)
    const heightScale = (frame.clientHeight - 32) / Math.max(height, 1)
    const scale = mode === 'page' ? Math.min(widthScale, heightScale) : widthScale
    applyZoom(scale * 100, mode)
  }, [applyZoom])

  useEffect(() => {
    if (fitMode === 'custom') return
    const handleResize = () => fitDocument(fitMode)
    const observer = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(handleResize)
    if (iframeRef.current) observer?.observe(iframeRef.current)
    window.addEventListener('resize', handleResize)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', handleResize)
    }
  }, [currentResult?.html, fitDocument, fitMode])

  const goToItem = useCallback((index: number) => {
    const normalized = Math.max(0, Math.min(index, itemElementsRef.current.length - 1))
    const singleSurface = kind === 'pptx' || kind === 'xlsx'
    itemElementsRef.current.forEach((item, itemIndex) => {
      if (singleSurface) item.toggleAttribute('hidden', itemIndex !== normalized)
      else item.removeAttribute('hidden')
    })
    itemElementsRef.current[normalized]?.scrollIntoView?.({
      behavior: singleSurface ? 'auto' : 'smooth',
      block: 'start',
    })
    activeIndexRef.current = normalized
    setActiveIndex(normalized)
    if (fitMode !== 'custom') {
      iframeRef.current?.contentWindow?.requestAnimationFrame(() => fitDocument(fitMode))
    }
  }, [fitDocument, fitMode, kind])

  useEffect(() => {
    if (!isPresentation || presentationView === 'sorter') return
    const frameWindow = iframeRef.current?.contentWindow
    frameWindow?.requestAnimationFrame(() => fitDocument(
      presentationView === 'reading' || fitMode === 'custom' ? 'page' : fitMode,
    ))
  }, [fitDocument, fitMode, isPresentation, presentationView])

  const exitFullscreen = useCallback(async () => {
    const fullscreenDocument = document as WebkitFullscreenDocument
    try {
      if (fullscreenDocument.exitFullscreen) await fullscreenDocument.exitFullscreen()
      else await fullscreenDocument.webkitExitFullscreen?.()
    } catch {
      // Reading View remains usable when the host denies the Fullscreen API.
    }
  }, [])

  const exitReadingView = useCallback(() => {
    setPresentationView(readingReturnViewRef.current)
    if (fullscreenActiveRef.current) void exitFullscreen()
    requestAnimationFrame(() => viewerRef.current?.focus())
  }, [exitFullscreen])

  const handleViewerKeyDown = useCallback((event: ViewerKeyEvent) => {
    const targetTag = (event.target as { tagName?: string } | null)?.tagName
    if (targetTag === 'INPUT' || targetTag === 'TEXTAREA') return
    if (isPresentation && presentationView === 'reading' && event.key === 'Escape') {
      event.preventDefault()
      exitReadingView()
      return
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'f') {
      event.preventDefault()
      setSearchOpen(true)
      return
    }
    if (event.key === '+' || event.key === '=') {
      event.preventDefault()
      applyZoom(zoom + 10)
      return
    }
    if (event.key === '-') {
      event.preventDefault()
      applyZoom(zoom - 10)
      return
    }

    const singleSurface = kind === 'pptx' || kind === 'xlsx'
    const previous = event.key === 'PageUp'
      || (singleSurface && (event.key === 'ArrowLeft' || event.key === 'ArrowUp'))
    const next = event.key === 'PageDown'
      || (kind === 'pptx' && event.key === ' ' && targetTag !== 'BUTTON')
      || (singleSurface && (event.key === 'ArrowRight' || event.key === 'ArrowDown'))
    if (previous || next) {
      event.preventDefault()
      goToItem(activeIndexRef.current + (previous ? -1 : 1))
    } else if (event.key === 'Home') {
      event.preventDefault()
      goToItem(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      goToItem(itemElementsRef.current.length - 1)
    }
  }, [applyZoom, exitReadingView, goToItem, isPresentation, kind, presentationView, zoom])

  useEffect(() => {
    viewerKeyDownRef.current = handleViewerKeyDown
  }, [handleViewerKeyDown])

  const selectSearchMatch = useCallback((index: number) => {
    const document = iframeRef.current?.contentDocument
    const marks = document ? Array.from(document.querySelectorAll<HTMLElement>('mark[data-evoflux-search]')) : []
    if (marks.length === 0) {
      setSearchIndex(0)
      return
    }
    const normalized = (index + marks.length) % marks.length
    marks.forEach((mark, markIndex) => {
      mark.style.background = markIndex === normalized ? '#fbbf24' : '#fde68a'
      mark.style.outline = markIndex === normalized ? '2px solid #d97706' : ''
    })
    const active = marks[normalized]
    const itemIndex = itemElementsRef.current.findIndex((item) => item.contains(active))
    if (itemIndex >= 0) goToItem(itemIndex)
    active.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    setSearchIndex(normalized)
  }, [goToItem])

  const refreshSearch = useCallback((query: string) => {
    const document = iframeRef.current?.contentDocument
    if (!document) return
    const matches = markSearchMatches(document, query)
    setSearchCount(matches.length)
    setSearchIndex(0)
    if (matches.length > 0) {
      matches[0].style.background = '#fbbf24'
      matches[0].style.outline = '2px solid #d97706'
      const itemIndex = itemElementsRef.current.findIndex((item) => item.contains(matches[0]))
      if (itemIndex >= 0) goToItem(itemIndex)
      matches[0].scrollIntoView?.({ block: 'center' })
    }
  }, [goToItem])

  const closeSearch = useCallback(() => {
    setSearchOpen(false)
    setSearchQuery('')
    setSearchCount(0)
    setSearchIndex(0)
    const document = iframeRef.current?.contentDocument
    if (document) clearSearchMarks(document)
  }, [])

  const handleFrameLoad = useCallback(() => {
    frameCleanupRef.current?.()
    const frame = iframeRef.current
    const document = frame?.contentDocument
    const frameWindow = frame?.contentWindow
    if (!frame || !document || !frameWindow) return

    const elements = previewItems(document)
    itemElementsRef.current = elements
    setEntries(elements.map((element, index) => ({
      index,
      label: element.dataset.previewLabel || `${kind === 'xlsx' ? 'Sheet' : kind === 'pptx' ? 'Slide' : 'Page'} ${index + 1}`,
    })))
    if (kind === 'pptx') {
      setSlidePreviewMeta(elements.map((element) => ({
        notes: slideNotes(element),
        thumbnailHtml: slideThumbnailDocument(document, element),
      })))
      const renderedSlide = elements[0]?.querySelector<HTMLElement>('.slide')
      setSlideAspectRatio(renderedSlide?.style.aspectRatio || '16 / 9')
    } else {
      setSlidePreviewMeta([])
    }
    const restoredIndex = Math.max(0, Math.min(activeIndexRef.current, elements.length - 1))
    activeIndexRef.current = restoredIndex
    setActiveIndex(restoredIndex)
    if (kind === 'pptx' || kind === 'xlsx') {
      elements.forEach((element, index) => element.toggleAttribute('hidden', index !== restoredIndex))
    }

    const style = document.createElement('style')
    style.dataset.evofluxViewer = 'true'
    style.textContent = `
      [data-evoflux-selected-cell] { outline: 2px solid #107c41 !important; outline-offset: -2px; }
      mark[data-evoflux-search] { scroll-margin: 72px; }
      [data-preview-item] { scroll-margin-top: 18px; }
      [data-preview-notes]:not([data-preview-item]) { display: none !important; }
      ${kind === 'pptx' ? `
        html, body { height: 100%; overflow: hidden !important; background: var(--evoflux-stage-background, #e8eaed) !important; }
        body { display: flex !important; align-items: center; justify-content: center; padding: 18px !important; }
        [data-preview-item] { margin: 0 !important; }
        .slide-number { display: none !important; }
      ` : ''}
    `
    document.head?.append(style)

    let scrollFrame = 0
    const handleScroll = () => {
      frameWindow.cancelAnimationFrame(scrollFrame)
      scrollFrame = frameWindow.requestAnimationFrame(() => {
        let closest = 0
        let distance = Number.POSITIVE_INFINITY
        elements.forEach((element, index) => {
          const currentDistance = Math.abs(element.getBoundingClientRect().top - 16)
          if (currentDistance < distance) {
            closest = index
            distance = currentDistance
          }
        })
        activeIndexRef.current = closest
        setActiveIndex(closest)
      })
    }
    const tracksContinuousScroll = kind === 'pdf' || kind === 'docx'
    if (tracksContinuousScroll) {
      frameWindow.addEventListener('scroll', handleScroll, { passive: true })
    }
    const handleFrameKeyDown = (event: KeyboardEvent) => viewerKeyDownRef.current(event)
    frameWindow.addEventListener('keydown', handleFrameKeyDown)

    const cells = kind === 'xlsx'
      ? Array.from(document.querySelectorAll<HTMLElement>('[data-cell]'))
      : []
    cells.forEach((cell, index) => {
      cell.setAttribute('role', 'gridcell')
      cell.tabIndex = index === 0 ? 0 : -1
    })
    document.querySelectorAll<HTMLElement>('table').forEach((table) => {
      if (table.querySelector('[data-cell]')) table.setAttribute('role', 'grid')
    })
    const selectCellElement = (target: HTMLElement, focus = false) => {
      selectedCellElementRef.current?.removeAttribute('data-evoflux-selected-cell')
      if (selectedCellElementRef.current) selectedCellElementRef.current.tabIndex = -1
      target.setAttribute('data-evoflux-selected-cell', 'true')
      target.tabIndex = 0
      selectedCellElementRef.current = target
      setSelectedCell({
        name: target.dataset.cell ?? '',
        value: target.dataset.formula ?? target.textContent?.trim() ?? '',
      })
      if (focus) target.focus()
    }
    const cellFromEvent = (event: Event) => {
      const eventTarget = event.target as Element | null
      return eventTarget?.closest<HTMLElement>('[data-cell]') ?? null
    }
    const handleCellClick = (event: Event) => {
      if (kind !== 'xlsx') return
      const target = cellFromEvent(event)
      if (!target) return
      selectCellElement(target, true)
    }
    const handleCellFocus = (event: Event) => {
      const target = cellFromEvent(event)
      if (target) selectCellElement(target)
    }
    const handleCellKeyDown = (event: KeyboardEvent) => {
      const target = cellFromEvent(event)
      if (!target) return
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
      // Keep spreadsheet arrows inside the grid. Without stopping propagation,
      // the frame-level shortcut also treats them as sheet navigation.
      event.preventDefault()
      event.stopPropagation()
      const nextName = adjacentCellName(target.dataset.cell ?? '', event.key)
      if (!nextName) return
      const surface = target.closest<HTMLElement>('[data-preview-item]')
      const next = Array.from(surface?.querySelectorAll<HTMLElement>('[data-cell]') ?? [])
        .find((cell) => cell.dataset.cell === nextName)
      if (!next) return
      selectCellElement(next, true)
    }
    document.addEventListener('click', handleCellClick)
    document.addEventListener('focusin', handleCellFocus)
    document.addEventListener('keydown', handleCellKeyDown)

    frameCleanupRef.current = () => {
      frameWindow.cancelAnimationFrame(scrollFrame)
      if (tracksContinuousScroll) frameWindow.removeEventListener('scroll', handleScroll)
      frameWindow.removeEventListener('keydown', handleFrameKeyDown)
      document.removeEventListener('click', handleCellClick)
      document.removeEventListener('focusin', handleCellFocus)
      document.removeEventListener('keydown', handleCellKeyDown)
      style.remove()
    }

    if (searchQuery) refreshSearch(searchQuery)
    frameWindow.requestAnimationFrame(() => fitDocument(fitMode === 'custom' ? 'width' : fitMode))
  }, [fitDocument, fitMode, kind, refreshSearch, searchQuery])

  useEffect(() => {
    if (!isPresentation) return
    const document = iframeRef.current?.contentDocument
    const background = presentationView === 'reading' ? '#111111' : '#e8eaed'
    document?.documentElement.style.setProperty('--evoflux-stage-background', background)
    document?.body?.style.setProperty('--evoflux-stage-background', background)
  }, [currentResult?.html, isPresentation, presentationView])

  if (currentResult?.error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-(--color-error)/10 text-(--color-error)">
          <AlertCircle size={18} aria-hidden="true" />
        </span>
        <div>
          <p className="text-sm font-medium text-(--color-text)">Document preview unavailable</p>
          <p className="mt-1 max-w-sm text-xs leading-5 text-(--color-text-muted)">{currentResult.error}</p>
        </div>
        <button
          type="button"
          onClick={() => setRetryKey((value) => value + 1)}
          className="flex items-center gap-1.5 rounded-md border border-(--color-border) px-3 py-1.5 text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key)"
        >
          <RefreshCw size={12} aria-hidden="true" /> Try again
        </button>
      </div>
    )
  }

  if (!currentResult?.html) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-(--color-text-subtle)">
        <Loader2 size={17} className="animate-spin" aria-hidden="true" />
        <span className="text-xs">Rendering {meta.label} document…</span>
      </div>
    )
  }

  const itemName = kind === 'xlsx' ? 'Sheet' : kind === 'pptx' ? 'Slide' : 'Page'
  const itemCount = entries.length
  const status = itemCount > 0 ? `${itemName} ${activeIndex + 1} of ${itemCount}` : `${meta.label} document`
  const navigatorVisible = navigatorOpen && (!isPresentation || presentationView === 'normal')

  const enterReadingView = () => {
    readingReturnViewRef.current = presentationView === 'sorter' ? 'sorter' : 'normal'
    setPresentationView('reading')
    setNotesOpen(false)
    requestAnimationFrame(() => viewerRef.current?.focus())
  }

  const toggleFullscreen = async () => {
    if (isFullscreen) {
      await exitFullscreen()
      return
    }
    const viewer = viewerRef.current as WebkitFullscreenElement | null
    try {
      if (viewer?.requestFullscreen) await viewer.requestFullscreen()
      else await viewer?.webkitRequestFullscreen?.()
    } catch {
      // Fullscreen is optional; keep the in-window Reading View as the fallback.
    }
  }

  return (
    <section
      ref={viewerRef}
      className={cn(
        'flex h-full min-h-0 flex-col overflow-hidden bg-(--bg-app)',
        isPresentation && presentationView === 'reading' && 'bg-[#111111]',
      )}
      aria-label={`${meta.label} document viewer`}
      data-testid="workspace-document-preview"
      data-presentation-view={isPresentation ? presentationView : undefined}
      tabIndex={0}
      onKeyDown={handleViewerKeyDown}
      style={{ borderTop: presentationView === 'reading' ? 'none' : `2px solid ${meta.accent}` }}
    >
      {presentationView !== 'reading' && <div className={cn(
        'flex min-h-10 shrink-0 items-center justify-between gap-2 border-b border-(--color-border) bg-(--bg-card) px-2 py-1',
        isPresentation && 'min-h-12',
      )}>
        <div className="flex min-w-0 items-center gap-1">
          {isPresentation && (
            <>
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm bg-[#b7472a] text-sm font-semibold text-white shadow-sm" aria-hidden="true">P</span>
              <span className="hidden min-w-0 max-w-44 sm:block">
                <span className="block truncate text-xs font-semibold text-(--color-text)" title={file.name}>{file.name}</span>
                <span className="block text-[9px] text-(--color-text-subtle)">PowerPoint · Saved</span>
              </span>
              <span className="mx-1 hidden h-6 w-px bg-(--color-border) sm:block" aria-hidden="true" />
            </>
          )}
          <button
            type="button"
            onClick={() => setNavigatorOpen((open) => !open)}
            aria-label={navigatorVisible
              ? `Hide ${isPresentation ? 'slide thumbnails' : 'navigator'}`
              : `Show ${isPresentation ? 'slide thumbnails' : 'navigator'}`}
            aria-pressed={navigatorVisible}
            disabled={isPresentation && presentationView === 'sorter'}
            className={cn('rounded p-1.5 text-(--color-text-muted) hover:bg-(--bg-key) disabled:cursor-not-allowed disabled:opacity-35', navigatorVisible && 'bg-(--bg-key) text-(--color-text)')}
          >
            <PanelLeft size={15} />
          </button>
          <button
            type="button"
            onClick={() => searchOpen ? closeSearch() : setSearchOpen(true)}
            aria-label={searchOpen ? 'Close document search' : 'Search document'}
            aria-pressed={searchOpen}
            className={cn('rounded p-1.5 text-(--color-text-muted) hover:bg-(--bg-key)', searchOpen && 'bg-(--bg-key) text-(--color-text)')}
          >
            <Search size={15} />
          </button>
          {searchOpen && (
            <div className="flex min-w-0 items-center rounded-xs border border-(--color-border) bg-(--bg-page)">
              <input
                autoFocus
                value={searchQuery}
                onChange={(event) => {
                  const query = event.target.value
                  setSearchQuery(query)
                  refreshSearch(query)
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') selectSearchMatch(searchIndex + (event.shiftKey ? -1 : 1))
                  if (event.key === 'Escape') closeSearch()
                }}
                placeholder="Find"
                aria-label="Find in document"
                className="h-7 w-28 min-w-0 bg-transparent px-2 text-xs text-(--color-text) outline-none sm:w-40"
              />
              <span className="whitespace-nowrap px-1 text-[10px] tabular-nums text-(--color-text-subtle)">
                {searchCount ? `${searchIndex + 1}/${searchCount}` : '0/0'}
              </span>
              <button type="button" onClick={() => selectSearchMatch(searchIndex - 1)} disabled={!searchCount} aria-label="Previous search result" className="p-1 text-(--color-text-muted) disabled:opacity-30"><ChevronLeft size={13} /></button>
              <button type="button" onClick={() => selectSearchMatch(searchIndex + 1)} disabled={!searchCount} aria-label="Next search result" className="p-1 text-(--color-text-muted) disabled:opacity-30"><ChevronRight size={13} /></button>
            </div>
          )}
        </div>

        <div className="hidden items-center gap-1 sm:flex">
          <button type="button" onClick={() => goToItem(activeIndex - 1)} disabled={activeIndex <= 0} aria-label={`Previous ${itemName.toLowerCase()}`} className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-30"><ChevronLeft size={15} /></button>
          <span className="min-w-24 text-center text-[11px] tabular-nums text-(--color-text-muted)" role="status">{status}</span>
          <button type="button" onClick={() => goToItem(activeIndex + 1)} disabled={activeIndex >= itemCount - 1} aria-label={`Next ${itemName.toLowerCase()}`} className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-30"><ChevronRight size={15} /></button>
        </div>

        <div className="flex shrink-0 items-center gap-0.5">
          {isPresentation && (
            <span className="mr-1 hidden rounded-full border border-(--color-border) px-2 py-0.5 text-[9px] font-medium text-(--color-text-muted) lg:inline">Read only</span>
          )}
          <button type="button" onClick={() => applyZoom(zoom - 10)} aria-label="Zoom out" className="rounded p-1.5 text-(--color-text-muted) hover:bg-(--bg-key)"><ZoomOut size={14} /></button>
          <button type="button" onClick={() => applyZoom(zoom + 10)} aria-label="Zoom in" className="rounded p-1.5 text-(--color-text-muted) hover:bg-(--bg-key)"><ZoomIn size={14} /></button>
          <span className="w-10 text-center text-[10px] tabular-nums text-(--color-text-muted)" aria-label={`Zoom ${zoom} percent`}>{zoom}%</span>
          <button type="button" onClick={() => fitDocument('width')} aria-label="Fit width" title="Fit width" className={cn('rounded px-1.5 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)', fitMode === 'width' && 'bg-(--bg-key) text-(--color-text)')}>Width</button>
          <button type="button" onClick={() => fitDocument('page')} aria-label="Fit page" title="Fit page" className={cn('rounded p-1.5 text-(--color-text-muted) hover:bg-(--bg-key)', fitMode === 'page' && 'bg-(--bg-key) text-(--color-text)')}><Maximize2 size={13} /></button>
          <ChevronDown size={10} className="hidden text-(--color-text-subtle) lg:block" aria-hidden="true" />
        </div>
      </div>}

      {isPresentation && presentationView !== 'reading' && (
        <div
          className="flex min-h-11 shrink-0 items-stretch gap-1 overflow-x-auto border-b border-(--color-border) bg-(--bg-card) px-2"
          role="toolbar"
          aria-label="PowerPoint View controls"
        >
          <span className="flex shrink-0 items-center border-b-2 border-[#b7472a] px-2 text-[11px] font-semibold text-[#b7472a]">View</span>
          <span className="my-2 w-px shrink-0 bg-(--color-border)" aria-hidden="true" />
          <button
            type="button"
            onClick={() => setPresentationView('normal')}
            aria-label="Normal view"
            aria-pressed={presentationView === 'normal'}
            className={cn(
              'flex shrink-0 items-center gap-1.5 rounded-sm px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)',
              presentationView === 'normal' && 'bg-(--bg-key) font-medium text-(--color-text)',
            )}
          >
            <PanelsTopLeft size={15} aria-hidden="true" /> Normal
          </button>
          <button
            type="button"
            onClick={() => setPresentationView('sorter')}
            aria-label="Slide sorter view"
            aria-pressed={presentationView === 'sorter'}
            className={cn(
              'flex shrink-0 items-center gap-1.5 rounded-sm px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)',
              presentationView === 'sorter' && 'bg-(--bg-key) font-medium text-(--color-text)',
            )}
          >
            <LayoutGrid size={15} aria-hidden="true" /> Slide Sorter
          </button>
          <button
            type="button"
            onClick={enterReadingView}
            aria-label="Start Reading View slide show"
            aria-pressed="false"
            className="flex shrink-0 items-center gap-1.5 rounded-sm px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)"
          >
            <MonitorPlay size={15} aria-hidden="true" /> Reading View
          </button>
          {hasSlideNotes && (
            <button
              type="button"
              onClick={() => {
                setPresentationView('normal')
                setNotesOpen((open) => !open)
              }}
              aria-label={notesOpen ? 'Hide speaker notes' : 'Show speaker notes'}
              aria-pressed={notesOpen}
              className={cn(
                'flex shrink-0 items-center gap-1.5 rounded-sm px-2 py-1 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)',
                notesOpen && 'bg-(--bg-key) font-medium text-(--color-text)',
              )}
            >
              <NotepadText size={15} aria-hidden="true" /> Notes
            </button>
          )}
          <span className="ml-auto hidden shrink-0 items-center px-2 text-[9px] text-(--color-text-subtle) md:flex">
            Arrow keys or Page Up/Down to navigate
          </span>
        </div>
      )}

      {kind === 'xlsx' && (
        <div className="flex h-8 shrink-0 items-center border-b border-(--color-border) bg-(--bg-card) text-xs">
          <div className="flex h-full w-20 shrink-0 items-center border-r border-(--color-border) px-2 font-mono text-(--color-text-2)" aria-label="Selected cell">
            {selectedCell?.name || '—'}
          </div>
          <div className="flex h-full w-7 shrink-0 items-center justify-center border-r border-(--color-border) font-serif italic text-(--color-text-muted)" aria-hidden="true">fx</div>
          <div className="min-w-0 flex-1 truncate px-2 font-mono text-(--color-text-2)" aria-label="Formula bar">
            {selectedCell?.value || 'Select a cell'}
          </div>
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {navigatorVisible && isPresentation && (
          <nav
            className="z-(--z-drawer) w-48 shrink-0 overflow-y-auto border-r border-(--color-border) bg-(--bg-card) px-2 py-3 max-[640px]:absolute max-[640px]:inset-y-0 max-[640px]:left-0 max-[640px]:w-44 max-[640px]:shadow-xl"
            aria-label="Slide thumbnails"
          >
            <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">Slides</p>
            <div className="space-y-2">
              {entries.map((entry) => {
                const selected = activeIndex === entry.index
                return (
                  <button
                    key={`${entry.label}:${entry.index}`}
                    type="button"
                    onClick={() => {
                      goToItem(entry.index)
                      if (window.matchMedia?.('(max-width: 640px)').matches) setNavigatorOpen(false)
                    }}
                    aria-label={`Go to slide ${entry.index + 1}: ${entry.label}`}
                    aria-current={selected ? 'page' : undefined}
                    className={cn(
                      'flex w-full items-start gap-1.5 rounded-sm p-1 text-left transition-colors hover:bg-(--bg-key)',
                      selected && 'bg-[#b7472a]/8',
                    )}
                  >
                    <span className={cn(
                      'w-4 shrink-0 pt-1 text-right text-[10px] tabular-nums text-(--color-text-subtle)',
                      selected && 'font-semibold text-[#b7472a]',
                    )}>{entry.index + 1}</span>
                    <span
                      className="relative min-w-0 flex-1 overflow-hidden rounded-[2px] border-2 bg-white shadow-sm"
                      style={{
                        aspectRatio: slideAspectRatio,
                        borderColor: selected ? meta.accent : 'var(--color-border-strong)',
                      }}
                    >
                      <SlideThumbnail
                        html={slidePreviewMeta[entry.index]?.thumbnailHtml}
                        label={`Thumbnail for slide ${entry.index + 1}`}
                      />
                    </span>
                  </button>
                )
              })}
            </div>
          </nav>
        )}
        {navigatorVisible && !isPresentation && (
          <nav className="z-(--z-panel) w-40 shrink-0 overflow-y-auto border-r border-(--color-border) bg-(--bg-card) p-2 max-[640px]:absolute max-[640px]:inset-y-0 max-[640px]:left-0 max-[640px]:shadow-xl" aria-label="Document navigator">
            <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">{itemName}s</p>
            <div className="space-y-1.5">
              {entries.map((entry) => (
                <button
                  key={`${entry.label}:${entry.index}`}
                  type="button"
                  onClick={() => goToItem(entry.index)}
                  aria-current={activeIndex === entry.index ? 'page' : undefined}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-xs border px-2 py-2 text-left text-[11px] transition-colors',
                    activeIndex === entry.index
                      ? 'border-(--color-accent) bg-(--color-accent)/8 text-(--color-text)'
                      : 'border-(--color-border) bg-(--bg-page) text-(--color-text-muted) hover:border-(--color-border-strong)',
                  )}
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xs bg-white text-[10px] font-semibold shadow-sm" style={{ color: meta.accent }}>{entry.index + 1}</span>
                  <span className="truncate" title={entry.label}>{entry.label}</span>
                </button>
              ))}
            </div>
          </nav>
        )}
        <div className={cn(
          'flex min-w-0 flex-1 flex-col',
          isPresentation && presentationView === 'reading' ? 'bg-[#111111]' : 'bg-[#e8eaed]',
        )}>
          <div className="relative min-h-0 flex-1">
            <iframe
              ref={iframeRef}
              title={`Preview ${file.name}`}
              srcDoc={currentResult.html}
              onLoad={handleFrameLoad}
              sandbox="allow-same-origin"
              referrerPolicy="no-referrer"
              className={cn(
                'h-full min-h-0 w-full border-0',
                isPresentation && presentationView === 'reading' ? 'bg-[#111111]' : 'bg-[#e8eaed]',
              )}
              data-testid="document-preview-frame"
            />
            {isPresentation && presentationView === 'sorter' && (
              <section
                className="absolute inset-0 overflow-y-auto bg-[#e5e5e5] p-4 sm:p-6"
                aria-label="Slide sorter"
              >
                <div className="mx-auto grid max-w-6xl grid-cols-1 gap-x-5 gap-y-6 min-[460px]:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                  {entries.map((entry) => {
                    const selected = activeIndex === entry.index
                    return (
                      <button
                        key={`sorter:${entry.label}:${entry.index}`}
                        type="button"
                        onClick={() => {
                          goToItem(entry.index)
                          setPresentationView('normal')
                        }}
                        aria-label={`Open slide ${entry.index + 1}: ${entry.label}`}
                        aria-current={selected ? 'page' : undefined}
                        className="group min-w-0 rounded-sm text-left outline-none"
                      >
                        <span
                          className="block overflow-hidden rounded-[3px] border-2 bg-white shadow-md transition group-hover:shadow-lg group-focus-visible:ring-2 group-focus-visible:ring-[#b7472a]/50"
                          style={{
                            aspectRatio: slideAspectRatio,
                            borderColor: selected ? meta.accent : 'transparent',
                          }}
                        >
                          <SlideThumbnail
                            html={slidePreviewMeta[entry.index]?.thumbnailHtml}
                            label={`Sorter preview for slide ${entry.index + 1}`}
                          />
                        </span>
                        <span className="mt-1.5 flex min-w-0 items-center gap-2 px-0.5">
                          <span className={cn(
                            'text-[10px] tabular-nums text-(--color-text-subtle)',
                            selected && 'font-semibold text-[#b7472a]',
                          )}>{entry.index + 1}</span>
                          <span className="truncate text-[10px] text-(--color-text-muted)" title={entry.label}>{entry.label}</span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              </section>
            )}
            {isPresentation && presentationView === 'reading' && (
              <section
                className="pointer-events-none absolute inset-0 z-(--z-panel)"
                aria-label="PowerPoint reading view"
              >
                <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-3 bg-gradient-to-b from-black/75 to-transparent p-3 text-white sm:p-4">
                  <div className="min-w-0 rounded-full bg-black/55 px-3 py-1.5 shadow-lg backdrop-blur-sm">
                    <p className="truncate text-[11px] font-medium" title={file.name}>{file.name}</p>
                    <p className="text-[9px] text-white/65">Reading View · Slide Show</p>
                  </div>
                  <div className="pointer-events-auto flex shrink-0 items-center gap-1.5">
                    {fullscreenSupported && (
                      <button
                        type="button"
                        onClick={() => void toggleFullscreen()}
                        aria-label={isFullscreen ? 'Exit full screen' : 'Enter full screen'}
                        className="flex h-10 w-10 items-center justify-center rounded-full bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                      >
                        {isFullscreen
                          ? <Minimize2 size={18} aria-hidden="true" />
                          : <Maximize2 size={18} aria-hidden="true" />}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={exitReadingView}
                      aria-label="Exit Reading View"
                      className="flex h-10 w-10 items-center justify-center rounded-full bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    >
                      <X size={19} aria-hidden="true" />
                    </button>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => goToItem(activeIndex - 1)}
                  disabled={activeIndex <= 0}
                  aria-label="Previous slide in Reading View"
                  className="pointer-events-auto absolute left-2 top-1/2 flex h-12 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:pointer-events-none disabled:opacity-0 sm:left-4 sm:h-14 sm:w-12"
                >
                  <ChevronLeft size={24} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => goToItem(activeIndex + 1)}
                  disabled={activeIndex >= itemCount - 1}
                  aria-label="Next slide in Reading View"
                  className="pointer-events-auto absolute right-2 top-1/2 flex h-12 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white shadow-lg backdrop-blur-sm transition hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:pointer-events-none disabled:opacity-0 sm:right-4 sm:h-14 sm:w-12"
                >
                  <ChevronRight size={24} aria-hidden="true" />
                </button>

                <div
                  className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-3 py-1.5 text-[11px] font-medium tabular-nums text-white shadow-lg backdrop-blur-sm sm:bottom-4"
                  role="status"
                  aria-live="polite"
                >
                  {status}
                </div>
              </section>
            )}
          </div>
          {isPresentation && presentationView === 'normal' && notesOpen && hasSlideNotes && (
            <section
              className="h-28 shrink-0 overflow-y-auto border-t border-(--color-border-strong) bg-(--bg-card) px-4 py-2 sm:h-32"
              aria-label="Speaker notes"
            >
              <div className="mx-auto max-w-4xl">
                <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
                  <NotepadText size={12} aria-hidden="true" /> Notes
                </div>
                <p className="whitespace-pre-wrap text-xs leading-5 text-(--color-text-2)">
                  {activeSlideNotes || 'No notes for this slide.'}
                </p>
              </div>
            </section>
          )}
        </div>
      </div>

      {presentationView !== 'reading' && <div className="flex h-6 shrink-0 items-center justify-between border-t border-(--color-border) bg-(--bg-card) px-2 text-[10px] text-(--color-text-subtle)">
        <span className="truncate">{file.name}</span>
        <span className="shrink-0 tabular-nums sm:hidden" role="status">{status}</span>
        <span className="hidden shrink-0 items-center gap-2 sm:flex">
          {isPresentation && <span className="tabular-nums" role="status">{status}</span>}
          <span>{isPresentation ? `${presentationView === 'normal' ? 'Normal' : 'Slide Sorter'} · ` : ''}Read only · {meta.label}</span>
        </span>
      </div>}
    </section>
  )
}
