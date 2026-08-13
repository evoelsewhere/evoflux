import { useEffect } from 'react'
import { apiUrl } from '@/api/base-url'
import { renderHtmlSlide } from './html-slide-renderer'
import type { RenderRequest } from './slide-editable'

const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds))
const HEARTBEAT_INTERVAL_MS = 5_000
const POLL_INTERVAL_MS = 750
const FALLBACK_RENDERER_ID = '00000000-0000-4000-8000-000000000001'

function createRendererId(): string {
  return globalThis.crypto?.randomUUID?.() ?? FALLBACK_RENDERER_ID
}

export function ArtifactSlideRenderBridge() {
  useEffect(() => {
    const rendererId = createRendererId()
    const controller = new AbortController()
    let stopped = false
    let lastReportedError = ''

    const post = (path: string, body?: unknown) => fetch(apiUrl(path), {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })

    const reportError = (error: unknown) => {
      if (controller.signal.aborted || stopped) return
      const message = error instanceof Error ? error.message : String(error)
      if (message === lastReportedError) return
      lastReportedError = message
      console.warn(`[ArtifactSlideRenderBridge] ${message}`)
    }

    // Heartbeat independently from raster work. A large slide can occupy the
    // render loop for many seconds and must not make the backend revoke the
    // otherwise healthy desktop renderer.
    const heartbeatLoop = async () => {
      while (!stopped) {
        try {
          const heartbeat = await post(
            `/artifacts/renderers/global/${encodeURIComponent(rendererId)}/heartbeat`,
          )
          if (!heartbeat.ok) {
            throw new Error(`Slide renderer heartbeat failed with ${heartbeat.status}.`)
          }
          lastReportedError = ''
        } catch (error) {
          reportError(error)
        }
        await sleep(HEARTBEAT_INTERVAL_MS)
      }
    }

    const renderLoop = async () => {
      while (!stopped) {
        try {
          const response = await fetch(apiUrl(
            `/artifacts/renderers/global/${encodeURIComponent(rendererId)}/next`,
          ), {
            cache: 'no-store',
            signal: controller.signal,
          })
          if (response.status === 204) {
            await sleep(POLL_INTERVAL_MS)
            continue
          }
          if (!response.ok) throw new Error(`Slide render poll failed with ${response.status}.`)
          const request = await response.json() as RenderRequest
          try {
            const result = await renderHtmlSlide(request)
            const completed = await post(
              `/artifacts/renderers/global/${encodeURIComponent(rendererId)}/requests/${encodeURIComponent(request.request_id)}/complete`,
              result,
            )
            if (!completed.ok && completed.status !== 404) throw new Error(`Slide render completion failed with ${completed.status}.`)
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            await post(
              `/artifacts/renderers/global/${encodeURIComponent(rendererId)}/requests/${encodeURIComponent(request.request_id)}/fail`,
              { message },
            ).catch(() => undefined)
          }
        } catch (error) {
          if (controller.signal.aborted || stopped) return
          reportError(error)
          await sleep(1_000)
        }
      }
    }
    void heartbeatLoop()
    void renderLoop()
    return () => {
      stopped = true
      controller.abort()
    }
  }, [])

  return null
}
