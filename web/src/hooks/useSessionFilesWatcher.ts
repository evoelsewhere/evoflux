/**
 * useSessionFilesWatcher — watches for file changes using native Tauri filesystem watcher.
 *
 * Desktop-only implementation that:
 * 1. Starts the native file watcher when the component mounts
 * 2. Listens for file-change events
 * 3. Invalidates the team files query cache when workspace changes
 *
 * Replaces the HTTP SSE-based watcher for desktop-only mode.
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/queries'
import {
  isTauriAvailable,
  tauriStartFileWatcher,
  tauriStopFileWatcher,
  tauriOnFileChange,
  type FileChangeEvent,
} from '@/api/tauri-workspace'

export function useSessionFilesWatcher(sessionId: string | null, workspaceRoot?: string | null) {
  const queryClient = useQueryClient()
  const unlistenRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!sessionId || !workspaceRoot) return
    if (!isTauriAvailable()) return

    let cancelled = false

    async function startWatching() {
      try {
        // Start the native file watcher
        await tauriStartFileWatcher(workspaceRoot)

        if (cancelled) return

        // Listen for file change events
        unlistenRef.current = tauriOnFileChange((events: FileChangeEvent[]) => {
          // Invalidate the files query to trigger a refetch
          queryClient.invalidateQueries({ queryKey: queryKeys.team.files(sessionId) })
        })
      } catch (err) {
        console.error('Failed to start file watcher:', err)
      }
    }

    void startWatching()

    return () => {
      cancelled = true
      unlistenRef.current?.()
      unlistenRef.current = null

      // Stop the watcher (best-effort)
      if (workspaceRoot) {
        void tauriStopFileWatcher(workspaceRoot).catch(() => {})
      }
    }
  }, [sessionId, workspaceRoot, queryClient])
}
