import { useEffect } from 'react'
import { domToPng } from 'modern-screenshot'

import { apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { getPlatform } from '@/hooks/use-platform'

interface SlideCanvas {
  width: number
  height: number
  exportPixelRatio: number
  previewPixelRatio: number
}

interface RenderRequest {
  id: string
  action: 'render_slide'
  params: {
    document: string
    inspectionScript: string
    inspectionParams: Record<string, unknown>
    canvas: SlideCanvas
  }
}

interface NativeImage {
  exportId: string
  [key: string]: unknown
}

interface InspectionResult {
  issues: unknown[]
  nativeText: unknown[]
  nativeShapes: unknown[]
  nativeImages: NativeImage[]
}

export interface DesktopSlideRenderResult {
  inspection: InspectionResult
  preview: string
  background: string
  nativeImages: Array<{ exportId: string; data: string }>
}

const CHUNK_CHARS = 256_000
const HIDE_EDITABLE_CSS = `
[data-pptx-export-text],
[data-pptx-export-text] * {
  color: transparent !important;
  text-shadow: none !important;
  -webkit-text-stroke-color: transparent !important;
}
[data-pptx-export-shape] {
  background-color: transparent !important;
  border-color: transparent !important;
  outline-color: transparent !important;
}
[data-pptx-export-image] { visibility: hidden !important; }
`

export function useDesktopPresentationRenderer(sessionId: string | null): void {
  useEffect(() => {
    if (!sessionId || !getPlatform().isTauri) return
    let alive = true
    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    const requestChunks = new Map<string, { total: number; parts: Map<number, string> }>()

    const connect = () => {
      if (!alive) return
      socket = new WebSocket(rendererUrl(sessionId))
      socket.onopen = () => socket?.send(JSON.stringify({ type: 'ready' }))
      socket.onmessage = (event) => {
        if (typeof event.data !== 'string' || !socket) return
        const activeSocket = socket
        let raw: string | null
        try {
          raw = acceptRequestMessage(event.data, requestChunks)
        } catch (error) {
          sendResponse(activeSocket, {
            id: requestIdFromMessage(event.data),
            ok: false,
            error: error instanceof Error ? error.message : String(error),
          })
          return
        }
        if (raw === null) return
        void handleRequest(raw)
          .then((message) => sendResponse(activeSocket, message))
          .catch((error: unknown) => {
            const requestId = requestIdFromMessage(raw)
            sendResponse(activeSocket, {
              id: requestId,
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            })
          })
      }
      socket.onclose = () => {
        socket = null
        requestChunks.clear()
        if (alive) reconnectTimer = setTimeout(connect, 1000)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      alive = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [sessionId])
}

function acceptRequestMessage(
  raw: string,
  chunks: Map<string, { total: number; parts: Map<number, string> }>,
): string | null {
  const message = JSON.parse(raw) as {
    type?: unknown
    id?: unknown
    index?: unknown
    total?: unknown
    data?: unknown
  }
  if (message.type !== 'request_chunk') return raw
  if (
    typeof message.id !== 'string'
    || typeof message.index !== 'number'
    || typeof message.total !== 'number'
    || typeof message.data !== 'string'
    || message.total < 1
    || message.total > 4096
    || message.index < 0
    || message.index >= message.total
  ) {
    throw new Error('Invalid desktop presentation request chunk')
  }
  const state = chunks.get(message.id) ?? {
    total: message.total,
    parts: new Map<number, string>(),
  }
  if (state.total !== message.total) {
    throw new Error('Desktop presentation request chunk count changed')
  }
  state.parts.set(message.index, message.data)
  chunks.set(message.id, state)
  if (state.parts.size !== state.total) return null
  chunks.delete(message.id)
  return Array.from({ length: state.total }, (_, index) => {
    const part = state.parts.get(index)
    if (part === undefined) throw new Error('Desktop presentation request lost a chunk')
    return part
  }).join('')
}

function sendResponse(socket: WebSocket, message: Record<string, unknown>): void {
  if (socket.readyState !== WebSocket.OPEN) return
  const raw = JSON.stringify(message)
  if (raw.length <= CHUNK_CHARS) {
    socket.send(raw)
    return
  }
  const requestId = typeof message.id === 'string' ? message.id : null
  const parts = Array.from(
    { length: Math.ceil(raw.length / CHUNK_CHARS) },
    (_, index) => raw.slice(index * CHUNK_CHARS, (index + 1) * CHUNK_CHARS),
  )
  parts.forEach((data, index) => socket.send(JSON.stringify({
    type: 'response_chunk',
    id: requestId,
    index,
    total: parts.length,
    data,
  })))
}

async function handleRequest(raw: string): Promise<{
  id: string
  ok: true
  result: DesktopSlideRenderResult
}> {
  const request = JSON.parse(raw) as RenderRequest
  if (
    typeof request.id !== 'string'
    || request.action !== 'render_slide'
    || typeof request.params?.document !== 'string'
    || typeof request.params?.inspectionScript !== 'string'
    || !isSlideCanvas(request.params?.canvas)
  ) {
    throw new Error('Invalid desktop presentation render request')
  }
  return {
    id: request.id,
    ok: true,
    result: await renderSlideInWebView(request.params),
  }
}

export async function renderSlideInWebView(
  params: RenderRequest['params'],
): Promise<DesktopSlideRenderResult> {
  const canvas = params.canvas
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.setAttribute('sandbox', 'allow-same-origin allow-scripts')
  Object.assign(frame.style, {
    position: 'fixed',
    left: '0',
    top: '0',
    width: `${canvas.width}px`,
    height: `${canvas.height}px`,
    border: '0',
    zIndex: '-2147483647',
    pointerEvents: 'none',
  })

  try {
    const loaded = new Promise<void>((resolve, reject) => {
      frame.onload = () => resolve()
      frame.onerror = () => reject(new Error('Slide iframe failed to load'))
    })
    frame.srcdoc = params.document
    document.body.append(frame)
    await loaded

    const frameWindow = frame.contentWindow
    const frameDocument = frame.contentDocument
    if (!frameWindow || !frameDocument) {
      throw new Error('Slide iframe is not accessible')
    }
    await waitForAssets(frameDocument)
    await nextPaint(frameWindow)

    const frameFunction = (frameWindow as unknown as {
      Function: FunctionConstructor
    }).Function
    const inspector = frameFunction(
      `"use strict"; return (${params.inspectionScript});`,
    )() as (values: Record<string, unknown>) => InspectionResult
    const inspection = inspector(params.inspectionParams)
    const slide = frameDocument.querySelector<HTMLElement>('.slide')
    if (!slide) throw new Error('Slide document has no .slide root')

    const nativeImages = await Promise.all(
      inspection.nativeImages.map(async ({ exportId }) => {
        const element = frameDocument.querySelector<HTMLElement>(
          `[data-pptx-export-image="${cssEscape(exportId)}"]`,
        )
        if (!element) {
          throw new Error(`Editable image ${exportId} disappeared during rendering`)
        }
        return {
          exportId,
          data: await domToPng(element, { scale: canvas.exportPixelRatio }),
        }
      }),
    )

    const hasNativeObjects = Boolean(
      inspection.nativeText.length
      || inspection.nativeShapes.length
      || nativeImages.length,
    )
    const exportOptions = {
      scale: canvas.exportPixelRatio,
      width: canvas.width,
      height: canvas.height,
    }
    if (!hasNativeObjects) {
      // Nothing is overlaid natively, so a single raster is both the background
      // embedded in the deck and the preview.
      const background = await domToPng(slide, exportOptions)
      return { inspection, preview: background, background, nativeImages }
    }

    // The preview is only a QA thumbnail and an attachment card, so it renders
    // at the cheaper ratio. It has to be captured before the editable layer is
    // hidden, because it is the one image that shows the slide as designed.
    const preview = await domToPng(slide, {
      scale: canvas.previewPixelRatio,
      width: canvas.width,
      height: canvas.height,
    })
    const style = frameDocument.createElement('style')
    style.textContent = HIDE_EDITABLE_CSS
    frameDocument.head.append(style)
    await nextPaint(frameWindow)
    const background = await domToPng(slide, exportOptions)

    return { inspection, preview, background, nativeImages }
  } finally {
    frame.remove()
  }
}

async function waitForAssets(target: Document): Promise<void> {
  if (target.fonts) await target.fonts.ready
  await Promise.all(
    Array.from(target.images, (image) => {
      if (image.complete) return Promise.resolve()
      return new Promise<void>((resolve) => {
        image.addEventListener('load', () => resolve(), { once: true })
        image.addEventListener('error', () => resolve(), { once: true })
      })
    }),
  )
}

async function nextPaint(target: Window): Promise<void> {
  await new Promise<void>((resolve) => {
    target.requestAnimationFrame(() => target.requestAnimationFrame(() => resolve()))
  })
}

function requestIdFromMessage(raw: string): string | null {
  try {
    const parsed = JSON.parse(raw) as { id?: unknown }
    return typeof parsed.id === 'string' ? parsed.id : null
  } catch {
    return null
  }
}

function isSlideCanvas(value: unknown): value is SlideCanvas {
  if (typeof value !== 'object' || value === null) return false
  const canvas = value as Record<string, unknown>
  return (['width', 'height', 'exportPixelRatio', 'previewPixelRatio'] as const).every(
    (key) => typeof canvas[key] === 'number' && (canvas[key] as number) > 0,
  )
}

function cssEscape(value: string): string {
  return value.replace(/["\\]/g, '\\$&')
}

function rendererUrl(sessionId: string): string {
  return withTokenParam(
    `${apiWsBaseUrl()}/team/${encodeURIComponent(sessionId)}/presentation-renderer`,
  )
}
