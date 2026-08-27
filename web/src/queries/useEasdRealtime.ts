import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { easdRunStream } from '@/api/client'
import type { EasdPresenceEvent, EasdRealtimeEvent, EasdResyncEvent } from '@/api/types'
import { queryKeys } from './keys'

export type EasdRealtimeStatus = 'connecting' | 'live' | 'reconnecting' | 'off'

export function useEasdRealtime(runId: string | null, enabled = true) {
  const client = useQueryClient()
  const clientId = useRef(crypto.randomUUID())
  const lastSequence = useRef(0)
  const [status, setStatus] = useState<EasdRealtimeStatus>(enabled ? 'connecting' : 'off')
  const [viewerCount, setViewerCount] = useState(0)

  useEffect(() => {
    if (!runId || !enabled) {
      return
    }
    let disposed = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let controller: AbortController | null = null
    let reconnectAttempts = 0

    const refresh = () => Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.easd.detail(runId) }),
      client.invalidateQueries({ queryKey: queryKeys.easd.trace(runId) }),
      client.invalidateQueries({ queryKey: queryKeys.easd.recovery(runId) }),
      client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
    ])

    const scheduleReconnect = () => {
      if (disposed || retryTimer) return
      setStatus('reconnecting')
      const delay = Math.min(1_000 * (2 ** reconnectAttempts), 10_000)
      reconnectAttempts += 1
      retryTimer = setTimeout(() => {
        retryTimer = null
        connect()
      }, delay)
    }

    const connect = () => {
      if (disposed) return
      controller?.abort()
      controller = new AbortController()
      setStatus(reconnectAttempts ? 'reconnecting' : 'connecting')
      easdRunStream(
        runId,
        lastSequence.current,
        clientId.current,
        {
          onEvent: (type, raw) => {
            if (type === 'easd_presence') {
              const presence = raw as EasdPresenceEvent
              setViewerCount(presence.count)
              setStatus('live')
              reconnectAttempts = 0
              return
            }
            if (type === 'easd_resync_required') {
              const resync = raw as EasdResyncEvent
              if (resync.run_id !== runId) return
              lastSequence.current = 0
              void refresh()
              return
            }
            if (type !== 'easd_event') return
            const event = raw as EasdRealtimeEvent
            if (event.run_id !== runId || event.sequence <= lastSequence.current) return
            lastSequence.current = event.sequence
            setStatus('live')
            reconnectAttempts = 0
            void refresh()
          },
          onError: scheduleReconnect,
          onDone: scheduleReconnect,
        },
        controller.signal,
      )
    }

    connect()
    return () => {
      disposed = true
      controller?.abort()
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [client, enabled, runId])

  return { status, viewerCount }
}
