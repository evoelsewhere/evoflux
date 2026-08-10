import { useEffect } from 'react'
import { apiUrl } from '@/api/base-url'
import { useTeamStore } from '@/stores/useTeamStore'
import { renderHtmlSlide } from './html-slide-renderer'
import type { RenderRequest } from './slide-editable'

const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds))

export function ArtifactSlideRenderBridge() {
  const sessionId = useTeamStore((state) => state.sessionId)

  useEffect(() => {
    if (!sessionId) return
    const controller = new AbortController()
    let stopped = false
    let lastHeartbeatAt = 0

    const post = (path: string, body?: unknown) => fetch(apiUrl(path), {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })

    const loop = async () => {
      while (!stopped) {
        try {
          const now = Date.now()
          if (now - lastHeartbeatAt >= 5_000) {
            const heartbeat = await post(`/artifacts/renderers/${encodeURIComponent(sessionId)}/heartbeat`)
            if (!heartbeat.ok) throw new Error(`Slide renderer heartbeat failed with ${heartbeat.status}.`)
            lastHeartbeatAt = now
          }
          const response = await fetch(apiUrl(`/artifacts/renderers/${encodeURIComponent(sessionId)}/next`), {
            cache: 'no-store',
            signal: controller.signal,
          })
          if (response.status === 204) {
            await sleep(750)
            continue
          }
          if (!response.ok) throw new Error(`Slide render poll failed with ${response.status}.`)
          const request = await response.json() as RenderRequest
          try {
            const result = await renderHtmlSlide(request)
            const completed = await post(
              `/artifacts/renderers/${encodeURIComponent(sessionId)}/requests/${encodeURIComponent(request.request_id)}/complete`,
              result,
            )
            if (!completed.ok && completed.status !== 404) throw new Error(`Slide render completion failed with ${completed.status}.`)
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            await post(
              `/artifacts/renderers/${encodeURIComponent(sessionId)}/requests/${encodeURIComponent(request.request_id)}/fail`,
              { message },
            ).catch(() => undefined)
          }
        } catch (_error) {
          if (controller.signal.aborted || stopped) return
          await sleep(1_000)
        }
      }
    }
    void loop()
    return () => {
      stopped = true
      controller.abort()
    }
  }, [sessionId])

  return null
}
