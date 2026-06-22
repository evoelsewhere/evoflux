import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  forwardRef,
} from 'react'

import { apiBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'

export interface ScreencastStatus {
  active: boolean
  url?: string
  title?: string
  tabs?: Array<{ index: number; url: string; title: string }>
  cdpHttp?: string
  cdp_http?: string
}

export interface ScreencastHandle {
  send: (msg: Record<string, unknown>) => void
}

interface ScreencastCanvasProps {
  sessionId: string
  interactive?: boolean
  onStatus?: (status: ScreencastStatus) => void
  onConnected?: (connected: boolean) => void
  onFrame?: () => void
  className?: string
}

export const ScreencastCanvas = forwardRef<ScreencastHandle, ScreencastCanvasProps>(
  function ScreencastCanvas(
    { sessionId, interactive = false, onStatus, onConnected, onFrame, className },
    ref,
  ) {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const wsRef = useRef<WebSocket | null>(null)
    const imgRef = useRef<HTMLImageElement | null>(null)
    const frameSizeRef = useRef<{ w: number; h: number }>({ w: 1, h: 1 })

    const notifyConnected = useCallback(
      (v: boolean) => {
        onConnected?.(v)
      },
      [onConnected],
    )

    useImperativeHandle(
      ref,
      () => ({
        send(msg: Record<string, unknown>) {
          const ws = wsRef.current
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg))
          }
        },
      }),
      [],
    )

    // ── Canvas → page coordinate mapping ────────────────────────────
    const canvasToPage = useCallback(
      (clientX: number, clientY: number): { x: number; y: number } | null => {
        const canvas = canvasRef.current
        if (!canvas) return null
        const rect = canvas.getBoundingClientRect()
        const { w, h } = frameSizeRef.current

        // Canvas uses object-fit: contain — compute the visible area
        const canvasAspect = w / h
        const rectAspect = rect.width / rect.height
        let drawW: number, drawH: number, offsetX: number, offsetY: number
        if (rectAspect > canvasAspect) {
          // Pillarboxed (bars on left/right)
          drawH = rect.height
          drawW = drawH * canvasAspect
          offsetX = rect.left + (rect.width - drawW) / 2
          offsetY = rect.top
        } else {
          // Letterboxed (bars on top/bottom)
          drawW = rect.width
          drawH = drawW / canvasAspect
          offsetX = rect.left
          offsetY = rect.top + (rect.height - drawH) / 2
        }

        const relX = clientX - offsetX
        const relY = clientY - offsetY
        if (relX < 0 || relY < 0 || relX > drawW || relY > drawH) return null

        return {
          x: Math.round((relX / drawW) * w),
          y: Math.round((relY / drawH) * h),
        }
      },
      [],
    )

    const sendJson = useCallback((msg: Record<string, unknown>) => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg))
      }
    }, [])

    // ── Mouse/keyboard handlers ─────────────────────────────────────
    const handleClick = useCallback(
      (e: React.MouseEvent<HTMLCanvasElement>) => {
        if (!interactive) return
        const pos = canvasToPage(e.clientX, e.clientY)
        if (!pos) return
        sendJson({
          action: e.detail === 2 ? 'dblclick' : 'click',
          x: pos.x,
          y: pos.y,
          button: e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left',
        })
      },
      [interactive, canvasToPage, sendJson],
    )

    const handleWheel = useCallback(
      (e: React.WheelEvent<HTMLCanvasElement>) => {
        if (!interactive) return
        e.preventDefault()
        sendJson({ action: 'scroll', dx: Math.round(e.deltaX), dy: Math.round(e.deltaY) })
      },
      [interactive, sendJson],
    )

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLCanvasElement>) => {
        if (!interactive) return
        e.preventDefault()

        // Build key string matching Playwright's key format
        let key = e.key
        if (key === ' ') key = 'Space'
        else if (key === 'Escape') key = 'Escape'
        else if (key === 'ArrowUp') key = 'ArrowUp'
        else if (key === 'ArrowDown') key = 'ArrowDown'
        else if (key === 'ArrowLeft') key = 'ArrowLeft'
        else if (key === 'ArrowRight') key = 'ArrowRight'

        // Modifier combos
        const mods: string[] = []
        if (e.ctrlKey) mods.push('Control')
        if (e.metaKey) mods.push('Meta')
        if (e.shiftKey) mods.push('Shift')
        if (e.altKey) mods.push('Alt')

        if (mods.length > 0 && key.length === 1) {
          // Ctrl+A, Ctrl+C, etc.
          sendJson({ action: 'key', key: `${mods.join('+')}+${key.toUpperCase()}` })
        } else if (key === 'Backspace') {
          sendJson({ action: 'key', key: 'Backspace' })
        } else if (key === 'Enter') {
          sendJson({ action: 'key', key: 'Enter' })
        } else if (key === 'Tab') {
          sendJson({ action: 'key', key: 'Tab' })
        } else if (key.length === 1) {
          sendJson({ action: 'type', text: key })
        } else {
          sendJson({ action: 'key', key })
        }
      },
      [interactive, sendJson],
    )

    const handleContextMenu = useCallback((e: React.MouseEvent) => {
      e.preventDefault()
    }, [])

    // ── WebSocket connection ────────────────────────────────────────
    useEffect(() => {
      let alive = true
      let reconnectTimer: ReturnType<typeof setTimeout> | null = null

      function connect() {
        if (!alive) return

        // Build WebSocket URL — resolve to the actual backend, not the
        // Vite dev proxy (which doesn't reliably forward WS upgrades).
        let wsUrl: string
        const apiBase = apiBaseUrl()
        if (apiBase.startsWith('http')) {
          // Production / Tauri: absolute URL from __OAD_API_BASE_URL__
          wsUrl = apiBase.replace(/^http/, 'ws')
        } else {
          // Dev mode: apiBase is "/api" (relative).  Point WS directly
          // at the backend so we don't depend on Vite's WS proxy.
          const host = window.location.hostname || 'localhost'
          const backendPort = '8000' // matches VITE_API_PROXY_TARGET default
          wsUrl = `ws://${host}:${backendPort}/api`
        }
        const url = withTokenParam(
          `${wsUrl}/${sessionId}/browser/screencast`,
        )

        const ws = new WebSocket(url)
        wsRef.current = ws
        ws.binaryType = 'arraybuffer'

        ws.onopen = () => {
          if (!alive) return
          notifyConnected(true)
        }

        ws.onmessage = (ev) => {
          if (!alive) return
          if (ev.data instanceof ArrayBuffer) {
            renderFrame(ev.data)
            onFrame?.()
          } else if (typeof ev.data === 'string') {
            try {
              const msg = JSON.parse(ev.data) as ScreencastStatus & { type?: string }
              if (msg.type === 'status') {
                onStatus?.({
                  active: msg.active,
                  url: msg.url,
                  title: msg.title,
                  tabs: msg.tabs,
                  cdpHttp: msg.cdp_http ?? msg.cdpHttp,
                })
              }
            } catch {
              // ignore
            }
          }
        }

        ws.onclose = () => {
          if (!alive) return
          notifyConnected(false)
          wsRef.current = null
          reconnectTimer = setTimeout(connect, 2000)
        }

        ws.onerror = () => {
          ws.close()
        }
      }

      function renderFrame(data: ArrayBuffer) {
        const canvas = canvasRef.current
        if (!canvas) return
        const ctx = canvas.getContext('2d')
        if (!ctx) return

        if (!imgRef.current) {
          imgRef.current = new Image()
        }
        const img = imgRef.current
        const blob = new Blob([data], { type: 'image/jpeg' })
        const objUrl = URL.createObjectURL(blob)

        img.onload = () => {
          if (
            canvas.width !== img.naturalWidth ||
            canvas.height !== img.naturalHeight
          ) {
            canvas.width = img.naturalWidth
            canvas.height = img.naturalHeight
            frameSizeRef.current = {
              w: img.naturalWidth,
              h: img.naturalHeight,
            }
          }
          ctx.drawImage(img, 0, 0)
          URL.revokeObjectURL(objUrl)
        }
        img.onerror = () => URL.revokeObjectURL(objUrl)
        img.src = objUrl
      }

      connect()

      return () => {
        alive = false
        if (reconnectTimer) clearTimeout(reconnectTimer)
        if (wsRef.current) {
          wsRef.current.close()
          wsRef.current = null
        }
        notifyConnected(false)
      }
    }, [sessionId, onStatus, onConnected, notifyConnected, onFrame])

    return (
      <canvas
        ref={canvasRef}
        className={className}
        tabIndex={interactive ? 0 : undefined}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          backgroundColor: 'var(--bg-key)',
          borderRadius: 'var(--radius-md, 6px)',
          cursor: interactive ? 'crosshair' : 'default',
          outline: 'none',
        }}
        onClick={handleClick}
        onDoubleClick={handleClick}
        onWheel={handleWheel}
        onKeyDown={handleKeyDown}
        onContextMenu={handleContextMenu}
      />
    )
  },
)
