/**
 * useSessionFilesWatcher — subscribes to the session-specific file-watch SSE
 * endpoint and invalidates the team files query cache when the workspace
 * changes (agent writes, uploads, renames, deletes).
 *
 * Mirrors useWorkspaceFileWatcher but targets the team session API so the
 * caller only needs the session ID — no workspace path required.
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiUrl } from '@/api/base-url'
import { queryKeys } from '@/queries'

export function useSessionFilesWatcher(sessionId: string | null) {
  const queryClient = useQueryClient()
  const abortRef = useRef<AbortController | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!sessionId) return

    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
    let stopped = false

    function flush() {
      if (!sessionId) return
      queryClient.invalidateQueries({ queryKey: queryKeys.team.files(sessionId) })
    }

    function scheduleBatch() {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(flush, 200)
    }

    async function connect() {
      if (stopped) return

      const url = apiUrl(`/team/${sessionId}/files/watch`)
      const controller = new AbortController()
      abortRef.current = controller

      try {
        const res = await fetch(url, { signal: controller.signal })
        if (!res.ok || !res.body) {
          throw new Error(`Watch stream HTTP ${res.status}`)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let eventType = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim()
            } else if (line === '') {
              if (eventType === 'fs_change') scheduleBatch()
              eventType = ''
            }
          }
        }
      } catch (err) {
        if (stopped || (err instanceof DOMException && err.name === 'AbortError')) return
      }

      if (!stopped) {
        reconnectTimeout = setTimeout(connect, 3000)
      }
    }

    void connect()

    return () => {
      stopped = true
      abortRef.current?.abort()
      if (reconnectTimeout) clearTimeout(reconnectTimeout)
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [sessionId, queryClient])
}
