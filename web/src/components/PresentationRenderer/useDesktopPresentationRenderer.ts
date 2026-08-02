import { useEffect } from 'react'
import { domToPng } from 'modern-screenshot'

import { apiBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { getPlatform } from '@/hooks/use-platform'

interface RenderRequest {
  id: string
  action: 'render_slide'
  params: {
    document: string
    inspectionScript: string
    inspectionParams: Record<string, unknown>
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

const CANVAS_WIDTH = 1600
const CANVAS_HEIGHT = 900
const PIXEL_RATIO = 2
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
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.setAttribute('sandbox', 'allow-same-origin allow-scripts')
  Object.assign(frame.style, {
    position: 'fixed',
    left: '0',
    top: '0',
    width: `${CANVAS_WIDTH}px`,
    height: `${CANVAS_HEIGHT}px`,
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

    const imageOptions = {
      scale: PIXEL_RATIO,
    }
    const preview = await domToPng(slide, {
      ...imageOptions,
      width: CANVAS_WIDTH,
      height: CANVAS_HEIGHT,
    })
    const nativeImages = await Promise.all(
      inspection.nativeImages.map(async ({ exportId }) => {
        const element = frameDocument.querySelector<HTMLElement>(
          `[data-pptx-export-image="${cssEscape(exportId)}"]`,
        )
        if (!element) {
          throw new Error(`Editable image ${exportId} disappeared during rendering`)
        }
        return { exportId, data: await domToPng(element, imageOptions) }
      }),
    )

    const hasNativeObjects = Boolean(
      inspection.nativeText.length
      || inspection.nativeShapes.length
      || nativeImages.length,
    )
    let background = preview
    if (hasNativeObjects) {
      const style = frameDocument.createElement('style')
      style.textContent = HIDE_EDITABLE_CSS
      frameDocument.head.append(style)
      await nextPaint(frameWindow)
      background = await domToPng(slide, {
        ...imageOptions,
        width: CANVAS_WIDTH,
        height: CANVAS_HEIGHT,
      })
    }

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

function cssEscape(value: string): string {
  return value.replace(/["\\]/g, '\\$&')
}

function rendererUrl(sessionId: string): string {
  const apiBase = apiBaseUrl()
  const wsBase = apiBase.startsWith('http')
    ? apiBase.replace(/^http/, 'ws')
    : `ws://${window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname}:8000/api`
  return withTokenParam(
    `${wsBase}/team/${encodeURIComponent(sessionId)}/presentation-renderer`,
  )
}
