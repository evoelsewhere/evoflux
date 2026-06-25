/**
 * useWorkspaceFileWatcher — subscribes to the backend file-watch SSE endpoint
 * and invalidates TanStack Query caches when workspace files change externally.
 *
 * Connects when `workspace` is non-null, auto-reconnects on disconnect.
 * Debounces bursts into a single invalidation per 200ms window.
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiUrl } from '@/api/base-url'
import { queryKeys } from '@/queries'

interface FsChangeEvent {
  type: 'added' | 'modified' | 'deleted'
  path: string
}

export function useWorkspaceFileWatcher(workspace: string | null) {
  const queryClient = useQueryClient()
  const abortRef = useRef<AbortController | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingPathsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!workspace) return

    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
    let stopped = false

    function flush() {
      if (!workspace) return
      const paths = [...pendingPathsRef.current]
      pendingPathsRef.current.clear()

      if (paths.length === 0) return

      // Invalidate file list + status
      queryClient.invalidateQueries({ queryKey: queryKeys.coding.files(workspace) })
      queryClient.invalidateQueries({ queryKey: queryKeys.coding.status(workspace) })

      // Invalidate diff for changed paths
      queryClient.invalidateQueries({ queryKey: queryKeys.coding.diff(workspace) })
    }

    function scheduleBatch(paths: string[]) {
      for (const p of paths) pendingPathsRef.current.add(p)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(flush, 200)
    }

    async function connect() {
      if (stopped) return

      const params = new URLSearchParams({ workspace: workspace! })
      const url = apiUrl(`/team/workspace/watch?${params}`)

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

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          let eventType = ''
          let dataLines: string[] = []

          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              dataLines.push(line.slice(5).trim())
            } else if (line === '') {
              // End of event
              if (eventType === 'fs_change' && dataLines.length > 0) {
                try {
                  const events: FsChangeEvent[] = JSON.parse(dataLines.join('\n'))
                  scheduleBatch(events.map((e) => e.path))
                } catch {
                  // Malformed JSON — skip
                }
              }
              eventType = ''
              dataLines = []
            }
          }
        }
      } catch (err) {
        if (stopped || (err instanceof DOMException && err.name === 'AbortError')) {
          return
        }
      }

      // Reconnect after delay (exponential backoff capped at 10s)
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
      pendingPathsRef.current.clear()
    }
  }, [workspace, queryClient])
}
